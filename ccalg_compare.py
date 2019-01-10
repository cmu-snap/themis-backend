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

QUEUE_SIZE_TABLE = {
    35: {5:16, 10:32, 15:64},
    85: {5:64, 10:128, 15:128},
    130: {5:64, 10:128, 15:256},
    275: {5:128, 10:256, 15:512}}

def is_completed_experiment(experiment_name):
    num_completed = glob.glob('/tmp/{}-*.tar.gz'.format(experiment_name))
    experiment_done = len(num_completed) > 0
    if experiment_done:
        logging.warning(
            'Skipping completed experiment: {}'.format(experiment_name))
    return experiment_done

def ran_experiment_today(experiment_name):
    today = datetime.datetime.now().isoformat()[:10].replace('-','')
    num_completed = glob.glob('/tmp/{}-{}*.tar.gz'.format(experiment_name, today))
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

def run_experiment(website1, url1, website2, url2, btlbw=10, queue_size=128, rtt=35, force=False):
    experiment_name = '{}bw-{}rtt-{}q-{}-{}'.format(btlbw, rtt, queue_size, website1, website2)
    if not force and is_completed_experiment(experiment_name):
        return
    else:
        if ran_experiment_today(experiment_name):
            return
    logging.info('Creating experiment for website1: {} website2: {}'.format(website1, website2))
    url_ip1 = get_website_ip(url1)
    url_ip2 = get_website_ip(url2)
    logging.info('Got website1 IP: {} website2 IP: {}'.format(url_ip1, url_ip2))
    website_rtt1 = int(float(get_nping_rtt(url_ip1)))
    website_rtt2 = int(float(get_nping_rtt(url_ip2)))
    logging.info('Got website1 RTT: {} website2 RTT: {}'.format(website_rtt1, website_rtt2))

    if website_rtt1 >= rtt:
        logging.warning('Skipping experiment with website1 RTT {} >= {}'.format(
            website_rtt1, rtt))
        return -1
    elif website_rtt2 >= rtt:
        logging.warning('Skipping experiment with website2 RTT {} >= {}'.format(
            website_rtt2, rtt))
        return -1

    client = HOST_CLIENT_TEMPLATE
    # TODO: Which IP should be used for client?
    client['ip_wan'] = url_ip1
    client = cctestbed.Host(**client)
    server = HOST_SERVER
    
    server_nat_ip = HOST_CLIENT.ip_wan #'128.104.222.182'  taro
    server_port = 5201
    client_port = 5555

    flow1 = {'ccalg': 'reno',
            'end_time': 60,
            'rtt': rtt - website_rtt1,
            'start_time': 0}
    flow2 = {'ccalg': 'reno',
            'end_time': 60,
            'rtt': rtt - website_rtt2,
            'start_time': 0}
    flows = [
        cctestbed.Flow(ccalg=flow1['ccalg'], start_time=flow1['start_time'],
                        end_time=flow1['end_time'], rtt=flow1['rtt'],
                        server_port=server_port, client_port=client_port,
                        client_log=None, server_log=None),
        cctestbed.Flow(ccalg=flow2['ccalg'], start_time=flow2['start_time'],
                        end_time=flow2['end_time'], rtt=flow2['rtt'],
                        server_port=server_port, client_port=client_port,
                        client_log=None, server_log=None),
    ]
    
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
        stack.enter_context(add_dnat_rule(exp, url_ip1))
        stack.enter_context(add_dnat_rule(exp, url_ip2))
        # add route to URL
        stack.enter_context(add_route(exp, url_ip1))
        stack.enter_context(add_route(exp, url_ip2))
        # add dns entry
        stack.enter_context(add_dns_rule(exp, website1, url_ip1))
        stack.enter_context(add_dns_rule(exp, website2, url_ip2))
        exp._run_tcpdump('server', stack)
        # run the flow
        # turns out there is a bug when using subprocess and Popen in Python 3.5
        # so skip ping needs to be true
        # https://bugs.python.org/issue27122
        cctestbed.stop_bess()
        stack.enter_context(exp._run_bess(ping_source='server', skip_ping=False))
        # give bess some time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        stack.enter_context(exp._run_rtt_monitor())
        with cctestbed.get_ssh_client(exp.server.ip_wan,
                                      exp.server.username,
                                      key_filename=exp.server.key_filename) as ssh_client:
            filename1 = os.path.basename(url1)
            filename2 = os.path.basename(url2)
            if filename1.strip() == '':
                logging.warning('Could not get filename from URL 1')
            if filename2.strip() == '':
                logging.warning('Could not get filename from URL 2')
            # Start first flow in background and second in foreground
            start_flow_cmd1 = 'timeout 65s wget --no-cache --delete-after --connect-timeout=10 --tries=3 --bind-address {}  -P /tmp/ {} || rm -f /tmp/{}.tmp* &'.format(exp.server.ip_lan, url1, filename1)
            start_flow_cmd2 = 'timeout 65s wget --no-cache --delete-after --connect-timeout=10 --tries=3 --bind-address {}  -P /tmp/ {} || rm -f /tmp/{}.tmp*'.format(exp.server.ip_lan, url2, filename2)
            # won't return until flow is done
            flow_start_time = time.time()
            _, _, _ = cctestbed.exec_command(ssh_client, exp.server.ip_wan, start_flow_cmd1)
            _, stdout, _ = cctestbed.exec_command(ssh_client, exp.server.ip_wan, start_flow_cmd2)
            exit_status = stdout.channel.recv_exit_status()
            flow_end_time = time.time()
            logging.info('Flow ran for {} seconds'.format(flow_end_time - flow_start_time))
        exp._show_bess_pipeline()
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        print(cctestbed.run_local_command(cmd))
        if exit_status != 0:
            if exit_status == 124: # timeout exit status
                print('Timeout. Flow longer than 65s.')
                logging.warning('Timeout. Flow longer than 65s.')
            else:
                logging.error(stdout.read())
                raise RuntimeError('Error running flow.')
    proc = exp._compress_logs_url()
    return (proc, exp.tar_filename, experiment_name)

