import click
import click_log
import subprocess
import shlex
from collections import namedtuple
import json
import time
from contextlib import contextmanager, ExitStack
import logging
import os
import pwd
from datetime import datetime

LOG = logging.getLogger(__name__)
ch = logging.StreamHandler()
ch.setFormatter('[%(asctime)s:%(levelname)s] %(message)s')
LOG.addHandler(ch)
click_log.basic_config(LOG)

# TODO: look into using Paramiko for ssh calls in python

#TODO: delete Experiment namedtuple class
#TODO: add logging and --debug cmdline option
#TODO: how to change RTT per flow using tc -- add delay per port instead of per interface

#TODO: need separate files for each flow's iperf output

#TODO: store files in a special tmp folder

# code for 2 pmdport

Environment = namedtuple('Environment', ['client_ifname', 'server_ifname', 'client_ip_wan', 'server_ip_wan', 'client_ip_lan', 'server_ip_lan', 'server_pci', 'client_pci'])
#Experiment = namedtuple('Experiment', ['name', 'btlbw', 'queue_size', 'queue_speed', 'flows', 'server_log', 'client_log', 'server_tcpdump_log', 'bess_tcpdump_log', 'queue_log'])
Flow = namedtuple('Flow', ['ccalg', 'duration', 'rtt', 'client_port', 'server_port', 'client_log', 'server_log'])

#note: currently's RTT's are set per machine so we can't have different RTT per flow

