import cctestbedv2 as cctestbed
import cctestbed_generate_experiments as generate_experiments
from contextlib import ExitStack, contextmanager
from urllib.parse import urlsplit, urlunsplit
from config import *

import logging
from logging.config import fileConfig
import time
import pandas as pd
import glob
import traceback
import os
import yaml
import datetime
import argparse
import json
import itertools

#mkdir websites/nytimes/
#wget -E -H -k -K -p https://www.nytimes.com

QUEUE_SIZE_TABLE = {
    35: {5:16, 10:32, 15:64},
    85: {5:64, 10:128, 15:128},
    130: {5:64, 10:128, 15:256},
    275: {5:128, 10:256, 15:512}}

def is_completed_experiment(experiment_name):
    num_completed = glob.glob('/tmp/data-tmp/{}-*.tar.gz'.format(experiment_name))
    experiment_done = len(num_completed) > 0
    if experiment_done:
        logging.warning(
            'Skipping completed experiment: {}'.format(experiment_name))
    return experiment_done

def ran_experiment_today(experiment_name):
    today = datetime.datetime.now().isoformat()[:10].replace('-','')
    num_completed = glob.glob('/tmp/data-tmp/{}-{}*.tar.gz'.format(experiment_name, today))
    experiment_done = len(num_completed) > 0
    if experiment_done:
        logging.warning(
            'Skipping completed experiment (today): {}'.format(experiment_name))
    return experiment_done
          
def get_nping_rtt(url_ip):
    cmd = "nping -v-1 -H -c 5 {} | grep -oP 'Avg rtt:\s+\K.*(?=ms)'".format(url_ip)
    rtt = cctestbed.run_local_command(cmd, shell=True)
    return rtt

def run_rtt_monitor(url_ip):
    cmd = "nping --delay 5s {} > {}  &".format(url_ip, '')
    rtt = cctestbed.run_local_command(cmd, shell=True)
    return rtt

def start_iperf_flows(experiment, stack):
    for flow in experiment.flows:
        if flow.kind != 'iperf':
            continue
        start_server_cmd = ('iperf3 --server '
                            '--bind {} '
                            '--port {} '
                            '--one-off '
                            '--affinity {} '
                            '--logfile {} ').format(
                                experiment.server.ip_lan,
                                flow.server_port,
                                1,
                                flow.server_log)
        start_server = cctestbed.RemoteCommand(start_server_cmd,
                                            experiment.server.ip_wan,
                                            username=experiment.server.username,
                                            logs=[flow.server_log],
                                            key_filename=experiment.server.key_filename)
        stack.enter_context(start_server())

    for idx, flow in enumerate(experiment.flows):
        if flow.kind != 'iperf':
            continue
        # make sure first flow runs for the whole time regardless of start time
        # note this assumes self.flows is sorted by start time
        flow_duration = flow.end_time - flow.start_time
        if idx == 0:
            flow_duration = flow.end_time
        start_client_cmd = ('iperf3 --client {} '
                            '--port {} '
                            '--verbose '
                            '--bind {} '
                            '--cport {} '
                            '--linux-congestion {} '
                            '--interval 0.5 '
                            '--time {} '
                            #'--length 1024K '#1024K '
                            '--affinity {} '
                            #'--set-mss 500 ' # default is 1448
                            #'--window 100K '
                            '--zerocopy '


                            '--json '
                            '--logfile {} ').format(experiment.server.ip_lan,
                                                    flow.server_port,
                                                    flow.client.ip_lan,
                                                    flow.client_port,
                                                    flow.ccalg,
                                                    flow_duration,
                                                    idx % 32,
                                                    flow.client_log)
        start_client = cctestbed.RemoteCommand(
            start_client_cmd,
            flow.client.ip_wan,
            username=flow.client.username,
            logs=[flow.client_log],
            key_filename=flow.client.key_filename)
        stack.enter_context(start_client())
        
