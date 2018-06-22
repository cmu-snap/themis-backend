#! /usr/bin/env python3

from command import RemoteCommand, run_local_command, get_ssh_client, exec_command

from collections import namedtuple, OrderedDict
from datetime import datetime
from contextlib import contextmanager, ExitStack
from json import JSONEncoder
import argparse
import json
import os
import pwd
import subprocess
import shlex
import time
import tarfile
import logging
import glob
import random
import yaml
import paramiko

from logging.config import fileConfig
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logging_config.ini')
fileConfig(log_file_path)    

Host = namedtuple('Host', ['ifname_remote', 'ifname_local', 'ip_wan', 'ip_lan', 'pci', 'key_filename', 'username'])
Flow = namedtuple('Flow', ['ccalg', 'start_time', 'end_time', 'rtt',
                           'server_port', 'client_port', 'client_log', 'server_log'])



# changes for aws experiments

#USERNAME = getpass.getuser()
#SERVER_LOCAL_IFNAME = 'ens13'
#CLIENT_LOCAL_IFNAME = 'enp11s0f0' #'ens3f0'

# TODO: write function to validate experiment output -- number packets output by
# queue module,

# TODO: come up with more elegant way to run remote sudo commands
# -- more machine setup: add ability to run stuff without sudo to potato (client)
# -- create /etc/sudoers.d/cctestbed

# TODO: to set affinity, get number of processors on remote machines using 'nproc --all
# TODO: check every seconds if processes still running instead of using time.sleep
# TODO: allow starting and stopping flows at any time