class Experiment(object):
    def __init__(self,
                 name,
                 btlbw,
                 queue_size,
                 flows,
                 env):
        self.name = name
        self.btlbw = btlbw
        self.queue_size = queue_size
        #self.flows = flows
        self.env = env
        
        self.exp_time = datetime.now().isoformat().replace(':','').replace('-','').split('.')[0]   
        self.server_tcpdump_log = '/tmp/server-tcpdump-{}-{}.pcap'.format(self.name,
                                                                        self.exp_time)
        self.bess_tcpdump_log = '/tmp/bess-tcpdump-{}-{}.pcap'.format(self.name,
                                                                     self.exp_time)
        self.queue_log = '/tmp/queue-{}-{}.txt'.format(self.name, self.exp_time)
        self.tarfile = '/tmp/{}-{}.tar.gz'.format(self.name, self.exp_time)
        self.client_tcpdump_log = '/tmp/client-tcpdump-{}-{}.pcap'.format(self.name,
                                                                        self.exp_time)
        self.description_log = '/tmp/{}-{}.json'.format(self.name, self.exp_time)
        
        # must make new flow objects since named tuples are immutable; a bit hacky
        self.flows = []
        for flow in flows:
            client_log = '/tmp/client-{}-{}-{}.iperf'.format(
                flow.client_port, self.name, self.exp_time)
            server_log = '/tmp/server-{}-{}-{}.iperf'.format(
                flow.server_port, self.name, self.exp_time)
            self.flows.append(Flow(ccalg=flow.ccalg,
                                   duration=flow.duration,
                                   rtt=flow.rtt,
                                   client_port=flow.client_port,
                                   server_port=flow.server_port,
                                   client_log=client_log,
                                   server_log=server_log))
    
        # files must be temporary files; use mktemp to make them
        
        
        # connect dpdk if not connected
        # assumes all experiments use the same environment which, they do
        # TODO: force above assumption to be true

        connect_dpdk(self.env.server_ifname, self.env.client_ifname)
        
    def __repr__(self):
        attrs = self.__str__()
        return 'Experiment({})'.format(attribs)

    def __str__(self):
        attribs = json.dumps(self.__dict__,
                             sort_keys=True,
                             indent=4,
                             separators=(',','='))
        return attribs
        
    def run(self):
        print('STARTING EXPERIMENT')
        print(self)
        max_duration = 0
        with ExitStack() as stack:
            # start bess -- give bess time to start
            print(stack.enter_context(self.start_bess()))
            time.sleep(5)
            # set rtt -- for now cannot set RTT per flow so just use first one
            #stack.enter_context(self.set_rtt(self.flows[0].rtt))
            self.check_rtt()
            # monitor the queue
            stack.enter_context(self.start_monitor_bess())
            # tcpdump server & client
            stack.enter_context(self.start_tcpdump_server())
            stack.enter_context(self.start_tcpdump_client())
            # start each flow
            for idx, flow in enumerate(self.flows):
                if flow.duration > max_duration:
                    max_duration = flow.duration
                stack.enter_context(self.start_iperf_client(flow, (idx % 32) + 1))
            # TODO: change this to check if iperf done
            # wait until flows finish
            print('SLEEPING FOR {}s'.format(max_duration + 25))
            time.sleep(max_duration + 25)
            # show pipeline
            cmd = '/opt/bess/bessctl/bessctl show pipeline'
            print(pipe_syscalls([cmd]))
            cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
            print(pipe_syscalls([cmd]))
            cmd = '/opt/bess/bessctl/bessctl command module queue_delay0 get_status EmptyArg'
            print(pipe_syscalls([cmd]))
        print('EXPERIMENT DONE')
        #cmd = 'tar -cvzf {}.tar.gz *{}*'.format(self.name, self.name)
        #pipe_syscalls([cmd])
        #cmd = 'rm -f *{}*'.format(self.name)
        #pipe_syscalls([cmd])
        with open(self.description_log, 'w') as f:
            json.dump(str(self), f)
        cmd = './cleanup-data.sh {} {} {}'.format(self.server_tcpdump_log,
                                                  self.tarfile,
                                                  os.path.basename(self.tarfile)[:-7])
        os.system(cmd)
        #os.remove(os.path.basename(self.bess_tcpdump_log))
        os.remove(self.queue_log)
        os.remove(self.server_tcpdump_log)
        os.remove(self.client_tcpdump_log)
        for flow in self.flows:
            os.remove(flow.client_log)
            os.remove(flow.server_log)
        os.remove('/tmp/{}.csv'.format(os.path.basename(self.tarfile)[:-7]))
        os.remove(self.description_log)
        
    @contextmanager
    def start_bess(self):
        cmd = '/opt/bess/bessctl/bessctl daemon start'
        pipe_syscalls([cmd])
        cmd = ("/opt/bess/bessctl/bessctl run active-middlebox-pmd "
               "\"BESS_PCI_SERVER='{}', "
               "BESS_PCI_CLIENT='{}', "
               "BESS_QUEUE_SIZE='{}', "
               "BESS_QUEUE_SPEED='{}', "
               "BESS_QUEUE_DELAY='{}'\"").format(self.env.server_pci,
                                                 self.env.client_pci,
                                                 self.queue_size,
                                                 self.btlbw,
                                                 self.flows[0].rtt)
        yield pipe_syscalls([cmd])
        cmd = '/opt/bess/bessctl/bessctl daemon stop'
        pipe_syscalls([cmd])

    @contextmanager
    def set_rtt(self, target_rtt):
        print('SETTING RTT TO {}'.format(target_rtt))
        # get current average RTT from ping
        cmd_rtt = ("ssh -p 22 rware@{} "
                   "ping -c 4 -I {} {} "
                   "| tail -1 "
                   "| awk '{{print $4}}' "
                   "| cut -d '/' -f 2").format(self.env.server_ip_wan,
                                               self.env.server_ip_lan,
                                               self.env.client_ip_lan)
        cmd_rtt = cmd_rtt.split('|')
        avg_rtt = float(pipe_syscalls(cmd_rtt, sudo=False))
        print('CURRENT AVG RTT = {}'.format(avg_rtt))
        if target_rtt < avg_rtt:
            raise ValueError('Existing RTT is {} so RTT cannot be set to {}'.format(
                avg_rtt, target_rtt))
        # set RTT to target RTT
        cmd = 'ssh -p 22 rware@{} sudo tc qdisc add dev enp6s0f0 root netem delay {}ms'.format(self.env.client_ip_wan, target_rtt-avg_rtt)
        pipe_syscalls([cmd], sudo=False)
        # check new average
        new_avg_rtt = float(pipe_syscalls(cmd_rtt))
        print('NEW AVG RTT = {}'.format(new_avg_rtt))
        yield new_avg_rtt
        # when done, remove RTT change
        click.echo('REMOVING RTT CHANGES')
        cmd = 'ssh -p 22 rware@{} sudo tc qdisc del dev enp6s0f0 root netem'.format(
            self.env.client_ip_wan)
        print(pipe_syscalls([cmd], sudo=False))

    def check_rtt(self):
        print('CHECKING RTT')
        # get current average RTT from ping
        cmd_rtt = ("ssh -p 22 rware@{} "
                   "ping -c 5 -I {} {} "
                   "| tail -1 "
                   "| awk '{{print $4}}' "
                   "| cut -d '/' -f 2").format(self.env.server_ip_wan,
                                               self.env.server_ip_lan,
                                               self.env.client_ip_lan)
        cmd_rtt = cmd_rtt.split('|')
        avg_rtt = float(pipe_syscalls(cmd_rtt, sudo=False))
        print('CURRENT AVG RTT = {}'.format(avg_rtt))        
        
    @contextmanager
    def start_iperf_server(self, flow, affinity):
        cmd = ('ssh -p 22 rware@{} '
               'nohup iperf3 --server '
               '--bind {} '
               '--port {} '
               '--one-off '
               '--affinity {} '
               '--logfile {} '
               ' > /dev/null 2> /dev/null < /dev/null &').format(
                   self.env.server_ip_wan,
                   self.env.server_ip_lan,
                   flow.server_port,
                   affinity,
                   flow.server_log)
        yield pipe_syscalls([cmd], sudo=False)
        self.cleanup_remote_cmd(ip=self.env.server_ip_wan,
                                cmd='iperf3',
                                filepath=flow.server_log)

    @contextmanager
    def start_iperf_client(self, flow, affinity):
        with self.start_iperf_server(flow, affinity):
            cmd = ('ssh -p 22 rware@{} '
                   'nohup iperf3 --client {} '
                   '--port {} '
                   '--verbose '
                   '--bind {} '
                   '--cport {} '
                   '--linux-congestion {} '
                   '--interval 0.5 '
                   '--time {} '
                   '--length 1024K '
                   '--affinity {} '
                   #'--set-mss 500 ' # default is 1448
                   '--window 100M '
                   '--zerocopy '
                   '--logfile {} '
                   '> /dev/null 2> /dev/null < /dev/null &').format(
                       self.env.client_ip_wan,
                       self.env.server_ip_lan,
                       flow.server_port,
                       self.env.client_ip_lan,
                       flow.client_port,
                       flow.ccalg,
                       flow.duration,
                       affinity,
                       flow.client_log)
            yield pipe_syscalls([cmd], sudo=False)
        self.cleanup_remote_cmd(ip=self.env.client_ip_wan,
                                cmd='iperf3',
                                filepath=flow.client_log)


    @contextmanager
    def start_tcpdump_client(self):
        cmd = ('ssh -p 22 rware@{} '
               'sudo tcpdump -n --packet-buffered '
               '--snapshot-length=65535 '
               '--interface=enp6s0f0 '
               '-w {} '
               '> /dev/null 2> /dev/null < /dev/null & ').format(
                   self.env.client_ip_wan,
                   self.client_tcpdump_log)
        yield pipe_syscalls([cmd], sudo=False)
        self.cleanup_remote_cmd(ip=self.env.client_ip_wan,
                                cmd='tcpdump',
                                filepath=self.client_tcpdump_log)
    
    @contextmanager
    def start_tcpdump_server(self):
        cmd = ('ssh -p 22 rware@{} '
               'sudo tcpdump -n --packet-buffered '
               '--snapshot-length=65535 '
               '--interface=enp6s0f0 '
               '-w {} '
               '> /dev/null 2> /dev/null < /dev/null & ').format(
                   self.env.server_ip_wan,
                   self.server_tcpdump_log)
        yield pipe_syscalls([cmd], sudo=False)
        self.cleanup_remote_cmd(ip=self.env.server_ip_wan,
                                cmd='tcpdump',
                                filepath=self.server_tcpdump_log)
        """
        cmd = ('tshark '
               '-T fields '
               '-E separator=, '
               '-E quote=d '
               '-r {} '
               '-e frame.time_relative '
               '-e tcp.len '
               '-e tcp.analysis.ack_rtt '
               '> {}.csv').format(self.bess_tcpdump_log, self.bess_tcpdump_log[:-5])
        print('RUNNING CMD: {}'.format(cmd))

        subprocess.run(shlex.split(cmd))
        """
        
    @contextmanager
    def start_monitor_bess(self):
        cmd = 'tail -n1 -f /tmp/bessd.INFO > {} &'.format(self.queue_log)
        # for some reason using subprocess here just hangs so use os.system instead
        print('RUNNING CMD: {}'.format(cmd))
        yield os.system(cmd)
        print('RUNNING CMD: pkill -9 tail')
        subprocess.run(['pkill','-9','tail'])
        #self.cleanup_local_cmd(cmd='tail')

    @contextmanager
    def start_tcpdump_bess(self):
        cmd = ('nohup /opt/bess/bessctl/bessctl tcpdump port_inc1 out 0 -n '
               '-s 65535 '
               '-w {} &> /dev/null &').format(self.bess_tcpdump_log)
        yield subprocess.run(shlex.split(cmd)) 
        self.cleanup_local_cmd(cmd=self.bess_tcpdump_log)
        
    def cleanup_remote_cmd(self, ip, cmd, filepath=None):
        """Kill remote commands and copy over files.

        Parameters:
        -----------
        ip : str
           IP addr of remote machines
        cmd : str
           cmd we want to kill
        filepath : str, default is None
           Path to file we want to copy to local machine. If None,
           will not copy any file.
        """
        try:
            run = 'ssh -p 22 rware@{} sudo pkill -9 {}'.format(ip,cmd)
            #pipe_syscalls([run], sudo=False)
            print('RUNNING CMD: {}'.format(run))
            close_proc = subprocess.run(shlex.split(run))
            if close_proc.returncode == 0:
                print('Process for cmd not found: {}'.format(cmd))
        finally:
            if filepath is not None:
                # copy remote file to local machine and delete on remote machine
                run = 'scp rware@{}:{} /tmp/'.format(ip, filepath)
                pipe_syscalls([run], sudo=False)
                run = 'ssh -p 22 rware@{} sudo rm -f {}'.format(ip, filepath)
                pipe_syscalls([run], sudo=False)

    def cleanup_local_cmd(self, cmd):
        run = 'sudo pkill -f {}'.format(cmd)
        pipe_syscalls([run], sudo=False)

    
