import click
import subprocess
import shlex
from collections import namedtuple
import json
import time
from contextlib import contextmanager, ExitStack

import os
import pwd

#TODO: delete Experiment class

# code for 2 pmdport's

Environment = namedtuple('Environment', ['client_ifname', 'server_ifname', 'client_ip_wan', 'server_ip_wan', 'client_ip_lan', 'server_ip_lan', 'server_pci', 'client_pci'])
Experiment = namedtuple('Experiment', ['name', 'btlbw', 'queue_size', 'queue_speed', 'flows', 'server_log', 'client_log', 'server_tcpdump_log', 'bess_tcpdump_log', 'queue_log'])
Flow = namedtuple('Flow', ['ccalg', 'duration', 'rtt', 'client_port', 'server_port'])

#note: currently's RTT's are set per machine so we can't have different RTT

class Experiment(object):
    def __init__(self,
                 name,
                 btlbw,
                 queue_size,
                 queue_speed,
                 flows,
                 server_log,
                 client_log,
                 server_tcpdump_log,
                 bess_tcpdump_log,
                 queue_log,
                 env):
        self.name = name
        self.btlbw = btlbw
        self.queue_size = queue_size
        self.queue_speed = queue_speed
        self.flows = flows
        self.server_log = server_log
        self.client_log = client_log
        self.server_tcpdump_log = server_tcpdump_log
        self.bess_tcpdump_log = bess_tcpdump_log
        self.queue_log = queue_log
        self.env = env

    def __repr__(self):
        #attribs = ', '.join(
        #    '{}={}'.format(name, val) for name, val in exp.__dict__.items())
        attribs = json.dumps(self.__dict__,
                             sort_keys=True,
                             indent=4,
                             separators=(',','='))
        return 'Experiment({})'.format(attribs)

    def __str__(self):
        return repr(self) 
        
    def run(self):
        print('STARTING EXPERIMENT')
        print(self)
        max_duration = 0
        with ExitStack() as stack:
            # start bess
            print(stack.enter_context(self.start_bess()))
            # set rtt -- for now cannot set RTT per flow so just use first one
            stack.enter_context(self.set_rtt(self.flows[0].rtt))
            # monitor the queue
            stack.enter_context(self.start_monitor_bess())
            # start each flow
            for idx, flow in enumerate(self.flows):
                if flow.duration > max_duration:
                    max_duration = flow.duration
                stack.enter_context(self.start_iperf_client(flow, (idx % 32) + 1))
            # TODO: change this to check if iperf done
            # wait until flows finish
            print('SLEEPING FOR {}s'.format(max_duration))
            time.sleep(max_duration)
            # show pipeline
            cmd = '/opt/bess/bessctl/bessctl show pipeline'
            print(pipe_syscalls([cmd]))
            cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
            print(pipe_syscalls([cmd]))
        print('EXPERIMENT DONE')
    
    @contextmanager
    def start_bess(self):
        cmd = '/opt/bess/bessctl/bessctl daemon start'
        pipe_syscalls([cmd])
        cmd = ("/opt/bess/bessctl/bessctl run active-middlebox-pmd "
               "\"BESS_PCI_SERVER='{}', "
               "BESS_PCI_CLIENT='{}', "
               "BESS_QUEUE_SIZE='{}', "
               "BESS_QUEUE_SPEED='{}'\"").format(self.env.server_pci,
                                                 self.env.client_pci,
                                                 self.queue_size,
                                                 self.queue_speed)
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
                   self.server_log)
        yield pipe_syscalls([cmd], sudo=False)
        self.cleanup_remote_cmd(ip=self.env.server_ip_wan,
                                cmd='iperf3',
                                filepath=self.server_log)

    @contextmanager
    def start_tcpdump_server(self, flow):
        cmd = ('ssh -p 22 rware@{} '
               'sudo tcpdump -n --packet-buffered '
               '--snapshot-length=65535 '
               '--interface={} '
               '-w {} '
               'port {} '
               '> /dev/null 2> /dev/null < /dev/null & ').format(
                   self.env.server_ip_wan,
                   self.env.server_ifname,
                   self.server_tcpdump_log,
                   flow.client_port)
        yield pipe_syscalls([cmd], sudo=False)
        self.cleanup_remote_cmd(ip=self.env.server_ip_wan,
                                cmd='tcpdump',
                                filepath=self.server_tcpdump_log)

    @contextmanager
    def start_monitor_bess(self):
        cmd = 'tail -n1 -f /tmp/bessd.INFO > {} &'.format(self.queue_log)
        # for some reason using subprocess here just hangs so use os.system instead
        yield os.system(cmd)
        subprocess.run(['pkill','-9','tail'])
        #self.cleanup_local_cmd(cmd='tail')

    @contextmanager
    def start_tcpdump_bess(self):
        cmd = ('nohup /opt/bess/bessctl/bessctl tcpdump port_inc0 out 0 -n '
               '-s 65535 '
               '-w {} &> /dev/null &').format(self.bess_tcpdump_log)
        yield subprocess.run(shlex.split(cmd)) #pipe_syscalls([cmd])
        self.cleanup_local_cmd(cmd=self.bess_tcpdump_log)

    @contextmanager
    def start_iperf_client(self, flow, affinity):
        with self.start_iperf_server(flow, affinity):
            cmd = ('ssh -p 22 rware@{} '
                   'nohup iperf3 --client {} '
                   '--verbose '
                   '--bind {} '
                   '--cport {} '
                   '--linux-congestion {} '
                   '--interval 0.5 '
                   '--time {} '
                   '--length 1024K '
                   '--affinity {} '
                   '--set-mss 1500 '
                   '--window 100M '
                   '--zerocopy '
                   '--logfile {} '
                   '> /dev/null 2> /dev/null < /dev/null &').format(
                       self.env.client_ip_wan,
                       self.env.server_ip_lan,
                       self.env.client_ip_lan,
                       flow.client_port,
                       flow.ccalg,
                       flow.duration,
                       affinity,
                       self.client_log)
            yield pipe_syscalls([cmd], sudo=False)
        self.cleanup_remote_cmd(ip=self.env.client_ip_wan,
                                cmd='iperf3',
                                filepath=self.client_log)
        
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
            close_proc = subprocess.run(shlex.split(cmd))
            if close_proc.returncode == 0:
                print('Process for cmd not found: {}'.format(cmd))
        finally:
            if filepath is not None:
                # copy remote file to local machine and delete on remote machine
                run = 'scp rware@{}:{} .'.format(ip, filepath)
                pipe_syscalls([run], sudo=False)
                run = 'ssh -p 22 rware@{} rm -f {}'.format(ip, filepath)
                pipe_syscalls([run], sudo=False)

    def cleanup_local_cmd(self, cmd):
        run = 'sudo pkill -f {}'.format(cmd)
        pipe_syscalls([run], sudo=False)

        