def run_experiment_1vmany(website, url, competing_ccalg, num_competing,
                          btlbw=10, queue_size=128, rtt=35, duration=60,
                          chrome=False):
    experiment_name = '{}bw-{}rtt-{}q-{}-{}{}-{}s'.format(btlbw, rtt,
                                                      queue_size, website,
                                                          num_competing, competing_ccalg, duration)
    logging.info('Creating experiment for website: {}'.format(website))
    url_ip = get_website_ip(url)
    logging.info('Got website IP: {}'.format(url_ip))
    website_rtt = int(float(get_nping_rtt(url_ip)))
    logging.info('Got website RTT: {}'.format(website_rtt))

    if website_rtt >= rtt:
        logging.warning('Skipping experiment with website RTT {} >= {}'.format(
            website_rtt, rtt))
        return -1

    client = HOST_CLIENT_TEMPLATE
    client['ip_wan'] = url_ip
    client = cctestbed.Host(**client)
    server = HOST_SERVER
    
    server_nat_ip = HOST_CLIENT.ip_wan #'128.104.222.182'  taro
    server_port = 5201
    client_port = 5555

    flow = {'ccalg': 'reno',
            'end_time': duration,
            'rtt': rtt - website_rtt,
            'start_time': 0}
    flows = [cctestbed.Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                            end_time=flow['end_time'], rtt=flow['rtt'],
                            server_port=server_port, client_port=client_port,
                            client_log=None, server_log=None, kind='website',
                            client=client)]
    for x in range(num_competing):
        server_port += 1
        client_port += 1
        flows.append(cctestbed.Flow(ccalg=competing_ccalg,
                                    start_time=flow['start_time'],
                                    end_time=flow['end_time'], rtt=rtt,
                                    server_port=server_port, client_port=client_port,
                                    client_log=None, server_log=None, kind='iperf',
                                    client=HOST_CLIENT))
    
    exp = cctestbed.Experiment(name=experiment_name,
                     btlbw=btlbw,
                     queue_size=queue_size,
                     flows=flows, server=server, client=client,
                     config_filename='experiments-all-ccalgs-aws.yaml',
                     server_nat_ip=server_nat_ip)
    
    logging.info('Running experiment: {}'.format(exp.name))

    # make sure tcpdump cleaned up
    logging.info('Making sure tcpdump is cleaned up')
    with cctestbed.get_ssh_client(
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename) as ssh_client:
        cctestbed.exec_command(
            ssh_client,
            exp.client.ip_wan,
            'sudo pkill -9 tcpdump')
                        
    with ExitStack() as stack:
        # add DNAT rule
        stack.enter_context(add_dnat_rule(exp, url_ip))
        # add route to URL
        stack.enter_context(add_route(exp, url_ip))
        # add dns entry
        stack.enter_context(add_dns_rule(exp, website, url_ip))
        exp._run_tcpdump('server', stack)
        # run the flow
        # turns out there is a bug when using subprocess and Popen in Python 3.5
        # so skip ping needs to be true
        # https://bugs.python.org/issue27122
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(ping_source='server', skip_ping=False, bess_config_name='active-middlebox-pmd-fairness'))
        # give bess some time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        stack.enter_context(exp._run_rtt_monitor())
        start_iperf_flows(exp,stack)
        with cctestbed.get_ssh_client(exp.server.ip_wan,
                                      exp.server.username,
                                      key_filename=exp.server.key_filename) as ssh_client:
            filename = os.path.basename(url)
            if filename.strip() == '':
                logging.warning('Could not get filename from URL')
            if chrome:
                start_flow_cmd = 'timeout {}s google-chrome --headless --remote-debugging-port=9222 --autoplay-policy=no-user-gesture-required {}'.format(duration+5, url)
            else:
                start_flow_cmd = 'timeout {}s wget --no-check-certificate --no-cache --delete-after --connect-timeout=10 --tries=3 --bind-address {}  -P /tmp/ {} || rm -f /tmp/{}.tmp*'.format(duration+5, exp.server.ip_lan, url, filename)
                
            # won't return until flow is done
            flow_start_time = time.time()
            _, stdout, _ = cctestbed.exec_command(ssh_client, exp.server.ip_wan, start_flow_cmd)
            exit_status = stdout.channel.recv_exit_status()
            flow_end_time = time.time()
            logging.info('Flow ran for {} seconds'.format(flow_end_time - flow_start_time))
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))

        logging.info('Dumping website data to log: {}'.format(exp.logs['website_log']))
        with open(exp.logs['website_log'], 'w') as f:
            website_info = {}
            website_info['website'] = website
            website_info['url'] = url
            website_info['website_rtt'] = website_rtt
            website_info['url_ip'] = url_ip
            website_info['flow_runtime'] = flow_end_time - flow_start_time 
            json.dump(website_info, f)

        if exit_status != 0:
            if exit_status == 124: # timeout exit status
                print('Timeout. Flow longer than {}s.'.format(duration+5))
                logging.warning('Timeout. Flow longer than {}s.'.format(duration+5))
            else:
                logging.error(stdout.read())
                raise RuntimeError('Error running flow.')

    proc = exp._compress_logs_url()
    return proc