class Experiment:
    def __init__(self, name, btlbw, queue_size,
                 flows, server, client, config_filename):
        self.exp_time = (datetime.now().isoformat()
                            .replace(':','').replace('-','').split('.')[0])
        self.name = name
        self.btlbw = btlbw
        self.queue_size = queue_size
        self.server = server
        self.client = client
        # store what version of this code we are running -- could be useful later
        self.cctestbed_git_commit = run_local_command('git rev-parse HEAD').strip()
        self.bess_git_commit = run_local_command('git --git-dir=/opt/bess/.git '
                                                 '--work-tree=/opt/bess '
                                                 'rev-parse HEAD').strip()
        self.config_filename = config_filename
        self.logs = {
            'server_tcpdump_log': '/tmp/server-tcpdump-{}-{}.pcap'.format(
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

    def cleanup_last_experiment(self):
        logging.info('Cleaning up last experiment just in case...')
        run_local_command('pkill tail')
        cleanup_cmds = [('sudo pkill -9 tcpdump', ('server', 'client')),
                        ('sudo pkill -9 cat', ('client')),
                        ('sudo pkill iperf', ('server','client')),
                        ('sudo rmmod tcp_probe_ray', ('client'))]
        for cmd, machines in cleanup_cmds:
            if 'client' in machines:
                with get_ssh_client(self.client.ip_wan,
                                    username=self.client.username,
                                    key_filename=self.client.key_filename) as ssh_client:
                    exec_command(ssh_client, self.client.ip_wan, cmd)
            if 'server' in machines:
                with get_ssh_client(self.server.ip_wan,
                                    username=self.server.username,
                                    key_filename=self.server.key_filename) as ssh_client:
                    exec_command(ssh_client, self.server.ip_wan, cmd)

    def write_description_log(self):
        # save experiment to json file
        with open(self.logs['description_log'], 'w') as f:
            json.dump(self.__dict__, f)
                    
    def run(self):
        try:
            # make sure old stuff closed
            self.cleanup_last_experiment()
            logging.info('Running experiment: {}'.format(self.name))
            with ExitStack() as stack:
                self._run_tcpdump('server', stack)
                self._run_tcpdump('client', stack)
                self._run_tcpprobe(stack)
                self._run_all_flows(stack)
            # compress all log files
            proc=self._compress_logs()
            logging.info('Finished experiment: {}'.format(self.name))
            return proc 
        except Exception as e:
            logging.error('Error occurred while running experiment {}'.format(
                self.name), e)
            """
            logging.info('Deleting all generated logs')
            # DON'T DELETE DESCRIPTION LOG!!
            logs = self.logs.copy()
            logs.pop('description_log')
            for log in logs.values():
                if os.path.isfile(log):
                    os.remove(log)
                else:
                    logging.warning('Log file does not exist: {}'.format(log))
            # zip flow iperf logs
            for flow in self.flows:
                for log in [flow.server_log, flow.client_log]:
                    if os.path.isfile(log):
                        os.remove(log)
                    else:
                        logging.warning('Log file does not exist: {}'.format(log))
            """
            self._delete_logs(delete_description=False)
            raise e
        
    def get_wait_times(self):
        logging.info('Computing wait times for each flow')
        start_times = [flow.start_time for flow in self.flows]
        assert(sorted(start_times) == start_times)
        wait_times = [0]
        for previous_flow_start_time, start_time in zip(start_times[:-1],
                                                        start_times[1:]):
            if len(wait_times) > 1:
                wait_times.append(start_time - previous_flow_start_time)
            else:
                wait_times.append(start_time)
        return wait_times
        
    def _compress_logs(self):
        # will silently not compress logs that don't exists
        # gather log names
        all_logs = list(self.logs.values())
        for flow in self.flows:
            if os.path.isfile(flow.server_log):
                all_logs.append(flow.server_log)
            if os.path.isfile(flow.client_log):
                all_logs.append(flow.client_log)
        assert(os.path.isfile(self.config_filename))
        logs = [os.path.basename(self.config_filename)]
        logs += [os.path.basename(log) for log in all_logs if os.path.isfile(log)]
        if len(logs) == 0:
            logging.warning('Found no logs for this experiment to compress')
        logging.info('Compressing {} logs into tarfile: {}'.format(len(logs), self.tar_filename))
        cmd = 'cp {} {} && cd /tmp && tar -czf {} {} && rm -f {}'.format(
            self.config_filename,
            os.path.join('/tmp', os.path.basename(self.config_filename)),
            os.path.basename(self.tar_filename),
            ' '.join(logs),
            ' && rm -f '.join(logs))
        logging.info('Renaming config_filename in experiment from {} to {}'.format(
            self.config_filename,
            os.path.join('/tmp' , os.path.basename(self.config_filename))))
        # MAYBE: don't do this:
        # update config filename to be in /tmp/ (assumption with all other files)
        self.config_filename = os.path.join('/tmp', os.path.basename(self.config_filename))
        proc = subprocess.Popen(cmd, shell=True)
        logging.info('Running background command: {} (PID={})'.format(cmd, proc.pid))
        return proc
    
    def _delete_logs(self, delete_description=True):
        logging.info('[{}] Deleting all generated logs'.format(self.name))
        logs = self.logs.copy()
        if not delete_description:
            logs.pop('description_log')
        for log in logs:
            if os.path.isfile(log):
                os.remove(log)
            else:
                logging.warning('Log file does not exist: {}'.format(log))
        for flow in self.flows:
            for log in [flow.server_log, flow.client_log]:
                if os.path.isfile(log):
                    os.remove(log)
                else:
                    logging.warning('Log file does not exist: {}'.format(log))

    def _validate(self):
        # check queue log has all lines with the same number of columns
        # check queue log isn't empty
        # check that the number of lines in queue log equal to number packets enqueued,
        # dequeued, dropped
        # check number of packets enqueued + dropped, numbers of packets at tcpdump sender -- MAY HAVE TO ACCOUNT FOR IPERF PACKETS?
        # check number of packets dequeued = number of packets at tcpdump receiver
        # check number of packets enqueued + dropped = number of packets in tcppprobe
        raise NotImplementedError()

    def _show_bess_pipeline(self):
        cmd = 'sudo /opt/bess/bessctl/bessctl show pipeline'
        logging.info('\n'+run_local_command(cmd))
        cmd = 'sudo /opt/bess/bessctl/bessctl command module queue0 get_status EmptyArg'
        logging.info('\n'+run_local_command(cmd))
        cmd = 'sudo /opt/bess/bessctl/bessctl command module queue_delay0 get_status EmptyArg'
        logging.info('\n'+run_local_command(cmd))


    def _run_tcpdump(self, host, stack):
        start_tcpdump_cmd = ('tcpdump -n --packet-buffered '
                             '--snapshot-length=65535 '
                             '--interface={} '
                             '-w {}')
        tcpdump_logs = None
        if host == 'server':
            start_tcpdump_cmd = start_tcpdump_cmd.format(self.server.ifname_remote,
                                                         self.logs['server_tcpdump_log'])

            tcpdump_logs = [self.logs['server_tcpdump_log']]
            start_tcpdump = RemoteCommand(start_tcpdump_cmd,
                                          self.server.ip_wan,
                                          logs=tcpdump_logs,
                                          sudo=True,
                                          username=self.server.username,
                                          key_filename=self.server.key_filename)
        elif host == 'client':
            start_tcpdump_cmd = start_tcpdump_cmd.format(self.client.ifname_remote,
                                                         self.logs['client_tcpdump_log'])
            tcpdump_logs = [self.logs['client_tcpdump_log']]
            start_tcpdump = RemoteCommand(start_tcpdump_cmd,
                                          self.client.ip_wan,
                                          logs=tcpdump_logs,
                                          sudo=True,
                                          username=self.client.username,
                                          key_filename=self.client.key_filename)
        else:
            raise ValueError('Expected either server or client to host')
        return stack.enter_context(start_tcpdump())

    def _run_tcpprobe(self, stack):
        # assumes that tcp_bbr_measure is installed @ /opt/tcp_bbr_measure on iperf client
        insmod_cmd = ('sudo insmod '
                      '/opt/cctestbed/tcp_bbr_measure/tcp_probe_ray.ko port=0 full=1 '
                      '&& sudo chmod 444 /proc/net/tcpprobe ')
        with get_ssh_client(self.client.ip_wan,
                            username=self.client.username,
                            key_filename=self.client.key_filename) as ssh_client:
            logging.info('Running cmd ({}): {}'.format(self.client.ip_wan,
                                                       insmod_cmd))
            _, stdout, stderr = ssh_client.exec_command(insmod_cmd)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                raise RuntimeError(
                    'Got a non-zero exit status running cmd: {}.\n{}'.format(
                        insmod_cmd, stderr.read()))
            
        try:
            start_tcpprobe_cmd = 'cat /proc/net/tcpprobe'
            start_tcpprobe = RemoteCommand(start_tcpprobe_cmd,
                                           self.client.ip_wan,
                                           stdout = self.logs['tcpprobe_log'],
                                           stderr = self.logs['tcpprobe_log'],
                                           logs=[self.logs['tcpprobe_log']],
                                           cleanup_cmd='sudo rmmod tcp_probe_ray',
                                           username=self.client.username,
                                           key_filename=self.client.key_filename)
        except:
            # need to still rmmod if we can't create the remote command
            # for some reason
            with get_ssh_client(self.client.ip_wan,
                                username=self.client.username,
                                key_filename=self.client.key_filename) as ssh_client:
                ssh_client.exec_command('sudo rmmod tcp_probe_ray')
        return stack.enter_context(start_tcpprobe())

    @contextmanager
    def _run_bess_monitor(self):
        # have to use system here; subprocess just hangs for some reason
        with open(self.logs['queue_log'], 'w') as f:
            f.write('dequeued,time,src,seq,datalen,size,dropped,queued,batch\n')
        # only log "good" lines, those that start with 0 or 1
        #cmd = 'tail -n1 -f /tmp/bessd.INFO | grep -e "^0" -e "^1" >> {} &'.format(self.logs['queue_log'])
        cmd = 'tail -n1 -f /tmp/bessd.INFO > {} &'.format(self.logs['queue_log'])
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
            run_local_command('grep -e "^0" -e "^1" {} > /tmp/queue-log-tmp.txt'.format(self.logs['queue_log']), shell=True)
            run_local_command('mv /tmp/queue-log-tmp.txt {}'.format(self.logs['queue_log']))
            run_local_command('kill {}'.format(pid))

    @contextmanager
    def _run_bess(self):
        self.write_description_log()
        stderr = None
        try:
            start_bess(self)
            # give bess some time to start
            time.sleep(3)
            # check that i can ping between machines
            cmd = ('ping -c 4 -I {} {} '
               '| tail -1 '
               '| awk "{{print $4}}" ').format(self.server.ip_lan,
                                               self.client.ip_lan)
            with get_ssh_client(self.server.ip_wan,
                                username=self.server.username, 
                                key_filename=self.server.key_filename) as ssh_client:
                logging.info('Running cmd ({}): {}'.format(self.server.ip_wan,
                                                           cmd))
                _, stdout, stderr = ssh_client.exec_command(cmd)
                line = stdout.readline()
                stderr = stderr.read()
                # parse out avg rtt from last line of ping output
                avg_rtt = float(line.split('=')[-1].split('/')[1])
                logging.info('Got an avg rtt of {}'.format(avg_rtt))
                if not (avg_rtt > 0):
                    raise RuntimeError('Did not see an avg_rtt greater than 0.')
        except Exception as e:
            raise RuntimeError('Encountered error when trying to start BESS\n{}'.format(stderr), e)
        finally:
            # this try, finally might be overkill
            try:
                yield
            finally:
                stop_bess()

    def _run_all_flows(self, stack):
        # get wait times for each flow
        wait_times = self.get_wait_times()
        # run bess and monitor
        stack.enter_context(self._run_bess())
        # give bess some time to start
        time.sleep(3)
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
                                         username=self.server.username,
                                         logs=[flow.server_log],
                                         key_filename=self.server.key_filename)
            stack.enter_context(start_server())

        for idx, flow in enumerate(self.flows):
            # make sure first flow runs for the whole time regardless of start time
            # note this assumes self.flows is sorted by start time
            flow_duration = flow.end_time - flow.start_time
            if idx == 0:
                flow_duration = flow.end_time
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
                                                        flow_duration,
                                                        idx % 32,
                                                        flow.client_log)
            start_client = RemoteCommand(start_client_cmd,
                                         self.client.ip_wan,
                                         username=self.client.username,
                                         logs=[flow.client_log],
                                         key_filename=self.client.key_filename)
            
            logging.info('Sleep for {}s before starting flow with start time {}'.format(
                    wait_times[idx], flow.start_time))
            time.sleep(wait_times[idx])
            stack.enter_context(start_client())
        # last flow should be the last one
        sleep_time = flow.end_time - flow.start_time + 1
        logging.info('Sleep for {}s'.format(sleep_time))
        time.sleep(sleep_time) 
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

