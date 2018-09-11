import cctestbedv2 as cctestbed
from contextlib import ExitStack, contextmanager
from urllib.parse import urlsplit, urlunsplit

import logging
import time
import pandas as pd
import glob

def is_completed_experiment(experiment_name):
    num_completed = glob.glob('/tmp/{}-*.tar.gz'.format(experiment_name))
    experiment_done = len(num_completed) > 0
    if experiment_done:
        logging.warning(
            'Skipping completed experiment: {}'.format(experiment_name))
    return experiment_done

def run_experiment(website, url, btlbw=10, queue_size=128, force=False):
    experiment_name = '{}bw-{}q-{}'.format(btlbw, queue_size, website)
    if not force and is_completed_experiment(experiment_name):
        return
    logging.info('Creating experiment for website: {}'.format(website))
    url_ip = get_website_ip(url)
    logging.info('Got website IP: {}'.format(url_ip))
        
    client = cctestbed.Host(**{'ifname_remote': 'ens13',
                 'ifname_local': 'ens3f0',
                 'ip_lan': '192.0.0.1',
                 'ip_wan': url_ip, #'ip_wan': '128.2.208.128',
                 'pci': '05:00.0',
                 'key_filename': '/home/ranysha/.ssh/id_rsa',
                 'username': 'ranysha'})

    server = cctestbed.Host(**{'ifname_remote': 'ens13',
                   'ifname_local': 'ens13',
                   'ip_lan': '192.0.0.4',
                   'ip_wan': '128.2.208.104',
                   'pci': '8b:00.0',
                   'key_filename': '/home/ranysha/.ssh/id_rsa',
                   'username': 'ranysha'})

    server_nat_ip = '128.2.208.128' # taro
    server_port = 5201
    client_port = 5555

    flow = {'ccalg': 'reno',
            'end_time': 60,
            'rtt': 1,
            'start_time': 0}
    flows = [cctestbed.Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                      end_time=flow['end_time'], rtt=flow['rtt'],
                      server_port=server_port, client_port=client_port,
                      client_log=None, server_log=None)]
    
    exp = cctestbed.Experiment(name=experiment_name,
                     btlbw=btlbw,
                     queue_size=queue_size,
                     flows=flows, server=server, client=client,
                     config_filename='experiments-all-ccalgs-aws.yaml',
                     server_nat_ip=server_nat_ip)
    
    logging.info('Running experiment: {}'.format(exp.name))
    exp._run_dig()
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
        stack.enter_context(exp._run_bess(ping_source='server', skip_ping=True))
        # give bess some time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        with cctestbed.get_ssh_client(exp.server.ip_wan,
                                      exp.server.username,
                                      key_filename=exp.server.key_filename) as ssh_client:
            start_flow_cmd = 'timeout 65s wget --connect-timeout=30 --tries=3 --bind-address 192.0.0.4 -P /tmp/ {}'.format(url)
            # won't return until flow is done
            flow_start_time = time.time()
            _, stdout, _ = cctestbed.exec_command(ssh_client, exp.server.ip_wan, start_flow_cmd)
            exit_status = stdout.channel.recv_exit_status()
            flow_end_time = time.time()
            logging.info('Flow ran for {} seconds'.format(flow_end_time - flow_start_time))
        exp._show_bess_pipeline()
        if exit_status != 0:
            if exit_status == 124: # timeout exit status
                logging.warning('Timeout. Flow longer than 65s.')
            else:
                logging.error(stdout.read())
                raise RuntimeError('Error running flow.')
    proc = exp._compress_logs()
    return proc
        
@contextmanager
def add_dnat_rule(exp, url_ip):
    with cctestbed.get_ssh_client(exp.server_nat_ip,
                                  exp.server.username,
                                  exp.server.key_filename) as ssh_client:
        # TODO: remove hard coding of the ip addr here
        dnat_rule_cmd = 'sudo iptables -t nat -A PREROUTING -i enp11s0f0 --source {} -j DNAT --to-destination {}'.format(url_ip, exp.server.ip_lan)
        cctestbed.exec_command(ssh_client, exp.server_nat_ip, dnat_rule_cmd)
    try:
        yield
    finally:
        # remove DNAT rule once down with this context
        with cctestbed.get_ssh_client(exp.server_nat_ip,
                                      exp.server.username,
                                      exp.server.key_filename) as ssh_client:
            # TODO: remove hard coding of the ip addr here
            dnat_delete_cmd = 'sudo iptables -t nat --delete PREROUTING 4'
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

def main():
    # get urls
    # url_filename = 'ccalg-predict-findfilesresults.txt'
    url_filename = 'urls_all_results.txt'
    df = pd.read_csv(url_filename, header=None,
                     names=['website', 'url', 'file_size']).set_index('website')
    urls = df.to_dict(orient='index')
    # only do apple
    #s = {'redcross.org':urls['redcross.org']}
    completed_experiment_procs = []
    #skip_websites = ['mlit.go.jp', 'arxiv.org'] # can't get arix.gov to work
    skip_websites = []
    logging.info('Found {} websites'.format(len(urls)))
    print('Found {} websites'.format(len(urls)))
    num_completed_websites = 0
    for website in urls:
        if website not in skip_websites:
            file_size = urls[website]['file_size']
            url = urls[website]['url']
            try:
                # before this was 1,5,10,15 but too much
                # gonna just do 5 & 10
                num_completed_experiments = 0
                for queue_size in [64, 128, 256]:
                    for btlbw in [5, 10, 15]:
                        print('Running experiment {}/9 website={}, btlbw={}, queue_size={}.'.format(num_completed_experiments,
                                                                                                     website,
                                                                                                     btlbw,
                                                                                                     queue_size))
                        num_completed_experiments += 1
                        proc = run_experiment(website, url, btlbw, queue_size, force=False)
                        if proc is not None:
                            completed_experiment_procs.append(proc)
            except Exception as e:
                logging.error('Error running experiment for website: {}'.format(website))
                logging.error(e)
                print('Error running experiment for website: {}'.format(website))
                print(e)
        num_completed_websites += 1
        print('Completed experiments for {}/{} websites'.format(len(urls)
        
    for proc in completed_experiment_procs:
        logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
        proc.wait()
        if proc.returncode != 0:
            logging.warning('Error running cmd PID={}'.format(proc.pid))

if __name__ == '__main__':
    main()
    