@click.group()
def main():
    pass

# TODO: add option to only run specific experiment by name
@click.command()
@click.argument('config_file')
@click.option('--name', '-n', multiple=True)
@click_log.simple_verbosity_option(LOG)
def run_experiment(config_file, name):
    experiments = load_experiment(config_file)

    
    if len(name) == 0:
        # run all the experiments
        for experiment in experiments.values():
            # make sure bess daemon is shut down
            os.system('/opt/bess/bessctl/bessctl daemon stop')
            experiment.run()
    else:
        for n in name:
            experiments[n].run()

def load_experiment(config_file):    
    env = Environment(client_ifname = 'enp6s0f1',
                      server_ifname = 'enp6s0f0',
                      client_ip_lan = '192.0.0.4',
                      server_ip_lan = '192.0.0.1',
                      client_ip_wan = '128.104.222.54',
                      server_ip_wan = '128.104.222.70',
                      server_pci = '06:00.0',
                      client_pci = '06:00.1')

    with open(config_file) as f:
        config = json.load(f)

    experiments = {}
    
    for experiment_name, experiment in config.items():
        flows = []

        for idx, flow in enumerate(experiment['flows']):
            flows.append(Flow(ccalg=flow['ccalg'],
                              duration=int(flow['duration']),
                              rtt=int(flow['rtt']),
                              client_port=5555+idx,
                              server_port=5201+idx,
                              client_log=None,
                              server_log=None))
            experiments[experiment_name] = Experiment(
                name = experiment_name,
                btlbw = int(experiment['btlbw']),
                queue_size = int(experiment['queue_size']),
                flows = flows,
                env = env)

    return experiments

    
        
    
