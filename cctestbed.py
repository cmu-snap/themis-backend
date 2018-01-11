import click
import subprocess
import shlex
from collections import namedtuple
import json
import time

# code for 2 pmdport's

Environment = namedtuple('Environment', ['client_ifname', 'server_ifname', 'client_ip_wan', 'server_ip_wan', 'client_ip_lan', 'server_ip_lan'])
Experiment = namedtuple('Experiment', ['name', 'btlbw', 'queue_size', 'queue_speed', 'flows'])
Flow = namedtuple('Flow', ['cc_alg', 'duration', 'rtt', 'client_port', 'server_port'])

#note: currently's RTT's are set per machine so we can't have different RTT

SERVER_LOG = '/users/rware/server-{}.iperf'
CLIENT_LOG = '/users/rware/client-{}.iperf'
SERVER_TCPDUMP_LOG = '/users/rware/server-tcpdump-{}.pcap'
BESS_TCPDUMP_LOG = '/opt/15-712/cctestbed//bess-tcpdump-{}.pcap'
QUEUE_LOG = '/opt/15-712/cctestbed/queue-{}.txt'

@click.group()
def main():
    pass

# TODO: add option to only run specific experiment by name
@click.command()
@click.argument('config_file')
def run_experiment(config_file):    
    with open(config_file) as f:
        experiments = json.load(f)

    env = Environment(client_ifname = 'enp6s0f0',
                      server_ifname = 'enp6s0f1',
                      client_ip_wan = '192.0.0.4',
                      server_ip_wan = '192.0.0.1',
                      client_ip_lan = '128.104.222.54',
                      server_ip_lan = '128.104.222.70')

    for experiment_name, experiment in experiments.items():
        start_bess('enp6s0f0','enp6s0f1',
                   experiment['queue_size'], experiment['queue_speed'])
        SERVER_LOG = SERVER_LOG.format(experiment_name)
        CLIENT_LOG = CLIENT_LOG.format(experiment_name)
        SERVER_TCPDUMP_LOG = SERVER_TCPDUMP_LOG.format(experiment_name)
        CLIENT_TCPDUMP_LOG = CLIENT_TCPDUMP_LOG.format(experiment_name)
        QUEUE_LOG = QUEUE_LOG.format(experiment_name)
        
        # just run first one for testing
        rtt = experiment['flows'][0]['rtt']
        set_rtt('128.104.222.54', rtt)
        flows = [Flow(cc_alg=flow['cc_alg'],
                      duration=flow['duration'],
                      rtt=flow['rtt'],
                      client_port=5555+idx,
                      server_port=5201+idx,)
                      for idx, flow in enumerate(experiment['flows'])]

        run_iperf(flows, env)
       
        remove_rtt('128.104.222.54')
        stop_bess()
        break

@click.command()
@click.argument('ifname_server')
@click.argument('ifname_client')
@click.argument('queue_size')
@click.argument('queue_speed')
def start_bess(ifname_server, ifname_client, queue_size, queue_speed):
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
    subprocess.run(['/opt/bess/bessctl/bessctl', 'daemon stop'])
    
main.add_command(start_bess)
main.add_command(stop_bess)
main.add_command(run_experiment)

def pipe_syscalls(cmds):
    """Run linux commands, piping input and output

    Parameters:
    -----------
    cmds : commands to call
    
    Reference: 
    piping shell commands - https://docs.python.org/2/library/subprocess.html#replacing-shell-pipeline
    """
    click.echo('Running cmd: {}'.format(' | '.join(cmds)))
    procs = []
    procs.append(subprocess.Popen(shlex.split(cmds[0]), stdout=subprocess.PIPE))
    for idx, cmd in enumerate(cmds[1:]):
        procs.append(subprocess.Popen(shlex.split(cmd), stdin=procs[idx].stdout, stdout=subprocess.PIPE))
        #procs[idx-1].stdout.close()
    stdout, stderr = procs[-1].communicate()
    if stderr is not None:
        raise subprocess.CallProcessError('Encountered error running cmd: {}/n{}'.format(cmd, stderr))
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


