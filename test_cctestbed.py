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
                          client_ip_wan = '128.104.222.40',
                          server_ip_wan = '128.104.222.35',
                          server_pci = '06:00.0',
                          client_pci = '06:00.1')
    return env

@pytest.fixture(params=['experiments.json', 'experiments-20180122.json'], ids=['oneflow', 'twoflow'])
def experiment(environment, request):
    def experiment_close():
        os.system('rm /tmp/*.json') # will remove all experiment description files
    experiments = mut.load_experiment(request.param)
    request.addfinalizer(experiment_close)
    return experiments.popitem()[1]    
        
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
        """
        cmd = ("/opt/bess/bessctl/bessctl run active-middlebox-pmd "
               "\"BESS_PCI_SERVER='{}', "
               "BESS_PCI_CLIENT='{}', "
               "BESS_QUEUE_SIZE='{}', "
               "BESS_QUEUE_SPEED='{}',"
               "BESS_QUEUE_DELAY='{}'\"").format(experiment.env.server_pci,
                                                 experiment.env.client_pci,
                                                 experiment.queue_size,
                                                 experiment.btlbw,
                                                 experiment.flows[0].rtt)
        """
        cmd = ("/opt/bess/bessctl/bessctl run active-middlebox-pmd "
               "\"CCTESTBED_EXPERIMENT_DESCRIPTION='{}'\"").format(experiment.description_log)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==0)
        request.addfinalizer(bess_close)

    def test_start_bess(self, bess):
        os.system('/opt/bess/bessctl/bessctl show pipeline')
        
    def test_start_iperf_server(self, experiment):
        cmd = 'ssh -p 22 rware@{} pgrep iperf3'.format(experiment.env.server_ip_wan)
        with ExitStack() as stack:
            for idx, flow in enumerate(experiment.flows):
                stack.enter_context(experiment.start_iperf_server(flow,
                                                                  (idx % 32) + 1))
            time.sleep(5) # make sure server have time to start
            output = subprocess.run(shlex.split(cmd),
                                    stdout=subprocess.PIPE)
            assert(output.returncode==0)
            assert(len(output.stdout.strip().split(b'\n'))==len(experiment.flows))
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==1)
        for flow in experiment.flows:
            filename = flow.server_log
            assert(os.path.isfile(filename))
            os.remove(filename)
        
    def test_start_iperf_client(self, experiment, bess):
        cmd = 'ssh -p 22 rware@{} pgrep iperf3'
        with ExitStack() as stack:
            for idx, flow in enumerate(experiment.flows):
                stack.enter_context(experiment.start_iperf_client(flow,
                                                                  (idx % 32) + 1))
        
            time.sleep(5) # make sure things have time to start
            output = subprocess.run(shlex.split(cmd.format(
                experiment.env.server_ip_wan)), stdout=subprocess.PIPE)
            assert(output.returncode==0)
            assert(len(output.stdout.strip().split(b'\n'))==len(experiment.flows))
            output = subprocess.run(shlex.split(cmd.format(
                experiment.env.client_ip_wan)), stdout=subprocess.PIPE)
            assert(output.returncode==0)
            assert(len(output.stdout.strip().split(b'\n'))==len(experiment.flows))
        time.sleep(5) # make sure things have time to shutdown
        output = subprocess.run(shlex.split(cmd.format(
            experiment.env.server_ip_wan)))
        assert(output.returncode==1)
        output = subprocess.run(shlex.split(cmd.format(
            experiment.env.client_ip_wan)))
        assert(output.returncode==1)
        for flow in experiment.flows:
            filename = flow.client_log
            assert(os.path.isfile(filename))
            os.remove(filename)
            filename = flow.server_log
            assert(os.path.isfile(filename))
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

    def test_start_tcpdump_client(self, experiment):
        cmd = 'ssh -p 22 rware@{} pgrep tcpdump'.format(experiment.env.client_ip_wan)
        with experiment.start_tcpdump_client():
            output = subprocess.run(shlex.split(cmd))
            assert(output.returncode==0)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==1)
        filename = os.path.basename(experiment.client_tcpdump_log)
        assert(os.path.isfile(filename))
        os.remove(filename)

    def test_queue_module(self, experiment, bess):
        with ExitStack() as stack: # look at queue module
            stack.enter_context(experiment.start_monitor_bess())
            for idx, flow in enumerate(experiment.flows):
                stack.enter_context(experiment.start_iperf_client(flow,
                                                                  (idx % 32) + 1))
            time.sleep(40) # let experiment run for some short time
        time.sleep(5)
        assert(os.path.isfile(experiment.queue_log))
        os.system('tail {}'.format(experiment.queue_log))
        os.remove(experiment.queue_log)
        for flow in experiment.flows:
            filename = flow.client_log
            assert(os.path.isfile(filename))
            os.system('tail {}'.format(filename))
            os.remove(filename)
            filename = flow.server_log
            assert(os.path.isfile(filename))
            os.system('tail {}'.format(filename))
            os.remove(filename)


    def test_connect_dpdk(self, experiment):
        server_pci, client_pci = mut.connect_dpdk(experiment.env.server_ifname,
                                              experiment.env.client_ifname)
        assert(server_pci == '06:00.0')
        assert(client_pci == '06:00.1')

    def test_print_description(self, experiment):
        with open(experiment.description_log, 'w') as f:
            json.dump(str(experiment), f, sort_keys=True, indent=4, separators=(',','='))
        assert(os.path.isfile(experiment.description_log))
        with open(experiment.description_log, 'r') as f:
            data = json.load(f)
        print(data)
        os.remove(experiment.description_log)

    def test_start_tcpprobe(self, experiment):
        cmd = 'ssh -p 22 rware@{} "grep tcp_probe /proc/modules"'.format(
            experiment.env.client_ip_wan)
        with experiment.start_tcpprobe():
            output = subprocess.run(shlex.split(cmd))
            assert(output.returncode==0)
        output = subprocess.run(shlex.split(cmd))
        assert(output.returncode==1)
        filename = experiment.tcpprobe_log
        assert(os.path.isfile(filename))
        os.remove(filename)
