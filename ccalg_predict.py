import cctestbedv2 as cctestbed
import cctestbed_generate_experiments as generate_experiments
from contextlib import ExitStack, contextmanager
from urllib.parse import urlsplit, urlunsplit

import logging
import time
import pandas as pd
import glob
import traceback
import os
import yaml

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

def compute_rtt_from_tcpdump(tcpdump_filename):
    logging.info('Computing RTT from tcpdump')
    rtts = run_local_command('tshark -r "{}" '
                             '-Tfields -e frame.time_relative '
                             '-e tcp.analysis.ack_rtt'.format(tcpdump_filename))
    for x,y in list(map(lambda x: x.split('\t'), rtts.split('\n'))):
        if y != '':
            rtt = float(y)
            return rtt
    

def generate_test_data(experiment_name, experiment=None):

    if experiment is None:
        completed_experiments = glob.glob('/tmp/{}-*.tar.gz'.format(experiment_name))
        if len(completed_experiments) > 1:
            logging.warning('Found more than 1 experiment with this name. Using first one')
        """"
        with cctestbed.untarfile_extract(
        if is_completed_experiment(experiment.name):
        tar_filename = experiment.tar_filename
        tcpdump_filename = os.path.basename(experiment.logs['server_tcpdump_log'])
        with cctestbed.untarfile_extract(tar_filename, tcpdump_filename, delete_file=True) as f:
            if experiment.rtt_measured is None:
                rtt = compute_rtt_from_tcpdump(experiment.logs['server_tcpdump_logs'])
            else:
                rtt = None
            data_bit_rate = run_local_command(
                'capinfos -i {}'.format(experiments.logs['server_tcpdump_logs']))
            data_bit_rate, data_bit_rate_unit = data_bit_rate.split('\n')[1].split(':')[-1].strip().split()
        exp_info = {}
        exp_info['rtt_measured'] = experiment.rtt_measured
        exp_info['website'] = experiment.name.split('-')[-1]
        exp_info['bit_rate'] = int(data_bit_rate)
        exp_info['bit_rate_unit'] = data_bit_rate_unit
        exp_info['queue_size'] = experiment.queue_size
        exp_info['btlbw'] = experiment.btlbw
        exp_info['rtt_tcpdump'] = int(rtt * 1000) if rtt is not None else None
        exp_info['name'] = experiment.name
        # append to url experiment data
        with open('/mnt/url_experiments.out', 'a') as f:
        f.write(json.dumps(exp_info))
        """
      
def _url_classify2(flow_analyzer, btlbw, queue_size, rtt):
    distances = {'name':flow_analyzer.experiment_name}
    taro_exps = load_experiments(['*-{}bw-{}rtt-{}q-taro*'.format(btlbw, rtt, queue_size)], load_queue=True)
    assert(len(taro_exps) == 3)
    testing_flows = {flow_analyzer.experiment_name : flow_analyzer}
    # this time, use only 1 seconds of flow
    X = flow_analyzer.features[:120]
    for exp_name, taro_exp in taro_exps.items():
        taro_flow_analyzer = FlowAnalyzer(taro_exp,
                                          labelsfunc=get_labels_dtw,
                                          featuresfunc=get_features_dtw,
                                          deltasfunc=get_deltas_dtw,
                                          resamplefunc=resample_dtw,
                                          resample_interval=500)
        # make sure the testing flows are shortened to match length of test flows
        Y = taro_flow_analyzer.features[:len(flow_analyzer.features)]
        distances[taro_flow_analyzer.flow.ccalg] = slowdtw(X, Y)
        return distances

def get_nping_rtt(url_ip):
    cmd = "nping -v-1 -H -c 5 {} | grep -oP 'Avg rtt:\s+\K.*(?=ms)'".format(url_ip)
    rtt = cctestbed.run_local_command(cmd, shell=True)
    return rtt

def run_rtt_monitor(url_ip):
    cmd = "nping --delay 5s {} > {}  &".format(url_ip, '')
    rtt = cctestbed.run_local_command(cmd, shell=True)
    return rtt