def load_experiments(config, config_filename, random_seed=None, experiment_names=None, force=False):
    """Create experiments from config file and output to config"""
    client = Host(**config['client'])
    server = Host(**config['server'])
    experiments = OrderedDict()
    def is_completed_experiment(experiment_name, force):
        num_completed = glob.glob('/tmp/{}-*.tar.gz'.format(experiment_name))
        experiment_done = len(num_completed) > 0
        if experiment_done:
            if force:
                logging.warning(
                    'Re-running completed experiment: {}'.format(experiment_name))
                return False
            else:
                logging.warning(
                    'Skipping completed experiment: {}'.format(experiment_name))
        return experiment_done
            
    experiments_to_run = []
    for experiment_name, experiment in config['experiments'].items():
        if experiment_names is None:
            if not is_completed_experiment(experiment_name, force):
                experiments_to_run.append((experiment_name, experiment))
        elif experiment_name in experiment_names:
            if not is_completed_experiment(experiment_name, force):
                experiments_to_run.append((experiment_name, experiment))

    for experiment_name, experiment in experiments_to_run:
        flows = []
        server_port = 5201
        client_port = 5555
        for flow in experiment['flows']:
            if random_seed is not None:
                flow['start_time'] = random.randint(0,10)
            assert(flow['start_time'] < flow['end_time'])
            flows.append(Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                              end_time=flow['end_time'], rtt=int(flow['rtt']),
                              server_port=server_port, client_port=client_port,
                              client_log=None, server_log=None))
            server_port += 1
            client_port += 1
        # sort flows according to their start times so they can be run in order
        flows.sort(key=lambda x: x.start_time)
        exp = Experiment(name=experiment_name,
                         btlbw=int(experiment['btlbw']),
                         queue_size=int(experiment['queue_size']),
                         flows=flows, server=server, client=client,
                         config_filename=config_filename)
        assert(experiment_name not in experiments)
        experiments[experiment_name] = exp
        exp.write_description_log()
        # save experiment to json file
        #with open(exp.logs['description_log'], 'w') as f:
        #    json.dump(exp.__dict__, f)
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
    cmd = '/opt/bess/bin/dpdk-devbind.py --status | grep drv={}'.format('dpdk_driver')
    proc = subprocess.run(cmd, check=False, shell=True, stdout=subprocess.PIPE)
    if proc.returncode == 0:
        logging.info('Interfaces already connected to DPDK')
        return server.pci, client.pci

    # make sure we can ssh into jicama from taro (ASSUMES POTATO IS CLIENT)
    if server.ifname_local == 'enp11s0f0' or server.ifname_local == 'enp11s0f0':
        check_cmd = 'route | grep 192.0.0.1'
        proc = subprocess.run(check_cmd, check=False, shell=True, stdout=subprocess.PIPE)
        if proc.returncode != 0:
            route_cmd = 'sudo ip route add 192.0.0.1 dev ens3f0'
            subprocess.run(route_cmd, check=True, shell=True, stdout=subprocess.PIPE)
            subprocess.run(check_cmd, check=True, shell=True, stdout=subprocess.PIPE)
    
    # get pcis
    expected_server_pci = get_interface_pci(server.ifname_local)
    expected_client_pci = get_interface_pci(client.ifname_local)
    if expected_server_pci is None or expected_server_pci.strip()=='':
        return server.pci, client.pci
    assert(expected_server_pci == server.pci)
    assert(expected_client_pci == client.pci)

    # get ips on this machine
    server_if_ip, server_ip_mask = get_interface_ip(server.ifname_local)
    client_if_ip, client_ip_mask = get_interface_ip(client.ifname_local)

    logging.info('Server: ifname = {}, '
                 'pci = {}, if_ip = {}/{}'.format(
                     server.ifname_local, server.pci, server_if_ip, server_ip_mask))
    logging.info('Client: ifname = {}, '
                 'pci = {}, if_ip = {}/{}'.format(
                     client.ifname_local, client.pci, client_if_ip, client_ip_mask))

    # make sure hugepages is started
    cmd = 'sudo sysctl vm.nr_hugepages=1024'
    run_local_command(cmd)

    # connect NIC interfaces to DPDK
    if dpdk_driver == 'igb_uio':
        cmd = 'sudo modprobe uio'
        run_local_command(cmd)
        cmd = 'sudo insmod /opt/bess/deps/dpdk-17.11/build/kmod/igb_uio.ko'
        run_local_command(cmd)
    else:
        cmd = 'sudo modprobe {}'.format(dpdk_driver)
        run_local_command(cmd)
    cmd = 'sudo ifconfig {} down'
    run_local_command(cmd.format(server.ifname_local))
    run_local_command(cmd.format(client.ifname_local))
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

