import cctestbed as mut # module under test
import subprocess
import shlex
from click.testing import CliRunner
import unittest.mock as mock

SERVER_IFNAME='enp6s0f0'
CLIENT_IFNAME='enp6s0f1'

SERVER_PCI='06:00.0'
CLIENT_PCI='06:00.1'

SERVER_IP='192.0.0.2'
CLIENT_IP='192.0.0.3'

#TODO: test for nonexistent ifnames

def test_get_interface_pci():
    pci = mut.get_interface_pci(SERVER_IFNAME)
    assert(pci == SERVER_PCI)
    pci = mut.get_interface_pci(CLIENT_IFNAME)
    assert(pci == CLIENT_PCI)
    
def test_pipe_syscalls():
    cmds = ['/opt/bess/bin/dpdk-devbind.py --status', 'grep enp6s0f0']
    output = mut.pipe_syscalls(cmds)
    assert(output.split()[0] == '0000:06:00.0')

def test_get_interface_ip():
    ip, mask = mut.get_interface_ip(SERVER_IFNAME)
    assert(ip == SERVER_IP)
    assert(mask == '24')
    
def test_env_var():
    mut.store_env_var('TEST','test')
    with open('/etc/environment', 'r') as f:
        assert('TEST=test' in f.read())
    subprocess.run(shlex.split('sudo sed -i "/^TEST=test/ d" /etc/environment'))

def test_set_rtt():
    mut.set_rtt('128.104.222.54',50)
    mut.remove_rtt('128.104.222.54')

def test_run_experiment():
    #process_mock = mock.Mock()
    #attrs = {'communicate.return_value':('output','error')}
    #process_mock.configure_mock(**attrs)
    #mock_popen.return_value = process_mock
    #runner = CliRunner()
    #result = runner.invoke(mut.main, ['run_experiment', 'experiments.json'])
    #print(result.output)
    #assert result.exit_code == 0
    mut._run_experiment('experiments.json')