def run_iperf(flows, env):
    for idx, flow in enumerate(flows):
        cmd = ('ssh -p 22 rware@{} '
               'nohup iperf3 --server '
               '--bind {} '
               '--port {} '
               '--one-off '
               '--affinity {} '
               '--logfile {} '
               ' > /dev/null 2> /dev/null < /dev/null &').format(env.server_ip_wan,
                                                                 env.server_ip_local,
                                                                 flow.server_port,
                                                                (idx % 32) + 1, 
                                                                 SERVER_LOG)
        #click.echo(pipe_syscalls([cmd]))
        click.echo(cmd)
        cmd = ('ssh -p 22 rware@{} '
               'sudo tcpdump -n -s 65535 '
               '-i enp6s0f0 '
               '-w {} '
               'port {} '
               ' > /dev/null 2> /dev/null < /dev/null &').format(SERVER_TCPDUMP_LOG, flow.client_port, flow.server_port)
        #click.echo(pipe_syscalls([cmd]))
        click.echo(cmd)
        
    # start monitoring of BESS output
    cmd = 'tail -n1 -f /tmp/bessd.INFO > {} &'.format(QUEUE_LOG)
    #pipe_syscalls([cmd])
    click.echo(cmd)
    
    # start BESS tcpdump
    cmd = ('nohup /opt/bess/bessctl/bessctl tcpdump port_inc1 out 0 -n '
           '-s 65535 '
           '-w {} &> /dev/null'.format(BESS_TCPDUMP_LOG))
    #pipe_syscalls([cmd])
    click.echo(cmd)
    
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
                                                              CLIENT_LOG)
    #pipe_syscalls([cmd])
    click.echo(cmd)
    
    # TODO: remove hardcoding of the number of processors
    # TODO: check for largest flow duration
    time.sleep(flows[0].duration)

    cmd = 'ssh -p 22 rware@{} pgrep -x iperf3'.format(env.server_ip_wan)
    #pgrep_iperf = pipe_syscalls([cmd])
    click.echo(cmd)
    while pgrep_iperf is not None or pgrep_iperf.strip() != '':
        time.sleep(1)

    #kill all processes
    cmd = 'sudo killall ssh'
    #pipe_syscalls([cmd])
    click.echo(cmd)
    cmd = 'sudo killall tcpdump'
    #pipe_syscalls([cmd])
    click.echo(cmd)
    cmd = 'sudo killall tail'
    #pipe_syscalls([cmd])
    click.echo(cmd)
    cmd = 'ssh -p 22 rware@{} sudo killall tcpdump'.format(env.client_ip_wan)
    #pipe_syscalls([cmd])
    click.echo(cmd)
    
    # get results from server
    cmd = 'scp rware@{}:{}'
    click.echo(cmd.format(env.client_ip_wan, CLIENT_LOG))
    #pipe_syscalls([cmd.format(env.client_ip_wan, CLIENT_LOG)])
    click.echo(cmd.format(env.server_ip_wan, SERVER_LOG))
    click.echo(cmd.format(env.server_ip_wan, SERVER_TCPDUMP_LOG))
    
    
    
    # get results from client

    # delete files
    cmd = 'ssh -p 22 rware@{} rm -f {}'
    #pipe_syscalls([cmd.format(env.client_ip_wan, CLIENT_LOG)])
    #pipe_syscalls([cmd.format(env.server_ip_wan, SERVER_LOG)])
    #pipe_syscalls([cmd.format(env.server_ip_wan, SERVER_TCPDUMP_LOG)])
    click.echo([cmd.format(env.client_ip_wan, CLIENT_LOG)])
    click.echo([cmd.format(env.server_ip_wan, SERVER_LOG)])
    click.echo([cmd.format(env.server_ip_wan, SERVER_TCPDUMP_LOG)])

    
    # show pipeline
    cmd = '/opt/bess/bessctl/bessctl show pipeline'
    #pipe_syscalls([cmd])
    click.echo(cmd)
    cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
    #pipe_syscalls([cmd])    
    click.echo(cmd)

    cmd = '/opt/bess/bessctl/bessctl show port'
    #pipe_syscalls([cmd])
    click.echo(cmd)

    cmd = '/opt/bess/bessctl/bessctl show module'
    #pipe_syscalls([cmd])
    click.echo(cmd)

    cmd = '/opt/bess/bessctl/bessctl show worker'
    #pipe_syscalls([cmd])
    click.echo(cmd)

    

#def set_rtt(server_ip_lan, client_ip_lan, client_ip_wan, rtt):
def set_rtt(client_ip_wan, rtt):
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
    click.echo(pipe_syscalls([cmd]))

    # output new average

    
    #new_avg_rtt = pipe_syscalls([cmd_rtt])
    #click.echo('NEW AVG RTT = {}'.format(new_avg_rtt))
    #return new_avg_rtt
    

def remove_rtt(machine_ip):
    cmd = 'ssh -p 22 rware@{} sudo tc qdisc del dev enp6s0f0 root netem'.format(
        machine_ip)
    pipe_syscalls([cmd])
    
if __name__ == '__main__':
    main()