def run_iperf(flows, env, exp):
    try:
        click.echo('RUNNING IPERF')
        for idx, flow in enumerate(flows):
            cmd = ('ssh -p 22 rware@{} '
                   'nohup iperf3 --server '
                   '--bind {} '
                   '--port {} '
                   '--one-off '
                   '--affinity {} '
                   '--logfile {} '
                   ' > /dev/null 2> /dev/null < /dev/null &').format(env.server_ip_wan,
                                                                     env.server_ip_lan,
                                                                     flow.server_port,
                                                                     (idx % 32) + 1, 
                                                                     exp.server_log)
            click.echo(pipe_syscalls([cmd], sudo=False))

            cmd = ('ssh -p 22 rware@{} '
                   'sudo tcpdump -n -s 65535 '
                   '-i enp6s0f0 '
                   '-w {} '
                   'port {} '
                   ' > /dev/null 2> /dev/null < /dev/null &').format(env.server_ip_wan, exp.server_tcpdump_log, flow.client_port)
            click.echo(pipe_syscalls([cmd], sudo=False))
        
        # start monitoring of BESS output
        cmd = 'tail -n1 -f /tmp/bessd.INFO &> {} &'.format(exp.queue_log)
        click.echo(cmd)
        #result = pipe_syscalls([cmd], sudo=False)
        #click.echo(result)
        #if pipe_syscalls([cmd], sudo=False):
        #    raise RuntimeError('Encountered error running cmd: {}'.format(cmd))
        
        # start BESS tcpdump
        cmd = ('nohup /opt/bess/bessctl/bessctl tcpdump port_inc0 out 0 -n '
               '-s 65535 '
               '-w {} &> /dev/null &'.format(exp.bess_tcpdump_log))
        pipe_syscalls([cmd])
    
        for idx, flow in enumerate(flows):
            cmd = ('ssh -p 22 rware@{} '
                   'nohup iperf3 --client {} '
                   '--verbose '
                   '--bind {} '
                   '--cport {} '
                   '--linux-congestion {} '
                   '--interval 0.5 '
                   '--time {} '
                   '--length 1024K '
                   '--affinity {} '
                   '--set-mss 1500 '
                   '--window 100M '
                   '--zerocopy '
                   '--logfile {} '
                   '> /dev/null 2> /dev/null < /dev/null &').format(env.client_ip_wan,
                                                                    env.server_ip_lan,
                                                                    env.client_ip_lan,
                                                                    flow.client_port,
                                                                    flow.ccalg,
                                                                    flow.duration,
                                                                    (idx % 32) + 1,
                                                                    exp.client_log)
            pipe_syscalls([cmd], sudo=False)
        
        # TODO: remove hardcoding of the number of processors
        # TODO: check for largest flow duration
        click.echo('SLEEPING FOR {}s'.format(flows[0].duration))
        time.sleep(flows[0].duration)

        cmd = 'ssh -p 22 rware@{} pgrep -x iperf3'.format(env.server_ip_wan)
        pgrep_iperf = pipe_syscalls([cmd], sudo=False)

        while pgrep_iperf is not None or pgrep_iperf.strip() != '':
            time.sleep(1)
            pgrep_iperf = pipe_syscalls([cmd], sudo=False)
    except (KeyboardInterrupt, SystemExit):
        raise RuntimeError('Experiment aborted!')
    finally:
        #kill all processes
        cmd = 'sudo killall ssh'
        pipe_syscalls([cmd], sudo=False)
        cmd = 'sudo killall tcpdump'
        pipe_syscalls([cmd], sudo=False)
        cmd = 'sudo killall tail'
        pipe_syscalls([cmd], sudo=False)
        cmd = 'ssh -p 22 rware@{} sudo killall tcpdump'.format(env.client_ip_wan)
        pipe_syscalls([cmd], sudo=False)
        
        # get results from server & client
        cmd = 'scp rware@{}:{} .'
        pipe_syscalls([cmd.format(env.client_ip_wan, exp.client_log)], sudo=False)
        #pipe_syscalls([cmd.format(env.client_ip_wan, CLIENT_LOG)])
        pipe_syscalls([cmd.format(env.server_ip_wan, exp.server_log)], sudo=False)
        pipe_syscalls([cmd.format(env.server_ip_wan, exp.server_tcpdump_log)], sudo=False)
        
        # delete files
        cmd = 'ssh -p 22 rware@{} rm -f {}'
        #pipe_syscalls([cmd.format(env.client_ip_wan, CLIENT_LOG)])
        #pipe_syscalls([cmd.format(env.server_ip_wan, SERVER_LOG)])
        #pipe_syscalls([cmd.format(env.server_ip_wan, SERVER_TCPDUMP_LOG)])
        pipe_syscalls([cmd.format(env.client_ip_wan, exp.client_log)], sudo=False)
        pipe_syscalls([cmd.format(env.server_ip_wan, exp.server_log)], sudo=False)
        pipe_syscalls([cmd.format(env.server_ip_wan, exp.server_tcpdump_log)], sudo=False)
        
        # show pipeline
        cmd = '/opt/bess/bessctl/bessctl show pipeline'
        click.echo(pipe_syscalls([cmd]))
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        click.echo(pipe_syscalls([cmd]))
        
        cmd = '/opt/bess/bessctl/bessctl show port'
        click.echo(pipe_syscalls([cmd]))
        
        cmd = '/opt/bess/bessctl/bessctl show module'
        click.echo(pipe_syscalls([cmd]))
        
        cmd = '/opt/bess/bessctl/bessctl show worker'
        click.echo(pipe_syscalls([cmd]))