def run_experiment_1vapache(website, url, competing_ccalg, 
                          btlbw=10, queue_size=128, rtt=35, duration=60):
    # force one competing apache flow
    num_competing = 1
    experiment_name = '{}bw-{}rtt-{}q-{}-1apache-{}'.format(
        btlbw, rtt, queue_size, website, competing_ccalg)
    logging.info('Creating experiment for website: {}'.format(website))
    url_ip = get_website_ip(url)
    logging.info('Got website IP: {}'.format(url_ip))
    website_rtt = int(float(get_nping_rtt(url_ip)))
    logging.info('Got website RTT: {}'.format(website_rtt))

    if website_rtt >= rtt:
        logging.warning('Skipping experiment with website RTT {} >= {}'.format(
            website_rtt, rtt))
        return -1

    client = HOST_CLIENT_TEMPLATE
    client['ip_wan'] = url_ip
    client = cctestbed.Host(**client)
    server = HOST_SERVER
    
    server_nat_ip = HOST_CLIENT.ip_wan #'128.104.222.182'  taro
    server_port = 5201
    client_port = 5555

    flow = {'ccalg': 'reno',
            'end_time': duration,
            'rtt': rtt - website_rtt,
            'start_time': 0}
    flows = [cctestbed.Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                            end_time=flow['end_time'], rtt=flow['rtt'],
                            server_port=server_port, client_port=client_port,
                            client_log=None, server_log=None, kind='website',
                            client=client)]
    # competing are apache flows
    for x in range(num_competing):
        server_port += 1
        client_port += 1
        flows.append(cctestbed.Flow(ccalg=competing_ccalg,
                                    start_time=flow['start_time'],
                                    end_time=flow['end_time'],
                                    rtt=rtt,
                                    server_port=server_port,
                                    client_port=client_port,
                                    client_log=None,
                                    server_log=None,
                                    kind='apache',
                                    client=HOST_CLIENT))
    
    exp = cctestbed.Experiment(name=experiment_name,
                     btlbw=btlbw,
                     queue_size=queue_size,
                     flows=flows, server=server, client=client,
                     config_filename='None',
                     server_nat_ip=server_nat_ip)
    
    logging.info('Running experiment: {}'.format(exp.name))

    # make sure tcpdump cleaned up
    logging.info('Making sure tcpdump is cleaned up')
    with cctestbed.get_ssh_client(
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename) as ssh_client:
        cctestbed.exec_command(
            ssh_client,
            exp.client.ip_wan,
            'sudo pkill -9 tcpdump')
                        
    with ExitStack() as stack:
        # add DNAT rule
        stack.enter_context(add_dnat_rule(exp, url_ip))
        # add route to URL
        stack.enter_context(add_route(exp, url_ip))
        # add dns entry
        stack.enter_context(add_dns_rule(exp, website, url_ip))
        exp._run_tcpdump('server', stack)
        # run the flow
        # turns out there is a bug when using subprocess and Popen in Python 3.5
        # so skip ping needs to be true
        # https://bugs.python.org/issue27122
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(ping_source='server', skip_ping=False, bess_config_name='active-middlebox-pmd-fairness'))
        # give bess some time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        stack.enter_context(exp._run_rtt_monitor())
        filename = os.path.basename(url)
        if filename.strip() == '':
            logging.warning('Could not get filename from URL')
        start_flow_cmd = 'wget --quiet --background --no-check-certificate --no-cache --delete-after --connect-timeout=10 --tries=1 --bind-address {}  -P /tmp/ "{}"'.format(exp.server.ip_lan, url)   
        start_flow = cctestbed.RemoteCommand(
            start_flow_cmd,
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename,
            cleanup_cmd='rm -f /tmp/{}*'.format(filename),
            pgrep_string=url)
        start_flow_pid = stack.enter_context(start_flow())
        # waiting time before starting apache flow
        time.sleep(10)
        assert(start_flow._is_running())
        apache_flow = start_apache_flow(exp.flows[1], exp, stack)
        logging.info('Waiting for apache flow to finish')
        apache_flow._wait()
        # add add a time buffer before finishing up experiment
        logging.info('Apache flow finished')
        time.sleep(5)
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))

        logging.info('Dumping website data to log: {}'.format(exp.logs['website_log']))
        with open(exp.logs['website_log'], 'w') as f:
            website_info = {}
            website_info['website'] = website
            website_info['url'] = url
            website_info['website_rtt'] = website_rtt
            website_info['url_ip'] = url_ip
            website_info['flow_runtime'] = None
            #flow_end_time - flow_start_time 
            json.dump(website_info, f)

    proc = exp._compress_logs_url()
    return proc

