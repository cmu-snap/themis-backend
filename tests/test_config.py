import config as mut
import subprocess
import shlex
import pytest
import os

@pytest.mark.parametrize("host", ['cctestbed-server','cctestbed-client'])
def test_get_host_ip_wan(host):
    ip_wan = mut.get_host_ip_wan(host)
    cmd = "ssh {} ifconfig enp1s0f0 | grep 'inet addr:' | cut -d: -f2 | cut -d' ' -f1".format(host)
    expected_ip = subprocess.check_output(cmd, shell=True).strip().decode('utf-8')
    assert(expected_ip == ip_wan)

@pytest.mark.parametrize("host", ['cctestbed-server','cctestbed-client'])
def test_get_host_key_filename(host):
    key_filename = mut.get_host_key_filename(host)
    expected_key_path = '/users/{}/.ssh/'.format(os.environ.get('USER'))
    assert(key_filename.startswith(expected_key_path))

@pytest.mark.parametrize("host", ['cctestbed-server','cctestbed-client'])
def test_get_host_username(host):
    user = mut.get_host_username(host)
    expected_user = os.environ.get('USER')
    assert(user == expected_user)
    