@click.group()
def main():
    pass

# TODO: add option to only run specific experiment by name
@click.command()
@click.argument('config_file')
def run_experiment(config_file):
    _run_experiment(config_file)

def _run_experiment(config_file):
    with open(config_file) as f:
        experiments = json.load(f)

    env = Environment(client_ifname = 'enp6s0f1',
                      server_ifname = 'enp6s0f0',
                      client_ip_lan = '192.0.0.4',
                      server_ip_lan = '192.0.0.1',
                      client_ip_wan = '128.104.222.54',
                      server_ip_wan = '128.104.222.70',
                      server_pci = '06:00.0',
                      client_pci = '06:00.1')

    for experiment_name, experiment in experiments.items():
        _start_bess(env.server_ifname ,env.client_ifname,
                    experiment['queue_size'], experiment['queue_speed'])
        rtt = int(experiment['flows'][0]['rtt'])
        set_rtt(env.client_ip_wan, rtt)
        flows = [Flow(ccalg=flow['ccalg'],
                      duration=int(flow['duration']),
                      rtt=int(flow['rtt']),
                      client_port=5555+idx,
                      server_port=5201+idx,)
                 for idx, flow in enumerate(experiment['flows'])]
        exp = Experiment(name = experiment_name,
                         btlbw = int(experiment['btlbw']),
                         queue_size = int(experiment['queue_size']),
                         queue_speed = int(experiment['queue_speed']),
                         flows = flows,
                         server_log = '/users/rware/server-{}.iperf'.format(experiment_name),
                         client_log = '/users/rware/client-{}.iperf'.format(experiment_name),
                         server_tcpdump_log= '/users/rware/server-tcpdump-{}.pcap'.format(experiment_name),
                         bess_tcpdump_log= '/opt/15-712/cctestbed/bess-tcpdump-{}.pcap'.format(experiment_name),
                         queue_log= '/opt/15-712/cctestbed/queue-{}.txt'.format(experiment_name))
        try:
            run_iperf(flows, env, exp)
        finally:
            remove_rtt(env.client_ip_wan)
            _stop_bess()
        break # run just one for testing

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
#main.add_command(run_experiment)

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
        procs.append(subprocess.Popen(shlex.split(cmd), stdin=procs[idx].stdout, stdout=subprocess.PIPE))
        #procs[idx-1].stdout.close()
    try:
        stdout, stderr = procs[-1].communicate(timeout=5)
    except subprocess.TimeoutExpired as e:
        # need to kill all the processes if a timeout occurs
        for proc in procs:
            proc.kill()
        click.echo('Process took longer than 5 seconds to finish: {}'.format(procs[-1].args))
        raise e
    if procs[-1].returncode != 0 or stderr is not None:
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
    cmds = ['/opt/bess/bin/dpdk-devbind.py --status', 'grep {}'.format(ifname)]
    pci = pipe_syscalls(cmds)
    pci = pci.split()[0][-7:]
    if pci.strip() == '':
        raise ValueError('There is no interface with name {}.'.format(ifname))
    return pci


def get_interface_ip(ifname):
    """Return the IP of the given interface.

    Parameters:
    -----------
    ifname : str
       Interface name

    Raise: ValueError there is no interface with given name
    """
    cmd = ['ip addr', 'grep {}'.format(ifname), 'grep inet']
    ip = pipe_syscalls(cmd)
    if ip is None or ip.strip() == '':
        raise ValueError('There is no interface with name {}.'.format(ifname))
    ip, mask = ip.split()[1].split('/')
    return ip, mask

def store_env_var(var, value):
    """Store an evironment variable in /etc/environment"""
    pipe_syscalls(['sudo sed -i "/^{}/ d" /etc/environment'.format(var)])
    with open('/etc/environment', 'a') as f:
        f.write('{}={}\n'.format(var, value))

def connect_dpdk(ifname_server, ifname_client):
    click.echo('CONNECTING DPDK')
    # TODO: if interfaces are not connected to kernel then throw an error

    # if already connected, just return
    connected_pcis = pipe_syscalls(['/opt/bess/bin/dpdk-devbind.py --status',
                                    'grep drv=uio_pci_generic'])
    if not (connected_pcis is None or connected_pcis.strip() == '') :
        #TODO: remove hardcoded number here
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