def run_experiment_rtt(website, url, competing_ccalg, num_competing,
                          btlbw=10, queue_size=128, rtt=35, duration=60):
    experiment_name = '{}bw-{}rtt-{}q-{}-{}{}-diffrtt-{}s'.format(
        btlbw, rtt, queue_size, website,
        num_competing, competing_ccalg, duration)
    logging.info('Creating experiment for website: {}'.format(website))
    url_ip = get_website_ip(url)
    logging.info('Got website IP: {}'.format(url_ip))
    website_rtt = int(float(get_nping_rtt(url_ip)))
    logging.info('Got website RTT: {}'.format(website_rtt))

    if website_rtt >= rtt:
        logging.warning('Skipping experiment with website RTT {} >= {}'.format(
            website_rtt, rtt))
        return -1

    client = HOST_CLIENT_TEMPLATE
    client['ip_wan'] = url_ip
    client = cctestbed.Host(**client)
    server = HOST_SERVER
    
    server_nat_ip = HOST_CLIENT.ip_wan #'128.104.222.182'  taro
    server_port = 5201
    client_port = 5555

    flow = {'ccalg': 'reno',
            'end_time': duration,
            'rtt': 1,
            'start_time': 0}
    flows = [cctestbed.Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                            end_time=flow['end_time'], rtt=flow['rtt'],
                            server_port=server_port, client_port=client_port,
                            client_log=None, server_log=None, kind='website',
                            client=client)]
    for x in range(num_competing):
        server_port += 1
        client_port += 1
        flows.append(cctestbed.Flow(ccalg=competing_ccalg,
                                    start_time=flow['start_time'],
                                    end_time=flow['end_time'], rtt=rtt,
                                    server_port=server_port, client_port=client_port,
                                    client_log=None, server_log=None, kind='iperf',
                                    client=HOST_CLIENT))
    
    exp = cctestbed.Experiment(name=experiment_name,
                     btlbw=btlbw,
                     queue_size=queue_size,
                     flows=flows, server=server, client=client,
                     config_filename='experiments-all-ccalgs-aws.yaml',
                     server_nat_ip=server_nat_ip)
    
    logging.info('Running experiment: {}'.format(exp.name))

    # make sure tcpdump cleaned up
    logging.info('Making sure tcpdump is cleaned up')
    with cctestbed.get_ssh_client(
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename) as ssh_client:
        cctestbed.exec_command(
            ssh_client,
            exp.client.ip_wan,
            'sudo pkill -9 tcpdump')
                        
    with ExitStack() as stack:
        # add DNAT rule
        stack.enter_context(add_dnat_rule(exp, url_ip))
        # add route to URL
        stack.enter_context(add_route(exp, url_ip))
        # add dns entry
        stack.enter_context(add_dns_rule(exp, website, url_ip))
        exp._run_tcpdump('server', stack)
        # run the flow
        # turns out there is a bug when using subprocess and Popen in Python 3.5
        # so skip ping needs to be true
        # https://bugs.python.org/issue27122
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(ping_source='server', skip_ping=False, bess_config_name='active-middlebox-pmd-fairness'))
        # give bess some time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        stack.enter_context(exp._run_rtt_monitor())
        start_iperf_flows(exp,stack)
        with cctestbed.get_ssh_client(exp.server.ip_wan,
                                      exp.server.username,
                                      key_filename=exp.server.key_filename) as ssh_client:
            filename = os.path.basename(url)
            if filename.strip() == '':
                logging.warning('Could not get filename from URL')
            start_flow_cmd = 'timeout {}s wget --no-check-certificate --no-cache --delete-after --connect-timeout=10 --tries=3 --bind-address {}  -P /tmp/ {} || rm -f /tmp/{}.tmp*'.format(duration+5, exp.server.ip_lan, url, filename)
            # won't return until flow is done
            flow_start_time = time.time()
            _, stdout, _ = cctestbed.exec_command(ssh_client, exp.server.ip_wan, start_flow_cmd)
            exit_status = stdout.channel.recv_exit_status()
            flow_end_time = time.time()
            logging.info('Flow ran for {} seconds'.format(flow_end_time - flow_start_time))
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))

        logging.info('Dumping website data to log: {}'.format(exp.logs['website_log']))
        with open(exp.logs['website_log'], 'w') as f:
            website_info = {}
            website_info['website'] = website
            website_info['url'] = url
            website_info['website_rtt'] = website_rtt
            website_info['url_ip'] = url_ip
            website_info['flow_runtime'] = flow_end_time - flow_start_time 
            json.dump(website_info, f)

        if exit_status != 0:
            if exit_status == 124: # timeout exit status
                print('Timeout. Flow longer than {}s.'.format(duration+5))
                logging.warning('Timeout. Flow longer than {}s.'.format(duration+5))
            else:
                logging.error(stdout.read())
                raise RuntimeError('Error running flow.')

    proc = exp._compress_logs_url()
    return proc


@contextmanager
def add_dnat_rule(exp, url_ip):
    with cctestbed.get_ssh_client(exp.server_nat_ip,
                                  exp.server.username,
                                  exp.server.key_filename) as ssh_client:
        dnat_rule_cmd = 'sudo iptables -t nat -A PREROUTING -i enp1s0f0 --source {} -j DNAT --to-destination {}'.format(url_ip, exp.server.ip_lan)
        cctestbed.exec_command(ssh_client, exp.server_nat_ip, dnat_rule_cmd)
    try:
        yield
    finally:
        # remove DNAT rule once down with this context
        with cctestbed.get_ssh_client(exp.server_nat_ip,
                                      exp.server.username,
                                      exp.server.key_filename) as ssh_client:
            # TODO: remove hard coding of the ip addr here
            dnat_delete_cmd = 'sudo iptables -t nat --delete PREROUTING 1'
            cctestbed.exec_command(ssh_client, exp.server.ip_wan, dnat_delete_cmd) 

@contextmanager
def add_route(exp, url_ip, gateway_ip=None):
    with cctestbed.get_ssh_client(exp.server.ip_wan,
                                  exp.server.username,
                                  key_filename=exp.server.key_filename) as ssh_client:
        if gateway_ip is None:
            gateway_ip = exp.client.ip_lan
        add_route_cmd = 'sudo route add {} gw {}'.format(url_ip, gateway_ip)
        cctestbed.exec_command(ssh_client, exp.server.ip_wan, add_route_cmd)
    try:
        yield
    finally:
        with cctestbed.get_ssh_client(exp.server.ip_wan,
                                      exp.server.username,
                                      key_filename=exp.server.key_filename) as ssh_client:
            del_route_cmd = 'sudo route del {}'.format(url_ip)
            cctestbed.exec_command(ssh_client, exp.server.ip_wan, del_route_cmd)