@click.command()
@click.argument('ifname_server')
@click.argument('ifname_client')
@click.argument('queue_size')
@click.argument('queue_speed')
def start_bess(ifname_server, ifname_client, queue_size, queue_speed):
    _start_bess(ifname_server, ifname_client, queue_size, queue_speed)
    
def _start_bess(ifname_server, ifname_client, queue_size, queue_speed):
    click.echo('STARTING BESS')
    server_pci, client_pci = connect_dpdk(ifname_server, ifname_client)
    subprocess.run(['/opt/bess/bessctl/bessctl', 'daemon start'])
    cmd = ("/opt/bess/bessctl/bessctl run active-middlebox-pmd "
           "\"BESS_IFNAME_SERVER='{}', "
           "BESS_IFNAME_CLIENT='{}', "
           "BESS_PCI_SERVER='{}', "
           "BESS_PCI_CLIENT='{}', "
           "BESS_QUEUE_SIZE='{}', "
           "BESS_QUEUE_SPEED='{}'\"").format(ifname_server,
                                             ifname_client,
                                             server_pci,
                                             client_pci,
                                             queue_size,
                                             queue_speed)
    click.echo(pipe_syscalls([cmd]))


    
@click.command()
def stop_bess():
    _stop_bess()

def _stop_bess():
    cmd = '/opt/bess/bessctl/bessctl daemon stop'
    pipe_syscalls([cmd])

    
