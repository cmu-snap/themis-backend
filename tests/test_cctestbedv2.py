import cctestbedv2 as mut
from tests.conftest import is_remote_process_running, does_remote_file_exist, is_local_process_running, check_open_fileobjs
import psutil
import time
import os
from contextlib import ExitStack
import pytest
import subprocess

#from logging.config import fileConfig
#fileConfig('logging_config.ini')    
    
def test_connect_dpdk(experiment):
    expected_server_pci, expected_client_pci = mut.connect_dpdk(
        experiment.server, experiment.client)
    assert(expected_server_pci == experiment.server.pci)
    assert(expected_client_pci == experiment.client.pci)

def test_start_bess(experiment):
    mut.start_bess(experiment)

def test_experiment_run_bess(experiment):
    with experiment._run_bess():
        subprocess.run(['pgrep', 'bessd'], check=True)
        proc = subprocess.run(['/opt/bess/bessctl/bessctl', 'show', 'pipeline'],
                                stdout=subprocess.PIPE)
        print(proc.stdout.decode('utf-8'))
    time.sleep(3)
    proc = subprocess.run(['pgrep', 'bessd'])
    assert(proc.returncode != 0)
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)
    
def test_experiment_run_bess_monitor(experiment):
    with experiment._run_bess_monitor() as pid:
        assert(is_local_process_running(pid))
    assert(not is_local_process_running(pid))
    assert(os.path.isfile(experiment.logs['queue_log']))
    # check that there's something in the file
    with open(experiment.logs['queue_log']) as f:
        assert(f.read().strip() == ('enqueued, time, src, seq, datalen, '
                                    'size, dropped, queued, batch'))
    os.remove(experiment.logs['queue_log'])
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)

def test_experiment_run_all_flows(experiment):
    with ExitStack() as stack:
        experiment._run_all_flows(stack)
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
    # cleanup bess monitoring file
    assert(os.path.isfile(experiment.logs['queue_log']))
    with open(experiment.logs['queue_log']) as f:
        f.readline()
        second_line = f.readline().split(',')
    assert(len(second_line) == 9)
    # MAYBE: could check here if all the lines have the same number of columns
    os.remove(experiment.logs['queue_log'])
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)
    
def test_experiment_run_tcpprobe(experiment):
    with ExitStack() as stack:
        pid = experiment._run_tcpprobe(stack)
        # check if kernel module loaded
        module_loaded_cmd = 'cat /proc/modules | grep tcp_probe_ray'
        ssh_client = mut.get_ssh_client(experiment.client.ip_wan)
        _, stdout, _ = ssh_client.exec_command(module_loaded_cmd)
        assert(stdout.channel.recv_exit_status() == 0)
        ssh_client.close()
        assert(is_remote_process_running(experiment.client.ip_wan, pid))
    assert(not is_remote_process_running(experiment.client.ip_wan, pid))
    # check if kernel module unloaded
    module_loaded_cmd = 'cat /proc/modules | grep tcp_probe_ray'
    ssh_client = mut.get_ssh_client(experiment.client.ip_wan)
    _, stdout, _ = ssh_client.exec_command(module_loaded_cmd)
    assert(stdout.channel.recv_exit_status() == 1)
    ssh_client.close()
    assert(os.path.isfile(experiment.logs['tcpprobe_log']))
    os.remove(experiment.logs['tcpprobe_log'])
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)

def test_experiment_run_tcpdump_server(experiment):
    with ExitStack() as stack:
        pid = experiment._run_tcpdump('server', stack)
        assert(is_remote_process_running(experiment.server.ip_wan, pid))
    assert(not is_remote_process_running(experiment.server.ip_wan, pid))
    assert(os.path.isfile(experiment.logs['server_tcpdump_log']))
    assert(not does_remote_file_exist(experiment.server.ip_wan,
                                      experiment.logs['server_tcpdump_log']))
    os.remove(experiment.logs['server_tcpdump_log'])
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)
    
def test_experiment_run_tcpdump_client(experiment):
    with ExitStack() as stack:
        pid = experiment._run_tcpdump('client', stack)
        assert(is_remote_process_running(experiment.client.ip_wan, pid))
    assert(not is_remote_process_running(experiment.client.ip_wan, pid))
    assert(os.path.isfile(experiment.logs['client_tcpdump_log']))
    assert(not does_remote_file_exist(experiment.client.ip_wan,
                                      experiment.logs['client_tcpdump_log']))
    os.remove(experiment.logs['client_tcpdump_log'])
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)

@pytest.mark.timeout(60)    
def test_experiment_run(experiment):
    proc=experiment.run()
    proc.wait(timeout=5)
    # TODO: check log compression
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)
    
def test_experiment_compress_logs(experiment):
    with ExitStack() as stack:
        experiment._run_all_flows(stack)
    proc = experiment._compress_logs()
    assert(is_local_process_running(proc.pid))
    proc.wait(timeout=5)
    # check that tarfile contains files with data in them
    assert(os.path.isfile(experiment.tar_filename))
    expected_zipped_files = [experiment.logs['queue_log'],
                             experiment.logs['description_log'],
                             experiment.config_filename]
    for flow in experiment.flows:
        expected_zipped_files.append(flow.server_log)
        expected_zipped_files.append(flow.client_log)
    for expected_file in expected_zipped_files:
        assert(not os.path.exists(expected_file))
    # unzip and check if files have data in them
    with tarfile.open(experiment.tar_filename) as tar:
        tar.extractall(path='/tmp/')
    for expected_file in expected_zipped_files:
        assert(os.path.isfile(expected_file))
        assert(os.stat(expected_file).st_size > 0)
        os.remove(expected_file)
    os.remove(experiment.tar_filename)
    open_files, open_connections = check_open_fileobjs()
    assert(len(open_files) == 0)
    assert(len(open_connections) == 0)
