import cctestbedv2 as cctestbed
import paramiko
import pytest
import subprocess
import os
import psutil

def pytest_addoption(parser):
    parser.addoption("--config", action="store",
                     default="/opt/cctestbed/tests/experiments-test.yaml",
                     help="full path to config file")
    
@pytest.fixture
def config_filename(request):
    return request.config.getoption("--config")

@pytest.fixture(name='config')
def test_load_config_file(config_filename):
    #config_filename = '/opt/cctestbed/tests/experiments-test.yaml'
    config = cctestbed.load_config_file(config_filename)
    assert(config is not None)
    assert('client' in config)
    assert('server' in config)
    assert('experiments' in config)
    return config, config_filename

@pytest.fixture(name='experiment', params=['cubic','cubic-bbr'])
def test_load_experiments(config, request):
    experiments = cctestbed.load_experiments(config[0], config[1], force=True)
    def remove_experiment_description_log():
        for experiment in experiments.values():
            # later tests could delete description log (see: compress_logs text)
            if os.path.exists(experiment.logs['description_log']):
                os.remove(experiment.logs['description_log'])
    request.addfinalizer(remove_experiment_description_log)
    """
    assert(len(experiments)==5)
    assert(experiments['cubic'].queue_size==8)
    assert(experiments['cubic-cubic'].queue_size==1024)
    assert(len(experiments['cubic'].flows)==1)
    assert(len(experiments['cubic-cubic'].flows)==2)
    """
    return experiments[request.param]
    
def is_remote_process_running(remote_ip, pid, username='ranysha'):
    ssh_client = paramiko.SSHClient()
    try:
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(remote_ip, username=username)
        _, stdout, stderr = ssh_client.exec_command('ps --no-headers -p {} -o pid='.format(pid))
        returned_pid = stdout.readline()
        if returned_pid.strip() == '':
            return False
        else:
            assert(int(returned_pid) == pid)
        return True
    finally:
        ssh_client.close()
    
    
def does_remote_file_exist(remote_ip, filename, username='ranysha'):
    ssh_client = paramiko.SSHClient()
    try:
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(remote_ip, username=username)
        sftp_client = ssh_client.open_sftp()
        try:
            sftp_client.stat(filename)
            return True
        except FileNotFoundError:
            return False
    finally:
        ssh_client.close()
        
def is_local_process_running(pid):
    cmd = ['ps', '--no-headers', '-p', str(pid), '-o', 'pid=']
    proc = subprocess.run(cmd, stdout=subprocess.PIPE)
    returned_pid = proc.stdout.decode('utf-8')
    if returned_pid.strip() == '':
        return False
    else:
        assert(int(returned_pid) == pid)
        return True

def check_open_fileobjs():
    this_proc = psutil.Process()
    return this_proc.open_files(), this_proc.connections()
