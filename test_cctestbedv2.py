import cctestbedv2 as mut
import pytest
import time
import paramiko
import os

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
def test_load_experiments(config):
    experiments = mut.load_experiments(config)
    assert(len(experiments)==2)
    assert(experiments['cubic-8q'].queue_size==8)
    assert(experiments['cubic-16q'].queue_size==16)
    assert(len(experiments['cubic-8q'].flows)==1)
    assert(len(experiments['cubic-16q'].flows)==1)
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