main.add_command(start_bess)
main.add_command(stop_bess)
main.add_command(run_experiment)

def pipe_syscalls(cmds, sudo=True):
    """Run linux commands, piping input and output

    Parameters:
    -----------
    cmds : commands to call
    
    Reference: 
    piping shell commands - https://docs.python.org/2/library/subprocess.html#replacing-shell-pipeline
    """
    if not sudo:
        click.echo('CHANGING USER TO RWARE')
        uid = pwd.getpwnam('rware').pw_uid
        os.setuid(uid)
    click.echo('RUNNING CMD: {}'.format(' | '.join(cmds)))
    procs = []
    procs.append(subprocess.Popen(shlex.split(cmds[0]), stdout=subprocess.PIPE))
    for idx, cmd in enumerate(cmds[1:]):
        procs.append(subprocess.Popen(shlex.split(cmd), stdin=procs[idx].stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        #procs[idx-1].stdout.close()
    try:
        stdout, stderr = procs[-1].communicate(timeout=30)
    except subprocess.TimeoutExpired as e:
        # need to kill all the processes if a timeout occurs
        for proc in procs:
            proc.kill()
        click.echo('Process took longer than 5 seconds to finish: {}'.format(procs[-1].args))
        raise e
    if procs[-1].returncode != 0:
        raise RuntimeError('Encountered error running cmd: {}\n{}'.format(procs[-1].args, stderr))
    return stdout.decode('utf-8')


def get_interface_pci(ifname):
    """Return the PCI of the given interface
    
    Parameters:
    -----------
    ifname : str
       The interface name

    Raise: ValueError if there is no interface with given name
    """
    cmd = '/opt/bess/bin/dpdk-devbind.py --status | grep {}'.format(ifname)
    #cmds = ['/opt/bess/bin/dpdk-devbind.py --status', 'grep {}'.format(ifname)]
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
    pci = proc.stdout
    #pci = pipe_syscalls(cmd.split('|'))
    pci = pci.split()[0][-7:]
    if pci.strip() == '':
        raise ValueError('There is no interface with name {}.'.format(ifname))
    return pci.decode('utf-8')


def get_interface_ip(ifname):
    """Return the IP of the given interface.

    Parameters:
    -----------
    ifname : str
       Interface name

    Raise: ValueError there is no interface with given name
    """
    #cmd = ['ip addr', 'grep {}'.format(ifname), 'grep inet']
    #ip = pipe_syscalls(cmd)
    cmd = 'ip addr | grep {} | grep inet'.format(ifname)
    ip = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8')
    if ip is None or ip.strip() == '':
        raise ValueError('There is no interface with name {}.'.format(ifname))
    ip, mask = ip.split()[1].split('/')
    return ip, mask

def store_env_var(var, value):
    """Store an evironment variable in /etc/environment"""
    pipe_syscalls(['sudo sed -i "/^{}/ d" /etc/environment'.format(var)])
    with open('/etc/environment', 'a') as f:
        f.write('{}={}\n'.format(var, value))

# must run with sudo
def connect_dpdk(ifname_server, ifname_client):
    click.echo('CONNECTING DPDK')
    # TODO: if interfaces are not connected to kernel then throw an error

    # if already connected, just return
    #TODO: catch error when grep won't work b/c not connected
    #connected_pcis = pipe_syscalls(['/opt/bess/bin/dpdk-devbind.py --status',
    #                                'grep drv=uio_pci_generic'])
    # TODO: FIX THIS
    #cmd = '/opt/bess/bin/dpdk-devbind.py --status | grep drv=uio_pci_generic'
    #proc = subprocess.run(shlex.split(cmd), check=False)

    # super hacky
    cmd = '/opt/bess/bin/dpdk-devbind.py --status | grep drv=uio_pci_generic'
    proc = subprocess.run(cmd, check=False, shell=True, stdout=subprocess.PIPE)
    if proc.returncode == 0:
        #TODO: remove hardcoded number here
        print('Interfaces already conncted to DPDK')
        return '06:00.0', '06:00.1'
        
    server_pci = get_interface_pci(ifname_server)
    client_pci = get_interface_pci(ifname_client)

    if server_pci is None or server_pci.strip()=='':
        #TODO: remove hardcoded numbers here
        return '06:00.0', '06:00.1'
    
    server_ip, server_ip_mask = get_interface_ip(ifname_server)
    client_ip, client_ip_mask = get_interface_ip(ifname_client)
    
    # make sure hugepages is started
    cmd = 'sudo sysctl vm.nr_hugepages=1024'
    subprocess.run(shlex.split(cmd))

    # put environment variables in /etc/environment (deleting old stuff)
    store_env_var('BESS_SERVER_PCI', server_pci)
    store_env_var('BESS_CLIENT_PCI', client_pci)
    store_env_var('BESS_SERVER_IP', server_ip)
    store_env_var('BESS_CLIENT_IP', client_ip)
    store_env_var('BESS_SERVER_IP_MASK', '{}/{}'.format(server_ip, server_ip_mask))
    store_env_var('BESS_CLIENT_IP_MASK', '{}/{}'.format(client_ip, client_ip_mask))

    # connect NIC interfaces to DPDK
    cmd = 'sudo modprobe uio_pci_generic'
    subprocess.run(shlex.split(cmd))
    cmd = 'sudo ifconfig {} down'
    subprocess.run(shlex.split(cmd.format(ifname_server)))
    subprocess.run(shlex.split(cmd.format(ifname_client)))
    cmd = 'sudo /opt/bess/bin/dpdk-devbind.py -b uio_pci_generic {}'
    subprocess.run(shlex.split(cmd.format(server_pci)))
    subprocess.run(shlex.split(cmd.format(client_pci)))

    return server_pci, client_pci
           
           
def disconnect_dpdk():
    # TODO:
    pass
    

#def set_rtt(server_ip_lan, client_ip_lan, client_ip_wan, rtt):
def set_rtt(client_ip_wan, rtt):
    click.echo('SETTING RTT')
    # get average RTT from ping
    """
    cmd_rtt = "ping -c 4 -I {} {} | tail -1| awk '{{print $4}}' | cut -d '/' -f 2".format(server_ip_lan, client_ip_lan)
    cmd_rtt = cmd_rtt.split("|")
    avg_rtt = int(pipe_syscalls(cmd_rtt))
    click.echo('AVG RTT = {}'.format(avg_rtt))
    if rtt < avg_rtt:
        raise ValueError(
            "Existing RTT is {} which is less than target RTT {} so RTT cannot be set")
    """
    cmd = 'ssh -p 22 rware@{} sudo tc qdisc add dev enp6s0f0 root netem delay {}ms'.format(client_ip_wan, rtt-0.1)
    click.echo(pipe_syscalls([cmd], sudo=False))

    # output new average
    
    #new_avg_rtt = pipe_syscalls([cmd_rtt])
    #click.echo('NEW AVG RTT = {}'.format(new_avg_rtt))
    #return new_avg_rtt
    

def remove_rtt(machine_ip):
    click.echo('REMOVING RTT')
    cmd = 'ssh -p 22 rware@{} sudo tc qdisc del dev enp6s0f0 root netem'.format(
        machine_ip)
    click.echo(pipe_syscalls([cmd], sudo=False))
    
if __name__ == '__main__':
    main()
