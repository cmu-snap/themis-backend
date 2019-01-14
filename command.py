import time
import subprocess
import paramiko
import logging
import shlex
from contextlib import closing, contextmanager, ExitStack
import os

from logging.config import fileConfig
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logging_config.ini')
fileConfig(log_file_path)    

class RemoteCommand:
    """Command to run on a remote machine in the background"""
    def __init__(self, cmd, ip_addr, username,
                 stdout='/dev/null', stdin='/dev/null', stderr='/dev/null', logs=[],
                 cleanup_cmd=None, sudo=False, key_filename=None, pgrep_string=None):
        self.cmd = cmd.strip()
        self.ip_addr = ip_addr
        self.stdout = stdout
        self.stdin = stdin
        self.stderr = stderr
        self.logs = logs
        self.cleanup_cmd = cleanup_cmd
        self.sudo = sudo
        self.username = username
        self.key_filename = key_filename
        self.exit_stack = ExitStack()
        self.pgrep_string = pgrep_string
        self.pid = None
        
    def _get_ssh_client(self):
        return get_ssh_client(self.ip_addr, self.username, self.key_filename)

    def _get_ssh_channel(self, ssh_client):
        return ssh_client.get_transport().open_session()
        
    def _is_running(self):
        with ExitStack() as stack:
            ssh_client = stack.enter_context(self._get_ssh_client())
            _, stdout, _ = ssh_client.exec_command('ps -p "{}"'.format(self.pid))
            stack.callback(stdout.close)
            exit_code = stdout.channel.recv_exit_status()
        return exit_code == 0
        
        
    def _wait(self):
        while self._is_running():
            time.sleep(1)
            
    def _get_pid(self, cmd):
        with ExitStack() as stack:
            ssh_client = stack.enter_context(self._get_ssh_client())
            logging.info('Running cmd ({}): {}'.format(self.ip_addr, cmd))
            if self.pgrep_string is None:
                self.pgrep_string = '^'+self.cmd
            logging.info('Looking up pid: pgrep -nf "{}"'.format(self.pgrep_string))
            _, stdout, _ = ssh_client.exec_command('pgrep -nf "{}"'.format(self.pgrep_string))
            stack.callback(stdout.close)
            pid = stdout.readline().strip()
            logging.info('PID={}'.format(pid))
        self.pid = pid
        return pid

    def _cleanup_cmd(self, pid):
        logging.info('Cleaning up cmd ({}): {}'.format(self.ip_addr, self.cmd))
        # on cleanup kill process & collect all logs
        with self._get_ssh_client() as ssh_client:
            kill_cmd = 'kill -9 {}'.format(pid)
            if self.sudo:
                kill_cmd = 'sudo kill -9 {}'.format(pid)
            exec_command(ssh_client, self.ip_addr, kill_cmd)
        if self.cleanup_cmd is not None:
            # TODO: run cleanup cmd as sudo too?
            with self._get_ssh_client() as ssh_client:
                exec_command(ssh_client, self.ip_addr, self.cleanup_cmd)
                # cleanup logs
        self._cleanup_logs()
        logging.info('Done cleaning up cmd ({}): {}'.format(self.ip_addr, self.cmd))
            
    def _cleanup_logs(self):
        with ExitStack() as stack:
            scp_procs = []
            for log in self.logs:
                logging.info('Copying remote file ({}): {}'.format(self.ip_addr,
                                                                   log))
                if self.key_filename is None:
                    cmd = 'scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {}@{}:{} /tmp/'.format(self.username, self.ip_addr,
                                                os.path.join('/tmp', log))
                else:
                    cmd = 'scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {} {}@{}:{} /tmp/'.format(self.key_filename, self.username,
                                                      self.ip_addr,
                                                      os.path.join('/tmp',log))
                logging.info('Starting local cmd: {}'.format(cmd))
                proc = subprocess.Popen(shlex.split(cmd),
                                        stdout = subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
                stack.callback(proc.kill) # should always kill process if there is an error
                scp_procs.append(proc)

            for proc in scp_procs:
                logging.info('Waiting for remote file to finish copying: {}'.format(proc.args[-1]))
                # NOTE: NO TIMEOUT SO THIS COULD HANG FOREVER
                proc.wait() 
                if proc.returncode != 0:
                    logging.warning('Could not find file "{}" on remote server "{}"'.format(log, self.ip_addr))
                    logging.warning(proc.stderr.read())
                else:
                    logging.info('Remove remote file ({}): {}'.format(self.ip_addr,
                                                                      log))
                    with self._get_ssh_client() as ssh_client:
                        rm_cmd = 'rm {}'.format(log)
                        if self.sudo:
                            rm_cmd = 'sudo rm {}'.format(log)
                        exec_command(ssh_client, self.ip_addr, rm_cmd)
    
    @contextmanager
    def __call__(self):
        try:
            cmd_ssh_client = self.exit_stack.enter_context(self._get_ssh_client())
            cmd_ssh_channel = self._get_ssh_channel(cmd_ssh_client)
            self.exit_stack.callback(cmd_ssh_channel.close)
            pid = None
            if self.sudo:
                cmd = 'sudo {}'.format(self.cmd)
            else:
                cmd = self.cmd
            with closing(cmd_ssh_channel.makefile_stderr()) as cmd_stderr:
                cmd_ssh_channel.exec_command('{} > {} 2> {} < {} &'.format(cmd,
                                                                           self.stdout,
                                                                           self.stderr,
                                                                           self.stdin))
                # check if immediately got nonzero exit status
                if cmd_ssh_channel.exit_status_ready():
                    if cmd_ssh_channel.recv_exit_status() != 0:
                        raise RuntimeError(
                            'Got a non-zero exit status running cmd: {}.\n{}'.format(
                                self.cmd, cmd_stderr.read()))
                
                # get PID
                pid = self._get_pid(cmd)
                if pid=='':
                    logging.error('Could not get PID after running cmd: {}.\n'.format(
                        self.cmd, cmd_stderr.read()))
                    # retry getting PID
                    time.sleep(5)
                    pid = self._get_pid(cmd)
                    if pid == '':
                        logging.error(
                            'Could not get PID after running cmd: {}.\n'.format(
                            self.cmd, cmd_stderr.read()))
                        raise RuntimeError(
                            'Could not get PID after running cmd: {}'.format(self.cmd))
            pid = int(pid)
            self.exit_stack.callback(self._cleanup_cmd, pid)
            yield pid
        finally:
            self.exit_stack.close()
            
    def __str__(self):
        return {'ip_addr': self.ip_addr, 'cmd': self.cmd, 'sudo': self.sudo, 'key_filename': self.key_filename,
                'logs': self.logs, 'username': self.username, 'cleanup_cmd':self.cleanup_cmd}

    def __repr__(self):
        return 'RemoteCommand({})'.format(self.__str__())

def run_local_command(cmd, shell=False, timeout=None, check=False):
    """Run local command return stdout"""
    logging.info('Running cmd: {}'.format(cmd))
    if shell:
        proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, timeout=timeout,
                              check=check)
    else:
        proc = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE,
                              timeout=timeout, check=check)
    return proc.stdout.decode('utf-8')

@contextmanager
def get_ssh_client(ip_addr, username, key_filename=None):
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(ip_addr, username=username, key_filename=key_filename,
                           banner_timeout=60, auth_timeout=60, timeout=60)
        yield ssh_client
    finally:
        ssh_client.close()

def exec_command(ssh_client, ip_addr, cmd):
    logging.info('Running cmd ({}): {}'.format(ip_addr, cmd))
    return ssh_client.exec_command(cmd, timeout=60)