@contextmanager
def add_dns_rule(exp, website, url_ip):
    with cctestbed.get_ssh_client(exp.server.ip_wan,
                                  exp.server.username,
                                  key_filename=exp.server.key_filename) as ssh_client:
        add_dns_cmd = "echo '{}   {}' | sudo tee -a /etc/hosts".format(url_ip, website)
        cctestbed.exec_command(ssh_client, exp.server.ip_wan, add_dns_cmd)
    try:
        yield
    finally:
        with cctestbed.get_ssh_client(exp.server.ip_wan,
                                      exp.server.username,
                                      key_filename=exp.server.key_filename) as ssh_client:
            # will delete last line of /etc/hosts file
            # TODO: should probs check that it's the line we want to delete
            del_dns_cmd = "sudo sed -i '$ d' /etc/hosts"
            cctestbed.exec_command(ssh_client, exp.server.ip_wan, del_dns_cmd)
    
            
def get_website_ip(url):
    url_parts = list(urlsplit(url.strip()))
    hostname = url_parts[1]
    ip_addrs = cctestbed.run_local_command(
        "nslookup {} | awk '/^Address: / {{ print $2 ; exit }}'".format(hostname), shell=True)
    ip_addr = ip_addrs.split('\n')[0]
    if ip_addr.strip() == '':
        raise ValueError('Could not find IP addr for {}'.format(url))
    return ip_addr

def update_url_with_ip(url, url_ip):
    # also make sure use http and not https
    url_parts = list(urlsplit(url.strip()))
    url_parts[0] = 'http'
    url_parts[1] = url_ip
    return urlunsplit(url_parts)

def start_apache_flow(flow, experiment, stack):
    # start apache server which is running on the cctestbed-client
    with cctestbed.get_ssh_client(flow.client.ip_wan,
                                  flow.client.username,
                                  key_filename=flow.client.key_filename) as ssh_client:
        start_apache_cmd = "sudo service apache2 start"
        cctestbed.exec_command(ssh_client, flow.client.ip_wan, start_apache_cmd)
    # change default cclag for client
    with cctestbed.get_ssh_client(flow.client.ip_wan,
                                  flow.client.username,
                                  key_filename=flow.client.key_filename) as ssh_client:
        change_ccalg = 'echo {} | sudo tee /proc/sys/net/ipv4/tcp_congestion_control'.format(flow.ccalg)
        cctestbed.exec_command(ssh_client, flow.client.ip_wan, change_ccalg)
    #TODO: should change ccalg back to default after running flow

    # delay flow start for start time plus 3 seconds
    web_download_cmd = 'wget --quiet --background --span-hosts --no-cache --delete-after --bind-address {} -P /tmp/ "http://{}:1234/www.nytimes.com"'.format(experiment.server.ip_lan, experiment.client.ip_lan)
    start_download = cctestbed.RemoteCommand(
            web_download_cmd,
            experiment.server.ip_wan,
            username=experiment.server.username,
            key_filename=experiment.server.key_filename,
            pgrep_string='http://{}:1234/www.nytimes.com'.format(
                experiment.client.ip_lan))
    stack.enter_context(start_download())
    return start_download


def start_video_flow(flow, experiment, stack):
    # start apache server which is running on the cctestbed-client
    with cctestbed.get_ssh_client(
            flow.client.ip_wan,
            flow.client.username,
            key_filename=flow.client.key_filename) as ssh_client:
        start_apache_cmd = "sudo service apache2 start"
        cctestbed.exec_command(
            ssh_client, flow.client.ip_wan, start_apache_cmd)
    # change default cclag for client
    with cctestbed.get_ssh_client(
            flow.client.ip_wan,
            flow.client.username,
            key_filename=flow.client.key_filename) as ssh_client:
        change_ccalg = 'echo {} | sudo tee /proc/sys/net/ipv4/tcp_congestion_control'.format(flow.ccalg)
        cctestbed.exec_command(ssh_client, flow.client.ip_wan, change_ccalg)

    #TODO: should change ccalg back to default after running flow

    # delay flow start for start time plus 3 seconds
    web_download_cmd = 'timeout {}s google-chrome --disable-gpu --headless --remote-debugging-port=9222 --autoplay-policy=no-user-gesture-required "http://{}:1234/"'.format(flow.end_time, experiment.client.ip_lan)
    start_download = cctestbed.RemoteCommand(
        web_download_cmd,
        experiment.server.ip_wan,
        username=experiment.server.username,
        key_filename=experiment.server.key_filename,
        pgrep_string='google-chrome'.format(
            experiment.client.ip_lan))
    stack.enter_context(start_download())
    return start_download



