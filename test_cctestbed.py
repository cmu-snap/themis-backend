import cctestbed as mut # module under test

import pytest
import subprocess
import shlex
import os
import json
import time

from contextlib import ExitStack

SERVER_IFNAME='enp6s0f0'
CLIENT_IFNAME='enp6s0f1'

SERVER_PCI='06:00.0'
CLIENT_PCI='06:00.1'

SERVER_IP='192.0.0.2'
CLIENT_IP='192.0.0.3'

#TODO: test for nonexistent ifnames

@pytest.fixture(scope='session')
def environment():
    env = mut.Environment(client_ifname = 'enp6s0f1',
                          server_ifname = 'enp6s0f0',
                          client_ip_lan = '192.0.0.4',
                          server_ip_lan = '192.0.0.1',
                          client_ip_wan = '128.104.222.54',
                          server_ip_wan = '128.104.222.70',
                          server_pci = '06:00.0',
                          client_pci = '06:00.1')
    return env

@pytest.fixture()
def experiment(environment):
    experiments = mut.load_experiment('experiments.json')
    """
    with open('experiments.json') as f:
        config = json.load(f)

    experiments = []
    for experiment_name, experiment in config.items():
        flows = []
        for idx, flow in enumerate(experiment['flows']):
            flows.append(mut.Flow(ccalg=flow['ccalg'],
                              duration=int(flow['duration']),
                              rtt=int(flow['rtt']),
                              client_port=5555+idx,
                              server_port=5201+idx))
        
            experiments.append(mut.Experiment(name = experiment_name,
                                          btlbw = int(experiment['btlbw']),
                                          queue_size = int(experiment['queue_size']),
                                          queue_speed = int(experiment['queue_speed']),
                                          flows = flows,
                                          server_log = '/users/rware/server-{}.iperf'.format(experiment_name),
                                          client_log = '/users/rware/client-{}.iperf'.format(experiment_name),
                                          server_tcpdump_log= '/users/rware/server-tcpdump-{}.pcap'.format(experiment_name),
                                          bess_tcpdump_log= '/opt/15-712/cctestbed/bess-tcpdump-{}.pcap'.format(experiment_name),
                                              queue_log= '/opt/15-712/cctestbed/queue-{}.txt'.format(experiment_name),
                                              env=environment,
                                              tarfile='{}.tar.gz'.format(experiment_name)))
    """
    return experiments['cubic']
    
        
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

#def test_set_rtt():
#    mut.set_rtt('128.104.222.54',50)
#    mut.remove_rtt('128.104.222.54')

@pytest.mark.usefixtures('experiment')
class TestExperiment(object):   

    @pytest.fixture
    def bess(self, request, experiment):
        def bess_close():
            # finalizer code for shutting down bess
            cmd = '/opt/bess/bessctl/bessctl daemon stop'
            output = subprocess.run(shlex.split(cmd))
            assert(output.returncode == 0)
        # start bess daemon and bess config
        cmd = '/opt/bess/bessctl/bessctl daemon start'
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode == 0)
        cmd = ("/opt/bess/bessctl/bessctl run active-middlebox-pmd "
               "\"BESS_PCI_SERVER='{}', "
               "BESS_PCI_CLIENT='{}', "
               "BESS_QUEUE_SIZE='{}', "
               "BESS_QUEUE_SPEED='{}'\"").format(experiment.env.server_pci,
                                                 experiment.env.client_pci,
                                                 experiment.queue_size,
                                                 experiment.queue_speed)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==0)
        request.addfinalizer(bess_close)

    def test_start_iperf_server(self, experiment):
        cmd = 'ssh -p 22 rware@{} pgrep iperf3'.format(experiment.env.server_ip_wan)
        with experiment.start_iperf_server(experiment.flows[0], affinity=1):
            time.sleep(10)
            output = subprocess.run(shlex.split(cmd))
            assert(output.returncode==0)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==1)
        filename = os.path.basename(experiment.server_log)
        assert(os.path.isfile(filename))
        with open(filename) as f:
            print("SERVER FILE:")
            print(f.read())
        os.remove(filename)

    def test_start_tcpdump_server(self, experiment):
        cmd = 'ssh -p 22 rware@{} pgrep tcpdump'.format(experiment.env.server_ip_wan)
        with experiment.start_tcpdump_server():
            output = subprocess.run(shlex.split(cmd))
            assert(output.returncode==0)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==1)
        filename = os.path.basename(experiment.server_tcpdump_log)
        assert(os.path.isfile(filename))
        os.remove(filename)
        
    def test_start_monitor_bess(self, experiment):
        cmd = 'pgrep tail'    
        with experiment.start_monitor_bess() as cmd_output:
            print(cmd_output)
            output = subprocess.run(shlex.split(cmd))
            assert(output.returncode==0)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==1)
        assert(os.path.isfile(experiment.queue_log))
        os.remove(experiment.queue_log)

    # TODO: fix this. BESS needs to be running to run this
    def test_start_tcpdump_bess(self, experiment, bess):
        cmd = 'pgrep -f {}'.format(experiment.bess_tcpdump_log)
        with experiment.start_tcpdump_bess():
            output = subprocess.run(shlex.split(cmd))
            assert(output.returncode==0)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==1)
        assert(os.path.isfile(experiment.bess_tcpdump_log))
        os.remove(experiment.bess_tcpdump_log)
        os.remove('nohup.out')
        
    def test_start_iperf_client(self, experiment, bess):
        with experiment.start_iperf_client(experiment.flows[0], 1):
            cmd = 'ssh -p 22 rware@{} pgrep iperf3'
            output = subprocess.run(shlex.split(cmd.format(
                experiment.env.server_ip_wan)))
            assert(output.returncode==0)
            output = subprocess.run(shlex.split(cmd.format(
                experiment.env.client_ip_wan)))
            assert(output.returncode==0)
        time.sleep(5)
        output = subprocess.run(shlex.split(cmd.format(
            experiment.env.server_ip_wan)))
        assert(output.returncode==1)
        output = subprocess.run(shlex.split(cmd.format(
            experiment.env.client_ip_wan)))
        assert(output.returncode==1)
        filename = os.path.basename(client_log)
        assert(os.path.isfile(filename))
        os.remove(filename)
        filename = os.path.basename(server_log)
        assert(os.path.isfile(filename))
        os.remove(filename)

    def test_set_rtt(self, experiment, bess):
        target_rtt = experiment.flows[0].rtt
        with experiment.set_rtt(target_rtt):
            cmd_rtt = ("ssh -p 22 rware@{} "
                       "ping -c 4 -I {} {} "
                       "| tail -1 "
                       "| awk '{{print $4}}' "
                       "| cut -d '/' -f 2").format(experiment.env.server_ip_wan,
                                                   experiment.env.server_ip_lan,
                                                   experiment.env.client_ip_lan)
            cmd_rtt = cmd_rtt.split('|')
            avg_rtt = float(mut.pipe_syscalls(cmd_rtt, sudo=False))
            assert(avg_rtt >= target_rtt)
        avg_rtt = float(mut.pipe_syscalls(cmd_rtt, sudo=False))
        assert(avg_rtt < target_rtt)
            
    def test_run(self, experiment):
        experiment.run()
        assert(os.path.isfile(experiment.tarfile))
        os.remove(experiment.tarfile)