def main(args):
    config = load_config_file(args.config_file)
    experiment_names = args.names
    logging.info('Going to repeat experiments {} times'.format(args.repeat))
    completed_experiment_procs = []
    for num_repeat in range(args.repeat):
        logging.info('REPTITION {}: '.format(num_repeat))
        experiments = load_experiments(config, args.config_file,
                                       experiment_names=experiment_names,
                                       force=args.force,
                                       random_seed=args.seed)
        logging.info('Going to run {} experiments'.format(len(experiments)))
        for experiment in experiments.values():
            proc = experiment.run()
            completed_experiment_procs.append(proc)
        
        args.force = True  # need to force future repetitions of experiments
    for proc in completed_experiment_procs:
        logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
        proc.wait()
        if proc.returncode !=0:
            logging.warning('Error running cmd PID={}'.format(proc.pid))
        

def parse_args():
    """Parse commandline arguments"""
    parser = argparse.ArgumentParser(description='Run congestion control experiments')
    parser.add_argument('config_file', help='Configuration file describing experiment')
    parser.add_argument('--names', '-n', nargs='+', help='Name(s) of experiments to run')
    parser.add_argument('--force', '-f', action='store_true', help='Force experiments that were already run to run again')
    parser.add_argument('--randomize', dest='seed', type=int,
                        help='Randomize flow start time between 0 & 10 seconds with given random seed')
    parser.add_argument('--repeat', type=int, default=1, help='Repeat experiments some number of times')
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    return args

if __name__ == '__main__':
    fileConfig('logging_config.ini')
    args = parse_args()
    main(args)