def run_iperf_experiments(ccalg, btlbw, rtt, queue_size, duration, num_flows):
    experiment_name = '{}-{}bw-{}rtt-{}q-{}iperf'.format(ccalg, btlbw, rtt, queue_size, num_flows)
    client = HOST_CLIENT
    server = HOST_SERVER
    server_port = 5201
    client_port = 5555

    flow = {'ccalg':ccalg,
            'end_time': duration,
            'rtt': rtt,
            'start_time': 0}
    flows = []
    for x in range(num_flows):
        server_port += 1
        client_port += 1
        flows.append(cctestbed.Flow(ccalg=ccalg,
                                    start_time=flow['start_time'],
                                    end_time=flow['end_time'], rtt=rtt,
                                    server_port=server_port, client_port=client_port,
                                    client_log=None, server_log=None, kind='iperf',
                                    client=HOST_CLIENT))
    exp = cctestbed.Experiment(name=experiment_name,
                               btlbw=btlbw,
                               queue_size=queue_size,
                               flows=flows,
                               server=server,
                               client=client,
                               config_filename='None',
                               server_nat_ip=None)

    logging.info('Running experiment: {}'.format(exp.name))

    logging.info('Making sure tcpdump is cleaned up ')
    with cctestbed.get_ssh_client(
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename) as ssh_client:
        cctestbed.exec_command(
            ssh_client,
            exp.server.ip_wan,
            'sudo pkill -9 tcpdump')

    with ExitStack() as stack:
        exp._run_tcpdump('server', stack)
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(ping_source='client',
                                          skip_ping=False,
                                          bess_config_name='active-middlebox-pmd-fairness'))
        # give bess time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        start_iperf_flows(exp, stack)
        time.sleep(duration+5)
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))

    proc = exp._compress_logs_url()
    return proc


def run_apache_experiments(ccalg, btlbw, rtt, queue_size, duration):
    experiment_name = '{}-{}bw-{}rtt-{}q-apache'.format(ccalg, btlbw, rtt, queue_size)
    client = HOST_CLIENT
    server = HOST_SERVER
    server_port = 5201
    client_port = 5555

    flow = {'ccalg':ccalg,
            'end_time': duration,
            'rtt': rtt,
            'start_time': 0}
    flows = [cctestbed.Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                            end_time=flow['end_time'], rtt=flow['rtt'],
                            server_port=server_port, client_port=client_port,
                            client_log=None, server_log=None, kind='apache',
                            client=client)]
    exp = cctestbed.Experiment(name=experiment_name,
                               btlbw=btlbw,
                               queue_size=queue_size,
                               flows=flows,
                               server=server,
                               client=client,
                               config_filename='None',
                               server_nat_ip=None)

    logging.info('Running experiment: {}'.format(exp.name))

    logging.info('Making sure tcpdump is cleaned up ')
    with cctestbed.get_ssh_client(
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename) as ssh_client:
        cctestbed.exec_command(
            ssh_client,
            exp.client.ip_wan,
            'sudo pkill -9 tcpdump')

    with ExitStack() as stack:
        exp._run_tcpdump('server', stack)
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(ping_source='client',
                                          skip_ping=False,
                                          bess_config_name='active-middlebox-pmd-fairness'))
        # give bess time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        apache_flow = start_apache_flow(exp.flows[0], exp, stack)
        # wait for flow to finish
        apache_flow._wait()
        # add add a time buffer before finishing up experiment
        logging.info('Apache flow finished')
        # add add a time buffer before finishing up experiment
        time.sleep(5)
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))

    proc = exp._compress_logs_url()
    return proc

def run_video_experiments(ccalg, btlbw, rtt, queue_size, duration):
    experiment_name = '{}-{}bw-{}rtt-{}q-video-{}s'.format(
        ccalg, btlbw, rtt, queue_size, duration)
    client = HOST_CLIENT
    server = HOST_SERVER
    server_port = 5201
    client_port = 5555

    flow = {'ccalg':ccalg,
            'end_time': duration,
            'rtt': rtt,
            'start_time': 0}
    flows = [cctestbed.Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                            end_time=flow['end_time'], rtt=flow['rtt'],
                            server_port=server_port, client_port=client_port,
                            client_log=None, server_log=None, kind='video',
                            client=client)]
    exp = cctestbed.Experiment(name=experiment_name,
                               btlbw=btlbw,
                               queue_size=queue_size,
                               flows=flows,
                               server=server,
                               client=client,
                               config_filename='None',
                               server_nat_ip=None)

    logging.info('Running experiment: {}'.format(exp.name))

    logging.info('Making sure tcpdump is cleaned up ')
    with cctestbed.get_ssh_client(
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename) as ssh_client:
        cctestbed.exec_command(
            ssh_client,
            exp.client.ip_wan,
            'sudo pkill -9 tcpdump')

    with ExitStack() as stack:
        exp._run_tcpdump('server', stack)
        exp._run_tcpdump('server', stack, capture_http=True)
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(
            ping_source='client',
            skip_ping=False,
            bess_config_name='active-middlebox-pmd-fairness'))
        # give bess time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        video_flow = start_video_flow(exp.flows[0], exp, stack)
        logging.info('Waiting for flow to finish')
        # wait for flow to finish
        video_flow._wait()
        # add add a time buffer before finishing up experiment
        logging.info('Video flow finished')
        # add add a time buffer before finishing up experiment
        time.sleep(5)
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))

    proc = exp._compress_logs_url()
    return proc