def run_experiment(website, url, btlbw=10, queue_size=128, rtt=35, force=False):
    experiment_name = '{}bw-{}rtt-{}q-{}'.format(btlbw, rtt, queue_size, website)
    if not force and is_completed_experiment(experiment_name):
        return
    logging.info('Creating experiment for website: {}'.format(website))
    url_ip = get_website_ip(url)
    logging.info('Got website IP: {}'.format(url_ip))
    website_rtt = int(float(get_nping_rtt(url_ip)))
    logging.info('Got website RTT: {}'.format(website_rtt))

    if website_rtt >= rtt:
        logging.warning('Skipping experiment with website RTT {} >= {}'.format(
            website_rtt, rtt))
        return -1
    
    client = cctestbed.Host(**{'ifname_remote': 'enp6s0f1',
                 'ifname_local': 'enp6s0f0',
                 'ip_lan': '192.0.0.4',
                 'ip_wan': url_ip, #'ip_wan': '128.2.208.128',
                 'pci': '06:00.0',
                 'key_filename': '/users/rware/.ssh/rware_turnip.pem', 
                 'username': 'rware'})

    server = cctestbed.Host(**{'ifname_remote': 'enp6s0f1',
                   'ifname_local': 'enp6s0f1',
                   'ip_lan': '192.0.0.2',
                   'ip_wan': '128.104.222.116',
                   'pci': '06:00.1',
                   'key_filename': '/users/rware/.ssh/rware_turnip.pem',
                   'username': 'rware'})
    
    server_nat_ip = '128.104.222.182' # taro
    server_port = 5201
    client_port = 5555

    #print('Connecting dpdk')
    #cctestbed.connect_dpdk(server, client)

    flow = {'ccalg': 'reno',
            'end_time': 60,
            'rtt': rtt - website_rtt,
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
    #exp._run_dig()
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
        stack.enter_context(exp._run_bess(ping_source='server', skip_ping=False))
        # give bess some time to start
        time.sleep(5)
        exp._show_bess_pipeline()
        stack.enter_context(exp._run_bess_monitor())
        exp._run_rtt_monitor(stack)
        with cctestbed.get_ssh_client(exp.server.ip_wan,
                                      exp.server.username,
                                      key_filename=exp.server.key_filename) as ssh_client:
            filename = os.path.basename(url)
            if filename.strip() == '':
                logging.warning('Could not get filename from URL')
            start_flow_cmd = 'timeout 65s wget --delete-after --connect-timeout=10 --tries=3 --bind-address {}  -P /tmp/ {} || rm -f /tmp/{}.tmp*'.format(exp.server.ip_lan, url, filename)
            # won't return until flow is done
            flow_start_time = time.time()
            _, stdout, _ = cctestbed.exec_command(ssh_client, exp.server.ip_wan, start_flow_cmd)
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
    return proc

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
    QUEUE_SIZE_TABLE = {
        35: {5:16, 10:32, 15:64},
        85: {5:64, 10:128, 15:128},
        130: {5:64, 10:128, 15:256},
        275: {5:128, 10:256, 15:512}}
    
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

def main():
    # get urls
    # url_filename = 'ccalg-predict-findfilesresults.txt'
    url_filename = 'ccalg-predict-urls-cleaned-20180920.csv'
    #'cdn_urls.txt' #'urls_all_results.txt'
    df = pd.read_csv(url_filename).set_index('website')
    #, header=None, names=['website', 'url', 'file_size']).set_index('website')
    urls = df.to_dict(orient='index')
    # only do apple
    #s = {'redcross.org':urls['redcross.org']}
    completed_experiment_procs = []
    #skip_websites = ['mlit.go.jp', 'arxiv.org'] # can't get arix.gov to work
    skip_websites = []
    logging.info('Found {} websites'.format(len(urls)))
    print('Found {} websites'.format(len(urls)))
    num_completed_websites = 0
    for website in urls.keys():
        if website not in skip_websites:
            file_size = urls[website]['filesize']
            url = urls[website]['url']
            try:
                # before this was 1,5,10,15 but too much
                # gonna just do 5 & 10
                num_completed_experiments = 1
                for rtt in [35, 85, 130, 275]:
                    for btlbw in [5, 10, 15]:
                        queue_size = QUEUE_SIZE_TABLE[rtt][btlbw]                    
                        print('Running experiment {}/12 website={}, btlbw={}, queue_size={}, rtt={}.'.format(num_completed_experiments,website,btlbw,queue_size,rtt))
                        num_completed_experiments += 1
                        proc = run_experiment(website, url, btlbw, queue_size, rtt, force=True)
                        # spaghetti code to skip websites that don't work for given rtt
                        if proc == -1:
                            break
                        elif proc is not None:
                            completed_experiment_procs.append(proc)
                    if proc == -1:
                        break
            except Exception as e:
                logging.error('Error running experiment for website: {}'.format(website))
                logging.error(e)
                logging.error(traceback.print_exc())
                print('Error running experiment for website: {}'.format(website))
                print(e)
                print(traceback.print_exc())
        num_completed_websites += 1
        print('Completed experiments for {}/{} websites'.format(num_completed_websites, len(urls)))
    
    for proc in completed_experiment_procs:
        logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
        proc.wait()
        if proc.returncode != 0:
            logging.warning('Error running cmd PID={}'.format(proc.pid))

if __name__ == '__main__':
    main()
    #run_taro_experiments()
