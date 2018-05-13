from collections import namedtuple
from datetime import datetime
from contextlib import contextmanager, ExitStack
from logging.config import fileConfig
from json import JSONEncoder
import argparse
import json
import os
import getpass
import pwd
import subprocess
import shlex
import time
import logging
import yaml
import paramiko

fileConfig('logging_config.ini')

Host = namedtuple('Host', ['ifname', 'ip_wan', 'ip_lan', 'pci'])
Flow = namedtuple('Flow', ['ccalg', 'start_time', 'end_time', 'rtt',
                           'server_port', 'client_port', 'client_log', 'server_log'])

USERNAME = getpass.getuser()
SEVER_LOCAL_IFNAME = 'ens13'
CLIENT_LOCAL_IFNAME = 'ens3f0'
# TODO: implement functions for starting tcpdump (issues with sudo?)
# TODO: write function to validate experiment output -- number packets output by
# queue module, 

# TODO: come up with more elegant way to run remote sudo commands
# -- more machine setup: add ability to run stuff without sudo to potato (client)
# -- create /etc/sudoers.d/cctestbed

# TODO: to set affinity, get number of processors on remote machines using 'nproc --all
# TODO: check every seconds if processes still running instead of using time.sleep
# TODO: allow starting and stopping flows at any time
                                  
class RemoteCommand:
    """Command to run on a remote machine in the background"""
    def __init__(self, cmd, ip_addr,
                 stdout='/dev/null', stdin='/dev/null', stderr='/dev/null', logs=[],
                 cleanup_cmd=None, sudo=False):
        self.cmd = cmd.strip()
        self.ip_addr = ip_addr
        self.stdout = stdout
        self.stdin = stdin
        self.stderr = stderr
        self.logs = logs
        self.cleanup_cmd = cleanup_cmd
        self.sudo = sudo
        self._ssh_client = None
        self._ssh_channel = None

    def _get_ssh_client(self):
        return get_ssh_client(self.ip_addr, USERNAME)
        
    def _get_ssh_channel(self, ssh_client):
        return ssh_client.get_transport().open_session()
        
    @contextmanager
    def __call__(self):
        self._ssh_client = self._get_ssh_client()
        self._ssh_channel = self._get_ssh_channel(self._ssh_client)
        pid = None
        try:
            stderr = self._ssh_channel.makefile_stderr()
            # run command and get PID
            if self.sudo:
                cmd = 'sudo {}'.format(self.cmd)
            else:
                cmd = self.cmd
            self._ssh_channel.exec_command('{} > {} 2> {} < {} &'.format(cmd,
                                                                         self.stdout,
                                                                         self.stderr,
                                                                         self.stdin))
            ssh_client = self._get_ssh_client()
            logging.info('Running cmd ({}): {}'.format(self.ip_addr, cmd))
            _, stdout, _ = ssh_client.exec_command('pgrep -f "^{}"'.format(self.cmd))
            pid = stdout.readline().strip()
            logging.info('PID={}'.format(pid))
            # check if immediately get nonzero exit status
            if self._ssh_channel.exit_status_ready():
                if self._ssh_channel.recv_exit_status() != 0:
                    raise RuntimeError(
                        'Got a non-zero exit status running cmd: {}.\n{}'.format(
                            self.cmd, stderr.read()))
            assert(pid)
            pid = int(pid)
            yield pid
            stdout.close()
            stderr.close()
        finally:
            self._ssh_channel.close()
            self._ssh_client.close()
            logging.info('Cleaning up cmd ({}): {}'.format(self.ip_addr, self.cmd))
            # on cleanup kill process & collect all logs
            ssh_client = self._get_ssh_client()
            kill_cmd = 'kill {}'.format(pid)
            if self.sudo:
                kill_cmd = 'sudo kill {}'.format(pid)
            logging.info('Running cmd ({}): {}'.format(self.ip_addr, kill_cmd))
            ssh_client.exec_command(kill_cmd)
            ssh_client.close()
            if self.cleanup_cmd is not None:
                # TODO: run cleanup cmd as sudo too?
                ssh_client = self._get_ssh_client()
                logging.info('Running cmd ({}): {}'.format(self.ip_addr,
                                                           self.cleanup_cmd))
                ssh_client.exec_command(self.cleanup_cmd)
                ssh_client.close()
            for log in self.logs:
                ssh_client = self._get_ssh_client()
                sftp_client = ssh_client.open_sftp()
                logging.info('Copying remote file ({}): {}'.format(self.ip_addr,
                                                                   log))
                try:
                    sftp_client.get(log, os.path.join('/tmp',log))
                    rm_cmd = 'rm {}'.format(log)
                    if self.sudo:
                        rm_cmd = 'sudo rm {}'.format(log)
                    logging.info('Running cmd ({}): {}'.format(self.ip_addr, rm_cmd))
                    ssh_client.exec_command(rm_cmd)
                except FileNotFoundError as e:
                    logging.warning('Could not find file "{}" on remote server "{}"'.format(
                        log, self.ip_addr))
                sftp_client.close()
                ssh_client.close()
                
    def __str__(self):
        return {'ip_addr': self.ip_addr, 'cmd': self.cmd,
                'logs': self.logs, 'username': USERNAME}

    def __repr__(self):
        return 'RemoteCommand({})'.format(self.__str__())
            