def run_experiment_1video(website, url, competing_ccalg, 
                          btlbw=10, queue_size=128, rtt=35, duration=60):
    # force one competing video flow
    num_competing = 1
    experiment_name = '{}bw-{}rtt-{}q-{}-1svideo-{}-{}s'.format(
        btlbw, rtt, queue_size, website, competing_ccalg, duration)
    logging.info('Creating experiment for website: {}'.format(website))
    url_ip = get_website_ip(url)
    logging.info('Got website IP: {}'.format(url_ip))
    website_rtt = int(float(get_nping_rtt(url_ip)))
    logging.info('Got website RTT: {}'.format(website_rtt))

    if website_rtt >= rtt:
        logging.warning('Skipping experiment with website RTT {} >= {}'.format(
            website_rtt, rtt))
        return -1

    client = HOST_CLIENT_TEMPLATE
    client['ip_wan'] = url_ip
    client = cctestbed.Host(**client)
    server = HOST_SERVER
    
    server_nat_ip = HOST_CLIENT.ip_wan #'128.104.222.182'  taro
    server_port = 5201
    client_port = 5555

    flow = {'ccalg': 'reno',
            'end_time': duration+20,
            'rtt': rtt - website_rtt,
            'start_time': 0}
    flows = [cctestbed.Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                            end_time=flow['end_time'], rtt=flow['rtt'],
                            server_port=server_port, client_port=client_port,
                            client_log=None, server_log=None, kind='website',
                            client=client)]
    # competing are apache flows
    for x in range(num_competing):
        server_port += 1
        client_port += 1
        flows.append(cctestbed.Flow(ccalg=competing_ccalg,
                                    start_time=flow['start_time'],
                                    end_time=duration,
                                    rtt=rtt,
                                    server_port=server_port,
                                    client_port=client_port,
                                    client_log=None,
                                    server_log=None,
                                    kind='video',
                                    client=HOST_CLIENT))
    
    exp = cctestbed.Experiment(name=experiment_name,
                     btlbw=btlbw,
                     queue_size=queue_size,
                     flows=flows, server=server, client=client,
                     config_filename='None',
                     server_nat_ip=server_nat_ip)
    
    logging.info('Running experiment: {}'.format(exp.name))

    # make sure tcpdump cleaned up
    logging.info('Making sure tcpdump is cleaned up')
    with cctestbed.get_ssh_client(
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename) as ssh_client:
        cctestbed.exec_command(
            ssh_client,
            exp.client.ip_wan,
            'sudo pkill -9 tcpdump')
                        
    with ExitStack() as stack:
        # add DNAT rule
        stack.enter_context(add_dnat_rule(exp, url_ip))
        # add route to URL
        stack.enter_context(add_route(exp, url_ip))
        # add dns entry
        stack.enter_context(add_dns_rule(exp, website, url_ip))
        exp._run_tcpdump('server', stack)
        exp._run_tcpdump('server', stack, capture_http=True)
        # run the flow
        # turns out there is a bug when using subprocess and Popen in Python 3.5
        # so skip ping needs to be true
        # https://bugs.python.org/issue27122
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(ping_source='server', skip_ping=False, bess_config_name='active-middlebox-pmd-fairness'))
        # give bess some time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        stack.enter_context(exp._run_rtt_monitor())
        filename = os.path.basename(url)
        if filename.strip() == '':
            logging.warning('Could not get filename from URL')
        start_flow_cmd = 'wget --quiet --background --no-check-certificate --no-cache --delete-after --connect-timeout=10 --tries=1 --bind-address {}  -P /tmp/ "{}"'.format(exp.server.ip_lan, url)   
        start_flow = cctestbed.RemoteCommand(
            start_flow_cmd,
            exp.server.ip_wan,
            username=exp.server.username,
            key_filename=exp.server.key_filename,
            cleanup_cmd='rm -f /tmp/{}*'.format(filename),
            pgrep_string=url)
        start_flow_pid = stack.enter_context(start_flow())
        # waiting time before starting apache flow
        time.sleep(10)
        assert(start_flow._is_running())
        video_flow = start_video_flow(exp.flows[1], exp, stack)
        logging.info('Waiting for video flow to finish')
        video_flow._wait()
        # add add a time buffer before finishing up experiment
        logging.info('Video flow finished')
        time.sleep(5)
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))

        logging.info('Dumping website data to log: {}'.format(exp.logs['website_log']))
        with open(exp.logs['website_log'], 'w') as f:
            website_info = {}
            website_info['website'] = website
            website_info['url'] = url
            website_info['website_rtt'] = website_rtt
            website_info['url_ip'] = url_ip
            website_info['flow_runtime'] = None
            #flow_end_time - flow_start_time 
            json.dump(website_info, f)

    proc = exp._compress_logs_url()
    return proc