@contextmanager
def add_dnat_rule(exp, url_ip):
    with cctestbed.get_ssh_client(exp.server_nat_ip,
                                  exp.server.username,
                                  exp.server.key_filename) as ssh_client:
        # TODO: remove hard coding of the ip addr here
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
def add_route(exp, url_ip):
    with cctestbed.get_ssh_client(exp.server.ip_wan,
                                  exp.server.username,
                                  key_filename=exp.server.key_filename) as ssh_client:
        add_route_cmd = 'sudo route add {} gw {}'.format(url_ip, exp.client.ip_lan)
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

def get_taro_experiments():    
    experiments = {}
    for rtt in [35, 85, 130, 275]:
        for btlbw in [5, 10, 15]:
            queue_size = QUEUE_SIZE_TABLE[rtt][btlbw]
            config = generate_experiments.ccalg_predict_config_websites(
                btlbw=btlbw,
                rtt=rtt,
                end_time=60,
                exp_name_suffix='taro',
                queue_size=queue_size)
            config_filename = 'experiments-ccalg-predict-{}bw-{}rtt.yaml'.format(btlbw, rtt)
            logging.info('Writing config file {}'.format(config_filename))
            with open(config_filename, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            experiments.update(cctestbed.load_experiments(config,
                                                          config_filename, force=True))
    return experiments
    
def run_taro_experiments():
    experiments = get_taro_experiments()
    completed_experiment_procs = []
    logging.info('Going to run {} experiments.'.format(len(experiments)))

    running_experiment = 1
    
    for experiment in experiments.values():
        try:
            print('Running experiments {}/{}'.format(running_experiment, len(experiments)))
            cctestbed.run_local_command('/opt/bess/bessctl/bessctl daemon stop')
            proc = experiment.run()
            completed_experiment_procs.append(proc)
            running_experiment += 1
        except Exception as e:
            print('ERROR RUNNING EXPERIMENT: {}'.format(e))

    for proc in completed_experiment_procs:
        logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
        proc.wait()
        if proc.returncode != 0:
            logging.warning('Error running cmd PID={}'.format(proc.pid))

def main(websites, ntwrk_conditions=None, force=False):
    completed_experiment_procs = []
    logging.info('Found {} website pairs'.format(len(websites)))
    print('Found {} website pairs'.format(len(websites)))
    num_completed_pairs = 0
    if ntwrk_conditions is None:
        ntwrk_conditions = [(5,35), (5,85), (5,130), (5,275),
                            (10,35), (10,85), (10,130), (10,275),
                            (15,35), (15,85), (15,130), (15,275)]
        
    for website1, url1, website2, url2 in websites:
        try:
            num_completed_experiments = 1
            too_small_rtts = []
            for btlbw, rtt in ntwrk_conditions:
                queue_size = QUEUE_SIZE_TABLE[rtt][btlbw]                    
                print('Running experiment {}/12 website1={}, website2={}, btlbw={}, queue_size={}, rtt={}.'.format(
                    num_completed_experiments,website1,website2,btlbw,queue_size,rtt))
                num_completed_experiments += 1
                if rtt in too_small_rtts:
                    print('Skipping experiment RTT too small')
                    num_completed_experiments += 1
                    break
                (proc, tar_filename, exp_name) = run_experiment(website1, url1, website2, url2, btlbw, queue_size, rtt, force=force)
                print('Experiment tar_filename={} exp_name={}'.format(tar_filename, exp_name))
                # spaghetti code to skip websites that don't work for given rtt
                if proc == -1:
                    too_small_rtts.append(rtt)
                elif proc is not None:
                    completed_experiment_procs.append(proc)
        except Exception as e:
            logging.error('Error running experiment for website1: {} website2: {}'.format(website1, website2))
            logging.error(e)
            logging.error(traceback.print_exc())
            print('Error running experiment for website1: {} website2: {}'.format(website1, website2))
            print(e)
            print(traceback.print_exc())

        num_completed_pairs += 1
        print('Completed experiments for {}/{} website pairs'.format(num_completed_pairs, len(websites)))
    
    for proc in completed_experiment_procs:
        logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
        proc.wait()
        if proc.returncode != 0:
            logging.warning('Error running cmd PID={}'.format(proc.pid))
    
            
def parse_args():
    """Parse commandline arguments"""
    parser = argparse.ArgumentParser(
        description='Run ccctestbed experiment on two websites to classify which congestion control algorithm each website is using')
    parser.add_argument(
        '--website, -w', nargs=4, action='append', required='True', metavar=('WEBSITE1', 'FILE_URL1', 'WEBSITE2', 'FILE_URL2'), dest='websites',
        help='Urls of files to download from two websites. Files should be sufficently big to enable classification.')
    parser.add_argument(
        '--network, -n', nargs=2, action='append', metavar=('BTLBW','RTT'), dest='ntwrk_conditions', default=None, type=int,
        help='Network conditions for downloads from websites.')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Force experiments that were already run to run again')
    args = parser.parse_args()
    return args
            
if __name__ == '__main__':
    # configure logging
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logging_config.ini')
    fileConfig(log_file_path)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    args = parse_args()
    main(args.websites, ntwrk_conditions=args.ntwrk_conditions, force=args.force)