class Experiment:
    def __init__(self, name, btlbw, queue_size, flows, server, client):
        self.exp_time = (datetime.now().isoformat()
                         .replace(':','').replace('-','').split('.')[0])
        self.name = name
        self.btlbw = btlbw
        self.queue_size = queue_size
        self.server = server
        self.client = client
        # store what version of this code we are running -- could be useful later
        self.git_commit = run_local_command('git rev-parse HEAD')
        self.logs = {
            'server_tcpdump_log': '/tmp/server-tcpdump-{}-{}.pcap'.format(
                self.name, self.exp_time),
            'bess_tcpdump_log': '/tmp/bess-tcpdump-{}-{}.pcap'.format(
                self.name, self.exp_time),
            'queue_log': '/tmp/queue-{}-{}.txt'.format(self.name, self.exp_time),
            'client_tcpdump_log': '/tmp/client-tcpdump-{}-{}.pcap'.format(
                self.name, self.exp_time),
            'description_log': '/tmp/{}-{}.json'.format(self.name, self.exp_time),
            'tcpprobe_log': '/tmp/tcpprobe-{}-{}.txt'.format(self.name, self.exp_time)
            }
        self.tar_filename = '/tmp/{}-{}.tar.gz'.format(self.name, self.exp_time)
        # update flow objects with log filenames
        self.flows = []
        for flow in flows:
            client_log = '/tmp/client-{}-{}-{}.iperf'.format(
                flow.client_port, self.name, self.exp_time)
            server_log = '/tmp/server-{}-{}-{}.iperf'.format(
                flow.server_port, self.name, self.exp_time)
            # tuples are immutable so we must create new ones to update log attributes
            new_flow = flow._replace(client_log=client_log,
                                     server_log=server_log)
            self.flows.append(new_flow)

    def get_wait_times(self):
        #start_times = [flow.wait_time for time in flow]
        pass
    
    def run(self):
        with ExitStack() as stack:
            self._run_tcpdump('server', stack)
            self._run_tcpdump('client', stack)
            self._run_tcpprobe(stack)
            self._run_all_flows(stack)
    
    def _validate(self):
        # check queue log has all lines with the same number of columns
        # check queue log isn't empty
        # check that the number of lines in queue log equal to number packets enqueued,
        # dequeued, dropped
        # check number of packets enqueued + dropped, numbers of packets at tcpdump sender -- MAY HAVE TO ACCOUNT FOR IPERF PACKETS?
        # check number of packets dequeued = number of packets at tcpdump receiver
        # check number of packets enqueued + dropped = number of packets in tcppprobe
        pass

    def _show_bess_pipeline(self):
        cmd = '/opt/bess/bessctl/bessctl show pipeline'
        logging.info(run_local_command(cmd))
        cmd = '/opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        logging.info(run_local_command(cmd))
        cmd = '/opt/bess/bessctl/bessctl command module queue_delay0 get_status EmptyArg'
        logging.info(run_local_command(cmd))


    def _run_tcpdump(self, host, stack):
        start_tcpdump_cmd = ('tcpdump -n --packet-buffered '
                             '--snapshot-length=65535 '
                             '--interface={} '
                             '-w {}')
        tcpdump_logs = None
        if host == 'server':
            start_tcpdump_cmd = start_tcpdump_cmd.format(self.server.ifname,
                                                         self.logs['server_tcpdump_log'])
            
            tcpdump_logs = [self.logs['server_tcpdump_log']]
            start_tcpdump = RemoteCommand(start_tcpdump_cmd,
                                          self.server.ip_wan,
                                          logs=tcpdump_logs,
                                          sudo=True)
        elif host == 'client':
            start_tcpdump_cmd = start_tcpdump_cmd.format(self.client.ifname,
                                                         self.logs['client_tcpdump_log'])
            tcpdump_logs = [self.logs['client_tcpdump_log']]
            start_tcpdump = RemoteCommand(start_tcpdump_cmd,
                                          self.client.ip_wan,
                                          logs=tcpdump_logs,
                                          sudo=True)
        else:
            raise ValueError('Expected either server or client to host')
        return stack.enter_context(start_tcpdump())
        
    def _run_tcpprobe(self, stack):
        # assumes that tcp_bbr_measure is installed @ /opt/tcp_bbr_measure on iperf client
        insmod_cmd = ('sudo insmod '
                      '/opt/tcp_bbr_measure/tcp_probe_ray.ko port=0 full=1 '
                      '&& sudo chmod 444 /proc/net/tcpprobe ')
        ssh_client = get_ssh_client(self.client.ip_wan, username=USERNAME)
        logging.info('Running cmd ({}): {}'.format(self.client.ip_wan,
                                                   insmod_cmd))
        try:
            _, stdout, stderr = ssh_client.exec_command(insmod_cmd)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                raise RuntimeError(
                    'Got a non-zero exit status running cmd: {}.\n{}'.format(
                        self.cmd, stderr.read()))
        finally:
            ssh_client.close()

        try:
            start_tcpprobe_cmd = 'cat /proc/net/tcpprobe'    
            start_tcpprobe = RemoteCommand(start_tcpprobe_cmd,
                                           self.client.ip_wan,
                                           stdout = self.logs['tcpprobe_log'],
                                           stderr = self.logs['tcpprobe_log'],
                                           logs=[self.logs['tcpprobe_log']],
                                           cleanup_cmd='sudo rmmod tcp_probe_ray')
        except:
            # need to still rmmod if we can't create the remote command
            # for some reason
            ssh_client = get_ssh_client(self.client.ip_wan, username=USERNAME)
            ssh_client.exec_command('sudo rmmod tcp_probe_ray')
            ssh_client.close()
        return stack.enter_context(start_tcpprobe())
    
    @contextmanager
    def _run_bess_monitor(self):
        # have to use system here; subprocess just hangs for some reason
        with open(self.logs['queue_log'], 'w') as f:
            f.write('enqueued, time, src, seq, datalen, '
                    'size, dropped, queued, batch')
        # only log "good" lines, those that start with 0 or 1
        cmd = 'tail -n1 -f /tmp/bessd.INFO | grep -e "^0" -e "^1" >> {} &'.format(self.logs['queue_log'])
        logging.info('Running cmd: {}'.format(cmd))
        pid = None
        try:
            os.system(cmd)
            pid = run_local_command('pgrep -f "tail -n1 -f /tmp/bessd.INFO"')
            assert(pid)
            pid = int(pid)
            logging.info('PID={}'.format(pid))
            yield pid
        finally:
            logging.info('Cleaning up cmd: {}'.format(cmd))
            run_local_command('kill {}'.format(pid))
    
    @contextmanager
    def _run_bess(self):
        try:
            yield start_bess(self)
        finally:
            stop_bess()
    
    def _run_all_flows(self, stack):
        # run bess and monitor
        stack.enter_context(self._run_bess())
        self._show_bess_pipeline()
        stack.enter_context(self._run_bess_monitor())
        for flow in self.flows:
            start_server_cmd = ('iperf3 --server '
                                '--bind {} '
                                '--port {} '
                                '--one-off '
                                '--affinity {} '
                                '--logfile {} ').format(
                                    self.server.ip_lan,
                                    flow.server_port,
                                    1,
                                    flow.server_log)
        start_server = RemoteCommand(start_server_cmd,
                                     self.server.ip_wan,
                                     logs=[flow.server_log])
        stack.enter_context(start_server())
        
        for idx, flow in enumerate(self.flows):
            start_client_cmd = ('iperf3 --client {} '
                                '--port {} '
                                '--verbose '
                                '--bind {} '
                                '--cport {} '
                                '--linux-congestion {} '
                                '--interval 0.5 '
                                '--time {} '
                                #'--length 1024K '#1024K '
                                '--affinity {} '
                                #'--set-mss 500 ' # default is 1448
                                #'--window 100K '
                                '--zerocopy '
                                '--json '
                                '--logfile {} ').format(self.server.ip_lan,
                                                        flow.server_port,
                                                        self.client.ip_lan,
                                                        flow.client_port,
                                                        flow.ccalg,
                                                        flow.end_time - flow.start_time,
                                                        idx % 32,
                                                        flow.client_log)
            start_client = RemoteCommand(start_client_cmd,
                                         self.client.ip_wan,
                                             logs=[flow.client_log])
            stack.enter_context(start_client())
        # assume all flows start and stop at the same time
        time.sleep(flow.end_time - flow.start_time + 5)
        self._show_bess_pipeline()
        
    def __repr__(self):
        attrs = self.__str__()
        return 'Experiment({})'.format(attrs)
        
    def __str__(self):
        attrs = json.dumps(self.__dict__,
                           sort_keys=True,
                           indent=4)
        return attrs