def main(tests, websites,
         nums_competing, competing_ccalgs,
         duration, ntwrk_conditions=None, repeat=1,
         chrome=False):
    completed_experiment_procs = []
    logging.info('Found {} websites'.format(len(websites)))
    print('Found {} websites'.format(len(websites)))
    if ntwrk_conditions is None:
        ntwrk_conditions = [(5,35), (5,85), (5,130), (5,275),
                            (10,35), (10,85), (10,130), (10,275),
                            (15,35), (15,85), (15,130), (15,275)]
    repetitions = list(range(repeat))
    exp_params = list(itertools.product(tests, websites, nums_competing,
                                        competing_ccalgs, [duration],
                                        ntwrk_conditions, repetitions))
    logging.info('Found {} experiments'.format(len(exp_params)))
    num_completed_experiments = 0
    for params in exp_params:
        try:
            test = params[0]
            website, url = params[1]
            num_competing = params[2]
            competing_ccalg = params[3]
            duration = params[4]
            btlbw, rtt, queue_size = params[5]
            repetition = params[6]
            
            num_completed_experiments += 1
            too_small_rtt = 0
            print('Running experiment {}/{} params={}'.format(
                num_completed_experiments, len(exp_params), params))

            if rtt <= too_small_rtt:
                print('Skipping experiment RTT too small')
                continue
        
            if test == 'iperf':
                proc = run_iperf_experiments(competing_ccalg,
                                             btlbw,
                                             rtt,
                                             queue_size,
                                             duration,
                                             num_competing)
            elif test == 'iperf-website':
                proc = run_experiment_1vmany(website,
                                             url,
                                             competing_ccalg,
                                             num_competing,
                                             btlbw,
                                             queue_size,
                                             rtt,
                                             duration,
                                             chrome)
            elif test == 'apache':
                proc = run_apache_experiments(competing_ccalg,
                                              btlbw,
                                              rtt,
                                              queue_size,
                                              duration)
            elif test == 'apache-website':
                proc = run_experiment_1vapache(website=website,
                                               url=url,
                                               competing_ccalg=competing_ccalg,
                                               btlbw=btlbw,
                                               rtt=rtt,
                                               queue_size=queue_size,
                                               duration=duration)
            elif test == 'video':
                proc = run_video_experiments(competing_ccalg,
                                             btlbw,
                                             rtt,
                                             queue_size,
                                             duration)
            elif test == 'video-website':
                proc = run_experiment_1video(website=website,
                                             url=url,
                                             competing_ccalg=competing_ccalg,
                                             btlbw=btlbw,
                                             rtt=rtt,
                                             queue_size=queue_size,
                                             duration=duration)
            elif test == 'iperf-rtt':
                proc = run_experiment_rtt(website,
                                          url,
                                          competing_ccalg,
                                          num_competing,
                                          btlbw,
                                          queue_size,
                                          rtt,
                                          duration)
            else:
                raise NotImplementedError
        
            # spaghetti code to skip websites that don't work for given rtt
            if proc == -1:
                too_small_rtt = max(too_small_rtt, rtt)
            elif proc is not None:
                completed_experiment_procs.append(proc)
        except Exception as e:
            logging.error('Error running experiment for website: {}'.format(website))
            logging.error(e)
            logging.error(traceback.print_exc())
            print('Error running experiment for website: {}'.format(website))
            print(e)
            print(traceback.print_exc())

    for proc in completed_experiment_procs:
        logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
        proc.wait()
        if proc.returncode != 0:
            logging.warning('Error cleaning up experiment PID={}'.format(proc.pid))
        
            
def parse_args():
    """Pbarse commandline arguments"""
    parser = argparse.ArgumentParser(
        description='Run ccctestbed experiment to measure interaction between flows')
    parser.add_argument('--test, -t', choices=[
        'apache','iperf','video','apache-website','iperf-website',
        'video-website', 'iperf-rtt'], action='append', dest='tests')
    parser.add_argument(
        '--website, -w', nargs=2, action='append', required='True', metavar=('WEBSITE', 'FILE_URL'), dest='websites',
        help='Url of file to download from website. File should be sufficently big to enable classification.')
    parser.add_argument(
        '--network, -n', nargs=3, action='append', metavar=('BTLBW','RTT', 'QUEUE_SIZE'), dest='ntwrk_conditions', default=None, type=int,
        help='Network conditions for download from website.')
    parser.add_argument(
        '--num_competing','-c', type=int, action='append', dest='nums_competing', required=True)
    parser.add_argument(
        '--competing_ccalg','-a', choices=['cubic','bbr','reno'], dest='competing_ccalgs', action='append', required=True)
    parser.add_argument(
        '--duration', '-d', type=int, default=60)
    parser.add_argument(
        '--chrome', '-s', action='store_true', help='Run website traffic with headless chrome')
    parser.add_argument(
        '--repeat', '-r', type=int, default=1)
    args = parser.parse_args()
    return args
            
if __name__ == '__main__':
    # configure logging
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logging_config.ini')
    fileConfig(log_file_path)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    args = parse_args()
    main(args.tests, args.websites, ntwrk_conditions=args.ntwrk_conditions, nums_competing=args.nums_competing, competing_ccalgs=args.competing_ccalgs, duration=args.duration, repeat=args.repeat, chrome=args.chrome)
