import command as mut
from tests.conftest import is_remote_process_running
import paramiko
import os
import psutil
import pytest
import time

@pytest.mark.timeout(60)
def test_remote_command(experiment):
    this_proc = psutil.Process()
    assert(len(this_proc.connections())==0)
    start_server_cmd = ('iperf3 --server '
                        '--bind {} '
                        '--port {} '
                        '--one-off '
                        '--affinity {} '
                        '--logfile {} ').format(
                            experiment.server.ip_lan,
                            experiment.flows[0].server_port,
                            1,
                            experiment.flows[0].server_log)
    start_server = mut.RemoteCommand(start_server_cmd,
                                     experiment.server.ip_wan,
                                     logs=[experiment.flows[0].server_log],
                                     username='ranysha',
                                     key_filename=None)
    with start_server() as pid:
        assert(is_remote_process_running(experiment.server.ip_wan, pid))
        assert(len(this_proc.connections()) > 0)
        time.sleep(5)
    time.sleep(1)
    assert(not is_remote_process_running(experiment.server.ip_wan, pid))
    assert(os.path.isfile(experiment.flows[0].server_log))
    os.remove(experiment.flows[0].server_log)
    assert(len(this_proc.open_files()) == 0)
    assert(len(this_proc.connections()) == 0)

def test_remote_command_failure(experiment):
    this_proc = psutil.Process()
    assert(len(this_proc.connections())==0)
    start_server_cmd = ('iperf3 --server '
                        '--bind {} '
                        '--port {} '
                        '--one-off '
                        '--affinity {} '
                        '--logfile {} ').format(
                            experiment.server.ip_lan,
                            experiment.flows[0].server_port,
                            1,
                            experiment.flows[0].server_log)
    start_server = mut.RemoteCommand(start_server_cmd,
                                     experiment.server.ip_wan,
                                     logs=[experiment.flows[0].server_log],
                                     username='ranysha',
                                     key_filename=None)
    with pytest.raises(RuntimeError, message='test'):
        with start_server() as pid:
            time.sleep(5)
            raise RuntimeError('test')
    time.sleep(1)
    assert(not is_remote_process_running(experiment.server.ip_wan, pid))
    assert(os.path.isfile(experiment.flows[0].server_log))
    os.remove(experiment.flows[0].server_log)
    assert(len(this_proc.open_files()) == 0)
    assert(len(this_proc.connections()) == 0)