def load_config_file(config_filename):
    """Parse YAML config file"""
    with open(config_filename) as f:
        config = yaml.safe_load(f)
    return config

def load_experiments(config):
    """Create experiments from config file and output to config"""
    client = Host(ifname=config['client']['ifname'],
                  ip_lan=config['client']['ip_lan'],
                  ip_wan=config['client']['ip_wan'],
                  pci=config['client']['pci'])
    server = Host(ifname=config['server']['ifname'],
                  ip_lan=config['server']['ip_lan'],
                  ip_wan=config['server']['ip_wan'],
                  pci=config['server']['pci'])
    experiments = {}
    for experiment_name, experiment in config['experiments'].items():
        flows = []
        server_port = 5201
        client_port = 5555
        for flow in experiment['flows']:
            assert(flow['start_time'] < flow['end_time'])
            flows.append(Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                              end_time=flow['end_time'], rtt=flow['rtt'],
                              server_port=server_port, client_port=client_port,
                              client_log=None, server_log=None))
            server_port += 1
            client_port += 1
        # sort flows according to their start times so they can be run in order
        flows.sort(key=lambda x: x.start_time)
        exp = Experiment(name=experiment_name,
                         btlbw=experiment['btlbw'],
                         queue_size=experiment['queue_size'],
                         flows=flows, server=server, client=client)
        assert(experiment_name not in experiments)
        experiments[experiment_name] = exp

        # save experiment to json file
        with open(exp.logs['description_log'], 'w') as f:
            json.dump(exp.__dict__, f)
    return experiments

