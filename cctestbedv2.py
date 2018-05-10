from collections import namedtuple
from datetime import datetime
from contextlib import contextmanager
from logging.config import fileConfig
from json import JSONEncoder
import argparse
import json
import os
import time
import logging
import yaml
import paramiko

fileConfig('logging_config.ini')

Host = namedtuple('Host', ['ifname', 'ip_wan', 'ip_lan', 'pci'])
Flow = namedtuple('Flow', ['ccalg', 'start_time', 'end_time', 'rtt',
                           'server_port', 'client_port', 'client_log', 'server_log'])    

class RemoteCommand:
    """Command to run on a remote machine in the background"""
    def __init__(self, cmd, ip_addr,
                 stdout='/dev/null', stdin='/dev/null', stderr='/dev/null', logs=[],
                 username='ranysha'):
        self.cmd = cmd
        self.ip_addr = ip_addr
        self.stdout = stdout
        self.stdin = stdin
        self.stderr = stderr
        self.logs = logs
        self.username = username
        self._ssh_client = None
        self._ssh_channel = None

    def _get_ssh_client(self):
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(self.ip_addr, username=self.username)
        return ssh_client
        
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
            self._ssh_channel.exec_command('{} > {} 2> {} < {} &'.format(self.cmd,
                                                                         self.stdout,
                                                                         self.stderr,
                                                                         self.stdin))
            ssh_client = self._get_ssh_client()
            _, stdout, _ = ssh_client.exec_command('pgrep -f "{}"'.format(self.cmd.strip()))
            pid = stdout.readline().strip()
            assert(pid)
            logging.info('Running cmd ({}): {}. \nPID={}'.format(self.ip_addr, self.cmd, pid))
            # check if immediately get nonzero exit status
            if self._ssh_channel.exit_status_ready():
                if self._ssh_channel.recv_exit_status() != 0:
                    raise RuntimeError(
                        'Got a non-zero exit status running cmd: {}.\n{}'.format(
                            self.cmd, stderr.read()))
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
            ssh_client.exec_command('kill {}'.format(pid))
            ssh_client.close()
            for log in self.logs:
                ssh_client = self._get_ssh_client()
                try:
                    sftp_client = ssh_client.open_sftp()
                    sftp_client.get(log, os.path.join('/tmp',log))
                    ssh_client.exec_command('rm {}'.format(log))
                except FileNotFoundError as e:
                    logging.warning('Could not find file "{}" on remote server "{}"'.format(
                        log, self.ip_addr))
                sftp_client.close()
                ssh_client.close()
                
    def __str__(self):
        return {'ip_addr': self.ip_addr, 'cmd': self.cmd,
                'logs': self.logs, 'username': self.username}

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
                                            self.server_log)
                start_server = RemoteCommand(start_server_cmd,
                                             self.server_ip_addr,
                                             logs=[self.server_log])
                stack.enter_context(start_server())
                time.sleep(5)

        
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
    """Create experiments from config file"""
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
            flows.append(Flow(ccalg=flow['ccalg'], start_time=flow['start_time'],
                              end_time=flow['end_time'], rtt=flow['rtt'],
                              server_port=server_port, client_port=client_port,
                              client_log=None, server_log=None))
            server_port += 1
            client_port += 1
        # sort flows according to their start times so they can be run in order
        flows.sort(key=lambda x: x.start_time)
        exp = Experiment(name=experiment_name, btlbw=experiment['btlbw'],
                         queue_size=experiment['queue_size'],
                         flows=flows, server=server, client=client)
        assert(experiment_name not in experiments)
        experiments[experiment_name] = Experiment(name=experiment_name,
                                                  btlbw=experiment['btlbw'],
                                                  queue_size=experiment['queue_size'],
                                                  flows=flows, server=server, client=client)
    return experiments
    
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
