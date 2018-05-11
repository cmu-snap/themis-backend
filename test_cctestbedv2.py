import cctestbedv2 as mut
from contextlib import ExitStack
import pytest
import time
import paramiko
import os
import subprocess
import json

#TODO: add cleanup code for experiment description log files in /tmp/

@pytest.fixture(name='config')
def test_load_config_file():
    config_filename = 'experiments-cubic.yaml'
    config = mut.load_config_file(config_filename)
    assert(config is not None)
    assert('client' in config)
    assert('server' in config)
    assert('experiments' in config)
    return config

@pytest.fixture(name='experiment')
def test_load_experiments(config, request):
    experiments = mut.load_experiments(config)
    assert(len(experiments)==2)
    assert(experiments['cubic-8q'].queue_size==8)
    assert(experiments['cubic-16q'].queue_size==16)
    assert(len(experiments['cubic-8q'].flows)==1)
    assert(len(experiments['cubic-16q'].flows)==1)
    def remove_experiment_description_log():
        for experiment in experiments.values():
            os.remove(experiment.logs['description_log'])
    request.addfinalizer(remove_experiment_description_log)
    return experiments['cubic-8q']

def is_remote_process_running(remote_ip, pid):
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(remote_ip, username='ranysha')
    _, stdout, stderr = ssh_client.exec_command('ps --no-headers -p {} -o pid='.format(pid))
    returned_pid = stdout.readline()
    if returned_pid.strip() == '':
        return False
    else:
        assert(int(returned_pid) == pid)
        return True

def test_remote_command(experiment):
    start_server_cmd = ('iperf3 --server '
                        '--bind {} '
                        '--port {} '
                        '--one-off '
                        '--affinity {} '
                        '--logfile {} ').format(
                            experiment.server.ip_lan,
                            experiment.flows[0].server_port,
                            1,
                            experiment.flows[0].server_log)
    start_server = mut.RemoteCommand(start_server_cmd,
                                     experiment.server.ip_wan,
                                     logs=[experiment.flows[0].server_log])
    with start_server() as pid:
        assert(is_remote_process_running(experiment.server.ip_wan, pid))
        time.sleep(5)
    assert(not is_remote_process_running(experiment.server.ip_wan, pid))
    assert(os.path.isfile(experiment.flows[0].server_log))
    os.remove(experiment.flows[0].server_log)

def test_connect_dpdk(experiment):
    expected_server_pci, expected_client_pci = mut.connect_dpdk(
        experiment.server, experiment.client)
    assert(expected_server_pci == experiment.server.pci)
    assert(expected_client_pci == experiment.client.pci)
    
def test_experiment_run_all_flows(experiment):
    experiment._run_all_flows()
    for flow in experiment.flows:
        # check that bw looks reasonable (not less than 2mb from btlbw)
        # and delete created files
        with open(flow.client_log) as f:
            client_log = json.load(f)
        mbits_per_second = client_log['end']['sum_sent']['bits_per_second'] / 10e5
        print('Mbps={}'.format(mbits_per_second))
        assert(experiment.btlbw - mbits_per_second < 2) 
        assert(os.path.isfile(flow.server_log))
        os.remove(flow.server_log)
        assert(os.path.isfile(flow.client_log))
        os.remove(flow.client_log)

def test_experiment_run_bess(experiment):
    with experiment._run_bess():
        subprocess.run(['pgrep', 'bessd'], check=True)
        subprocess.run(['/opt/bess/bessctl/bessctl', 'show', 'pipeline'],
                       stdout=subprocess.PIPE)
        # test that you can ping between machines
        cmd = ('ping -c 4 -I {} {} '
               '| tail -1 '
               '| awk "{{print $4}}" ').format(experiment.server.ip_lan,
                                           experiment.client.ip_lan)
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(experiment.server.ip_wan, username='ranysha')
        _, stdout, _ = ssh_client.exec_command(cmd)
        # parse out avg rtt from last line of ping output
        avg_rtt = float(stdout.readline().split('=')[-1].split('/')[1])
        ssh_client.close()        
        assert(avg_rtt > experiment.flows[0].rtt)
    time.sleep(3)
    proc = subprocess.run(['pgrep', 'bessd'])
    assert(proc.returncode != 0)
        