def start_bess(experiment):
    cmd = 'sudo /opt/bess/bessctl/bessctl daemon start'
    run_local_command(cmd)
    cmd = ("/opt/bess/bessctl/bessctl run active-middlebox-pmd "
           "\"CCTESTBED_EXPERIMENT_DESCRIPTION='{}'\"").format(
               experiment.logs['description_log'])
    run_local_command(cmd)

def stop_bess():
    cmd = 'sudo /opt/bess/bessctl/bessctl daemon stop'
    run_local_command(cmd)
                  
def connect_dpdk(server, client, dpdk_driver='igb_uio'):
    # check if DPDK already connected
    cmd = '/opt/bess/bin/dpdk-devbind.py --status | grep drv={}'.format(dpdk_driver)
    proc = subprocess.run(cmd, check=False, shell=True, stdout=subprocess.PIPE)
    if proc.returncode == 0:
        logging.info('Interfaces already connected to DPDK')
        return server.pci, client.pci

    # get pcis
    expected_server_pci = get_interface_pci(SERVER_LOCAL_IFNAME)
    expected_client_pci = get_interface_pci(CLIENT_LOCAL_IFNAME)
    if expected_server_pci is None or expected_server_pci.strip()=='':
        return server.pci, client.pci
    assert(expected_server_pci == server.pci)
    assert(expected_client_pci == client.pci)

    # get ips on this machine
    server_if_ip, server_ip_mask = get_interface_ip(SERVER_LOCAL_IFNAME)
    client_if_ip, client_ip_mask = get_interface_ip(CLIENT_LOCAL_IFNAME)

    logging.info('Server: ifname = {}, pci = {}, if_ip = {}/{}'.format(
        SERVER_LOCAL_IFNAME, server.pci, server_if_ip, server_ip_mask))
    logging.info('Client: ifname = {}, pci = {}, if_ip = {}/{}'.format(
        CLIENT_LOCAL_IFNAME, client.pci, client_if_ip, client_ip_mask))    
    
    # make sure hugepages is started
    cmd = 'sudo sysctl vm.nr_hugepages=1024'
    run_local_command(cmd)

    # connect NIC interfaces to DPDK
    if dpdk_driver == 'igb_uio':
        cmd = 'sudo modprobe uio'
        run_local_command(cmd)
        cmd = 'sudo insmod {}'.format('/opt/bess/deps/dpdk-17.11/build/kmod/igb_uio.ko')
        run_local_command(cmd)
    else:
        cmd = 'sudo modprobe {}'.format(dpdk_driver)
        run_local_command(cmd)
    cmd = 'sudo ifconfig {} down'
    run_local_command(cmd.format(SERVER_LOCAL_IFNAME))
    run_local_command(cmd.format(CLIENT_LOCAL_IFNAME))
    cmd = 'sudo /opt/bess/bin/dpdk-devbind.py -b {} {}'
    run_local_command(cmd.format(dpdk_driver, server.pci))
    run_local_command(cmd.format(dpdk_driver, client.pci))
    
    return server.pci, client.pci
    
def get_interface_pci(ifname):
    """Return the PCI of the given interface
    
    Parameters:
    -----------
    ifname : str
       The interface name

    Raise: ValueError if there is no interface with given name
    """
    cmd = '/opt/bess/bin/dpdk-devbind.py --status | grep {}'.format(ifname)
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
    pci = proc.stdout
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
    cmd = 'ip addr | grep {} | grep inet'.format(ifname)
    ip = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8')
    if ip is None or ip.strip() == '':
        raise ValueError('There is no interface with name {}.'.format(ifname))
    ip, mask = ip.split()[1].split('/')
    return ip, mask

def run_local_command(cmd):
    """Run local command return stdout"""
    logging.info('Running cmd: {}'.format(cmd))
    proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE)
    return proc.stdout.decode('utf-8')

def get_ssh_client(ip_addr, username=USERNAME):
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_client.connect(ip_addr, username=username)
    return ssh_client

def main(args):
    #setup logging
    pass
    
def parse_args():
    """Parse commandline arguments"""
    parser = argparse.ArgumentParser(description='Run congestion control experiments')
    parser.add_argument('config_file', help='Configuration file describing experiment')
    args = parser.parse_args()
    return args
    
if __name__ == '__main__':
    args = parse_args()
    main(args)
