import sys
sys.path.append('../')

from cctestbedv2 import Flow, Host, get_ssh_client, run_local_command

import os
import tarfile
import json
import pandas as pd
from collections import Counter
from contextlib import contextmanager
import subprocess
import re
import glob
import multiprocessing as mp
import itertools as it
import numpy as np
import datetime as dt

CODEPATH = '/home/ranysha/cctestbed'
DATAPATH_RAW = '/home/ranysha/cctestbed/data-raw'
DATAPATH_PROCESSED = '/home/ranysha/cctestbed/data-processed'
BYTES_TO_BITS = 8
BITS_TO_MEGABITS = 1.0 / 1000000.0
REMOTE_IP_ADDR = '128.2.208.131'
REMOTE_USERNAME = 'ranysha'

class Experiment:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            # special handling for creating Flow and Host objects
            if key == 'flows':
                for flow in value:
                    # convert log paths to paths in tarfile
                    flow[-1] = os.path.basename(flow[-1])
                    flow[-2] = os.path.basename(flow[-2])
                setattr(self, key, [Flow(*flow) for flow in value])
            elif key == 'server' or key == 'client':
                setattr(self, key, Host(*value))
            # convert log paths to path in tarfile
            elif key == 'logs':
                setattr(self, key,  {log:os.path.basename(logname) for log, logname in value.items()})
            else:
                setattr(self, key, value)

    def __repr__(self):
        attrs = self.__str__()
        return 'Experiment({})'.format(attrs)

    def __str__(self):
        attrs = json.dumps(self.__dict__,
                           sort_keys=True,
                           indent=4)
        return attrs

    def __eq__(self, other):
        return self.name.__eq__(other.name)

    def __lt__(self, other):
        return self.name.__lt__(other.name)

    def __le__(self, other):
        return self.name.__le__(other.name)

    def __gt__(self, other):
        return self.name.__gt__(other.name)

    def __ge__(self, other):
        return self.name.__ge__(other.name)

    def __ne__(self, other):
        return self.name.__ne__(other.name)

"""
Each experiment has it's own experiment analyzer

Lazily populate dataframes for queue, tcpprobe
"""
class ExperimentAnalyzer:
    def __init__(self, experiment, load_queue=False):
        self.experiment = experiment
        self._df_queue = None
        self._df_tcpprobe = None
        self._df_tcpdump_client = None
        self._df_tcpdump_server = None
        self._flow_sender_ports = None
        self._flow_names = None
         # path to HDF5 store of queue; lazily poulated after hdf_queue_path called
        self._hdf_queue_path = None

        if load_queue:
            try:
                with self.hdf_queue() as _: #None
                    pass
            except Exception as e:
                print('Error creating hdf queue for experiment: {}\n {}'.format(experiment.name, e))

    def _create_hdf_queue(self, raw_queue_log_tarpath, raw_queue_log_localpath, processed_queue_log_localpath):
        # haven't created HDF5 store yet; create it now
        find_bad_lines_cmd = 'grep ^.*,.*,.*,.*,.*,.*,.*,.*,.*$ {} -v -n'.format(raw_queue_log_localpath)
        badlines = run_local_command(find_bad_lines_cmd, shell=False).split('\n')
        if len(badlines) >= 1 and badlines[0] != '':
            sort_cmd = 'sort -k 2 -o {} {}'.format(raw_queue_log_localpath, raw_queue_log_localpath)
            print('Found {} bad lines:\n {}'.format(len(badlines), badlines))
        else:
            tmp_queue_filename = raw_queue_log_localpath + '.tmp'
            sort_cmd = 'sort -k 2 -o {} {} && grep ^.*,.*,.*,.*,.*,.*,.*,.*,.*$ {} > {} && mv {} {} '.format(
                        raw_queue_log_localpath, raw_queue_log_localpath, raw_queue_log_localpath, tmp_queue_filename, tmp_queue_filename, raw_queue_log_localpath)

        with untarfile(self.experiment.tarfile_localpath, raw_queue_log_tarpath, postprocess_cmd=sort_cmd) as f:
            with pd.HDFStore(processed_queue_log_localpath, mode='w') as store:
                df = pd.read_csv(f, names = ['dequeued',
                                                'time',
                                                'src',
                                                'seq',
                                                'datalen',
                                                'size',
                                                'dropped',
                                                'queued',
                                                'batch'],
                                    converters = {'seq': tohex,
                                                'src': tohex},
                                    dtype={'dequeued': bool,
                                        'time': np.uint64,
                                        'datalen': np.uint16,
                                        'size': np.uint32,
                                        'dropped':bool,
                                        'queued': np.uint16,
                                        'batch': np.uint16}, skip_blank_lines=True)
                df['seq'] = df['seq'].astype( np.uint32)
                df['src'] = df['src'].astype( np.uint16)
                #chunk['time'] = pd.to_datetime(chunk['time'], infer_datetime_format=True, unit='ns')
                df['lineno'] = df.index + 1
                df = df.set_index('time')
                df_enq = (pd
                        .get_dummies(df[(df.dequeued==0) & (df.dropped==0)]['src'])
                        .astype(np.uint8))
                df_deq = (pd
                        .get_dummies(df[df.dequeued==1]['src'])
                        .replace(1,-1)
                        .astype(np.int8))
                df_flows = (df_enq
                            .append(df_deq)
                            .sort_index()
                            .cumsum()
                            .fillna(0)
                            .astype(np.uint32))
                df = (df
                    .reset_index()
                    .join(df_flows.reset_index().drop('time', axis=1))
                    .sort_index()
                    .ffill())
                df.time = pd.to_datetime(df.time,
                                        infer_datetime_format=True,
                                        unit='ns')
                df = df.set_index('time')
                store.append('df_queue',
                            df,
                            format='table',
                            data_columns=['src', 'dropped', 'dequeued'])

    @contextmanager
    def hdf_queue(self, mode='r'):
        if (self._hdf_queue_path is None) or (not os.path.isfile(self._hdf_queue_path)):
            raw_queue_log_tarpath = self.experiment.logs['queue_log']
            raw_queue_log_localpath = os.path.join(DATAPATH_RAW, raw_queue_log_tarpath)
            processed_queue_log_localpath =  os.path.join(DATAPATH_PROCESSED,
                                                    '{}.h5'.format(os.path.join(
                                                    raw_queue_log_tarpath[:-len('.txt')])))
            if not os.path.isfile(processed_queue_log_localpath):
                print('Creating HDF store for queue')
                self._create_hdf_queue(raw_queue_log_tarpath, raw_queue_log_localpath, processed_queue_log_localpath)
            self._hdf_queue_path = processed_queue_log_localpath
        store = pd.HDFStore(self._hdf_queue_path, mode=mode)
        try:
            yield store
        finally:
            store.close()

    """
    @property
    def df_queue(self):
        raise NotImplementedError
        queue_log_tarpath = self.experiment.logs['queue_log']
        queue_log_localpath = os.path.join(DATAPATH_PROCESSED,
                                            '{}.csv'.format(os.path.join(queue_log_tarpath[:-len('.txt')])))
        if (self._df_queue is None) or (not os.path.isfile(queue_log_localpath)):
            # cleanup data and store processed data
            if not os.path.isfile(queue_log_localpath):
                if not os.path.isfile(os.path.join(DATAPATH_RAW, queue_log_tarpath)):
                    with untarfile(self.experiment.tarfile_localpath, queue_log_tarpath) as f:
                        # remove header=0, since there is no header
                        #df = pd.read_csv(f, skipinitialspace=True,
                        #        names=['dequeued', 'time', 'src', 'seq', 'datalen',
                        #                'size', 'dropped', 'queued', 'batch'])
                        df = pd.read_csv(f, names = ['dequeued',
                                                    'time',
                                                    'src',
                                                    'seq',
                                                    'datalen',
                                                    'size',
                                                    'dropped',
                                                    'queued',
                                                    'batch'],
                                        converters = {'seq': lambda x: int(x, 16) ,
                                                    'src': lambda x: int(x, 16)},
                                        dtype={'dequeued': bool,
                                            'time':np.uint64,
                                            'datalen':np.uint16,
                                            'size':np.uint32,
                                            'dropped':bool,
                                            'queued': np.uint16,
                                            'batch':np.uint16})
                else:
                    with open(os.path.join(DATAPATH_RAW, queue_log_tarpath)) as f:
                        df = pd.read_csv(f, skipinitialspace=True,
                                names=['dequeued', 'time', 'src', 'seq', 'datalen',
                                        'size', 'dropped', 'queued', 'batch'])
                df['lineno'] = df.index + 1 # save old index as lineno
                bad_lines = df[df.isna().any(1)]
                if not bad_lines.empty:
                    bad_lines = bad_lines['lineno'].tolist()
                    print('Dropping {} bad lines: {}'.format(len(bad_lines), bad_lines))
                    df = df.dropna(axis='rows', how='any')
                # add time as index
                df['time'] = pd.to_datetime(df['time'], infer_datetime_format=True, unit='ns')
                df = df.set_index('time').sort_index()
                # change src from hex to a number
                df['src'] = df['src'].apply(lambda x: str(int(x,16)))
                # add per flow queue occupancy
                df_enq = pd.get_dummies(df[(df.dequeued==0) & (df.dropped==0)]['src']).astype('int8')
                df_deq = pd.get_dummies(df[df.dequeued==1]['src']).astype('int8').replace(1,-1)
                df_flows = df_enq.append(df_deq).sort_index().cumsum()
                df = df.join(df_flows).sort_index().ffill()
                # IF THERE'S AN ERROR HERE, PROBABLY MESSED UP LINE IN DF QUEUE DATA
                #rename_src_ports = {src_hex:int(str(src_hex), 16) for src_hex in df.src.unique()}
                #df = df.rename(columns = rename_src_ports)
                df.to_csv(queue_log_localpath, header=True)
                self._df_queue = df
            else:
                with open(queue_log_localpath) as f:
                    df = pd.read_csv(f, header=0,
                                     skipinitialspace=True, index_col='time')
                    df.index = pd.to_datetime(df.index)
                    df['src'] = df['src'].astype('str')
                    self._df_queue = df

        return self._df_queue
    """

    @property
    def flow_sender_ports(self):
        if self._flow_sender_ports is None:
            self._flow_sender_ports = {flow.client_port:flow.ccalg
                                        for flow in self.experiment.flows}
        return self._flow_sender_ports

    @property
    def flow_names(self):
        if self._flow_names is None:
            # flow names will be cubic, cubic-2, cubic-3 if there are more
            # than one flow with the same ccalg name
            flow_ccalgs = ['{}-{}'.format(port, ccalg) for port, ccalg in self.flow_sender_ports.items()]
            flow_ccalgs = sorted(flow_ccalgs)

            flow_names = {}
            seen_ccalgs_counter = Counter()
            for flow_ccalg in flow_ccalgs:
                port, ccalg = flow_ccalg.split('-')
                seen_ccalgs_counter[ccalg] += 1
                if seen_ccalgs_counter[ccalg] > 1:
                    flow_names[int(port)] = '{}-{}'.format(ccalg, seen_ccalgs_counter[ccalg])
                else:
                    flow_names[int(port)] = ccalg
            self._flow_names = flow_names
        return self._flow_names

    @property
    def df_tcpprobe(self):
        MICROSECONDS_TO_MILLISECONDS = 1.0 / 1000
        tcpprobe_log_tarpath = self.experiment.logs['tcpprobe_log']
        tcpprobe_log_localpath = os.path.join(DATAPATH_PROCESSED,
                                            '{}.csv'.format(os.path.join(tcpprobe_log_tarpath[:-len('.txt')])))
        if (self._df_tcpprobe is None) or (not os.path.isfile(tcpprobe_log_localpath)):
            if not os.path.isfile(tcpprobe_log_localpath):
                with untarfile(self.experiment.tarfile_localpath, tcpprobe_log_tarpath) as f:
                    tcpprobe = pd.read_csv(f, sep='\s+', header=None,
                                names=['time','sender','receiver','bytes','next',
                                        'unack','cwnd','ssthresh','swnd','srtt',
                                        'rwnd', 'bbr_bw_lo','bbr_bw_hi','bbr_min_rtt',
                                        'bbr_pacing_gain','bbr_cwnd_gain'])

                    tcpprobe['bbr_bw_lo'] = (tcpprobe['bbr_bw_lo']*715) / 1e6
                    tcpprobe['bbr_pacing_gain'] = tcpprobe['bbr_pacing_gain'] / 256
                    tcpprobe['bbr_cwnd_gain'] = tcpprobe['bbr_cwnd_gain'] / 256
                    tcpprobe['bbr_min_rtt'] = tcpprobe['bbr_min_rtt'] * MICROSECONDS_TO_MILLISECONDS
                    tcpprobe['srtt'] = tcpprobe['srtt'] * MICROSECONDS_TO_MILLISECONDS
                    tcpprobe['time'] = tcpprobe['time'].apply(lambda x: dt.timedelta(seconds=x))
                    tcpprobe = tcpprobe.set_index('time')
                    senders = ['192.0.0.1:{}'.format(port) for port in  self.flow_sender_ports.keys()]
                    tcpprobe = tcpprobe[tcpprobe.sender.isin(senders)]
                    tcpprobe.to_csv(tcpprobe_log_localpath, header=True)
            else:
                with open(tcpprobe_log_localpath) as f:
                    tcpprobe = pd.read_csv(f, header=0, index_col = 'time')
                    tcpprobe.index = pd.to_datetime(tcpprobe.index)
            self._df_tcpprobe = tcpprobe
        return self._df_tcpprobe

    @property
    def df_tcpdump_client(self):
        tcpdump_client_tarpath = self.experiment.logs['client_tcpdump_log']
        tcpdump_client_processed_localpath = os.path.join(DATAPATH_PROCESSED, tcpdump_client_tarpath)[:-len('.pcap')] + '.csv'
        if (self._df_tcpdump_client is None) or (not os.path.isfile(tcpdump_client_processed_localpath)):
            if not(os.path.isfile(tcpdump_client_processed_localpath)):
                with open(tcpdump_client_processed_localpath, 'w') as f:
                    f.write('frame.time_relative,tcp.len,tcp.srcport,tcp.seq,tcp.analysis,ack_rtt\n')
                with untarfile_extract(self.experiment.tarfile_localpath, tcpdump_client_tarpath) as tcpdump_client_raw_localpath:
                    cmd = 'tshark -T fields -E separator=, -E quote=d -r {} -e frame.time_relative -e tcp.len -e tcp.srcport -e tcp.seq -e tcp.analysis.ack_rtt >> {}'.format(
                                            tcpdump_client_raw_localpath, tcpdump_client_processed_localpath)
                    proc = subprocess.run(cmd, shell=True, stderr=subprocess.PIPE)
                    if proc.returncode != 0:
                        raise RuntimeError('Encountered error running cmd {}\n{}'.format(cmd, proc.stderr.decode('utf-8')))
            with open(tcpdump_client_processed_localpath) as f:
                self._df_tcpdump_client = pd.read_csv(f, header=0, skipinitialspace=True)
        return self._df_tcpdump_client

    def get_total_goodput(self, interval=None):
        dequeued = self.df_queue[self.df_queue.dequeued==1]
        # total goodput
        if interval:
            dequeued.index = (dequeued.index - dequeued.index[0]).total_seconds()
            dequeued = dequeued[interval[0]:interval[1]]
            dequeued.index = dequeued.index - dequeued.index[0] # noramlize again
            goodput = (dequeued.groupby('src')['datalen'].sum() * BYTES_TO_BITS * BITS_TO_MEGABITS) / dequeued.index.max()
        else:
            goodput = (dequeued.groupby('src')['datalen'].sum() * BYTES_TO_BITS * BITS_TO_MEGABITS) / (dequeued.index.max() - dequeued.index.min()).total_seconds()
        goodput.index = goodput.index = goodput.index.astype('str')
        goodput = goodput.rename(self.flow_names)[list(self.flow_names.values())]
        # TODO: only get total goodput for a specific ccalg
        #goodput = goodput.rename(flows)[list(flows.values())]
        #goodput_describe = (transfer_size / transfer_time).describe().T
        return goodput

    def get_goodput(self, interval=None):
        #dequeued = self.df_queue[self.df_queue.dequeued==1]
        with self.hdf_queue() as hdf_queue:
            src_query = 'src=' + ' | src='.join(map(lambda x: str(5555+x),
                                                    range(len(self.experiment.flows))))
            dequeued = hdf_queue.select('df',
                                        where='dequeued=1 & ({})'.format(src_query),
                                        columns=['src', 'datalen'])

        df_queue_path = self.df_queue
        dequeued = pd.read_hdf(df_queue_path,'df', where='dequeued=1',
                               columns=['src', 'datalen'])
        # total goodput
        if interval:
            dequeued.index = (dequeued.index - dequeued.index[0]).total_seconds()
            dequeued = dequeued[interval[0]:interval[1]]
            dequeued.index = dequeued.index - dequeued.index[0] # noramlize again
            goodput = (dequeued.groupby('src')['datalen'].sum() * BYTES_TO_BITS * BITS_TO_MEGABITS) / dequeued.index.max()
        else:
            goodput = (dequeued.groupby('src')['datalen'].sum() * BYTES_TO_BITS * BITS_TO_MEGABITS) / (dequeued.index.max() - dequeued.index.min()).total_seconds()
        goodput.index = goodput.index = goodput.index.astype('str')
        goodput = goodput.rename(self.flow_names)[list(self.flow_names.values())]
        # TODO: only get total goodput for a specific ccalg
        #goodput = goodput.rename(flows)[list(flows.values())]
        #goodput_describe = (transfer_size / transfer_time).describe().T
        return goodput

    @property
    def df_tcpdump_server(self):
        raise NotImplementedError()

    def __repr__(self):
        attrs = self.__str__()
        return 'ExperimentAnalyzer({})'.format(attrs)

    def __str__(self):
        return str(self.experiment)

    def __eq__(self, other):
        return self.experiment.__eq__(other.experiment)

    def __lt__(self, other):
        return self.experiment.__lt__(other.experiment)

    def __le__(self, other):
        return self.experiment.__le__(other.experiment)

    def __gt__(self, other):
        return self.experiment.__gt__(other.experiment)

    def __ge__(self, other):
        return self.experiment.__ge__(other.experiment)

    def __ne__(self, other):
        return self.experiment.__ne__(other.experiment)

class ExperimentAnalyzers(dict):

    def get_matching_pool(self, pattern):
        """Return subset of ExperimentAnalyzers dict that match given
        regex pattern.
        """
        regex = re.compile(pattern)
        pool_chunksize = int(len(self) / mp.cpu_count()) + 1
        with mp.Pool() as pool:
            matching = pool.starmap(regex_match, zip(it.repeat(regex), self.keys()), chunksize=pool_chunksize)
        return {key:self[key] for key in matching if key is not None}

    def get_matching(self, pattern):
        # this one seems to actually be faster than get_matching_pool
        regex = re.compile(pattern)
        return {key:value for key,value in self.items() if regex.match(key)}

def regex_match(regex, key):
    if regex.match(key):
        return key
    else:
        return None

@contextmanager
def untarfile(tar_filename, filename, untar_dir=DATAPATH_RAW, delete_file=True, postprocess_cmd=None):
    file_localpath = os.path.join(untar_dir, filename)
    print('Extracting file {} from {} to {}'.format(filename, tar_filename, file_localpath))
    cmd = 'cd {} && tar -xzvf {} {}'.format(untar_dir,
                                            tar_filename,
                                            filename)
    # untar file
    try:
        completed_proc = subprocess.run(cmd, shell=True, check=False, stderr=subprocess.PIPE)
        completed_proc.check_returncode()
    except subprocess.CalledProcessError as e:
        print('STDERR:', completed_proc.stderr)
    # run postprocess cmd
    if postprocess_cmd is not None:
        try:
            print('Running postprocess cmd: {}'.format(postprocess_cmd))
            completed_proc = subprocess.run(postprocess_cmd, shell=True, check=False, stderr=subprocess.PIPE)
            completed_proc.check_returncode()
        except subprocess.CalledProcessError as e:
            print('STDERR:', completed_proc.stderr)
            raise e
    # open file and return open file
    try:
        f = open(file_localpath)
        yield f
    finally:
        # close file and delete when exiting context manager
        f.close()
        if delete_file:
            print('Deleting file {}'.format(file_localpath))
            os.remove(file_localpath)

@contextmanager
def untarfile_extract(tar_filename, filename, untar_dir=DATAPATH_RAW, delete_file=True, postprocess_cmd=None):
    file_localpath = os.path.join(untar_dir, filename)
    print('Extracting file {} from {} to {}'.format(filename, tar_filename, file_localpath))
    cmd = 'cd {} && tar -xzvf {} {}'.format(untar_dir,
                                            tar_filename,
                                            filename)
    # untar file
    try:
        completed_proc = subprocess.run(cmd, shell=True, check=False, stderr=subprocess.PIPE)
        completed_proc.check_returncode()
    except subprocess.CalledProcessError as e:
        print('STDERR:', completed_proc.stderr)
    # run postprocess cmd
    if postprocess_cmd is not None:
        try:
            print('Running postprocess cmd: {}'.format(postprocess_cmd))
            completed_proc = subprocess.run(postprocess_cmd, shell=True, check=False, stderr=subprocess.PIPE)
            completed_proc.check_returncode()
        except subprocess.CalledProcessError as e:
            print('STDERR:', completed_proc.stderr)
            raise e
    # return path to file
    try:
        yield file_localpath
    finally:
        # delete file when exiting context manager
        if delete_file:
            print('Deleting file {}'.format(file_localpath))
            os.remove(file_localpath)

def load_experiments(experiment_name_patterns, remote=True, force_local=False,
                        remote_username=REMOTE_USERNAME, remote_ip=REMOTE_IP_ADDR,
                        load_queue=False, clean=False):
    """Load all experiments into experiment analyzers
    experiment_name_pattern : list of str
        Should be a pattern that will be called
        with '{}.tar.gz'.format(experiment_name_pattern)
    remote : bool, (default: True)
        If True, look for experiments remotely.
        If False, don't look for experiments remotely,
        only locally.
    force_local : bool, (default: False)
        If True, always look for local experiments.
        If False, only look for local experiments,
        if no remote experiments are found.
    clean: bool
        If True, delete all local files matching this exp_name_pattern
        before downloading again.
    """
    assert(type(experiment_name_patterns) is list)
    tarfile_remotepaths = []
    # i feel like this code is too dangerous since there is a rm command ...
    if clean:
        for experiment_name_pattern in experiment_name_patterns:
            print('Deleting local files matching experiment pattern: {}'.format(experiment_name_pattern))
            run_local_command('rm {}.h5'.format(os.path.join(DATAPATH_PROCESSED, experiment_name_pattern)))
    if remote:
        print('Searching for experiments on remote machine: {}'.format(remote_ip))
        with get_ssh_client(ip_addr=remote_ip, username=remote_username) as ssh_client:
            for experiment_name_pattern in experiment_name_patterns:
                _, stdout, _ = ssh_client.exec_command(
                    'ls -1 /tmp/{}.tar.gz'.format(experiment_name_pattern))
                tarfile_remotepaths += [filename.strip()
                                        for filename in stdout.readlines()]
        print('Found {} experiment(s) on remote machine: {}'.format(
            len(tarfile_remotepaths), tarfile_remotepaths))
    else:
        print('Not searching remote machine for experiments.')

    if force_local or len(tarfile_remotepaths) == 0:
        num_local_files = 0
        for experiment_name_pattern in experiment_name_patterns:
            local_filepaths = glob.glob(os.path.join(DATAPATH_RAW,
                                                     experiment_name_pattern +'.tar.gz'))
            tarfile_remotepaths += local_filepaths
            num_local_files += len(local_filepaths)
        if len(tarfile_remotepaths) == 0:
            raise ValueError(('Found no experiments on remote or local machine '
                            '{} with name pattern {}').format(
                                remote_ip, experiment_name_pattern))
        if num_local_files > 0:
            print('Found {} experiment(s) on local machine: {}'.format(num_local_files,
                                                                        tarfile_remotepaths[-num_local_files:]))
        else:
            print('Found 0 experiment(s) on local machines.')

    #experiments = {}
    num_proc = 10
    num_tarfiles = len(tarfile_remotepaths)
    num_tarfiles_per_process = int(num_tarfiles / num_proc) + 1
    with mp.Pool(num_proc) as pool:
        analyzers = pool.starmap(get_experiment, zip(tarfile_remotepaths,
                                                    it.repeat(remote_ip, num_tarfiles),
                                                    it.repeat(remote_username, num_tarfiles),
                                                    it.repeat(load_queue, num_tarfiles)),
                                                    chunksize=num_tarfiles_per_process)
    experiment_analyzers = ExperimentAnalyzers()
    for analyzer in analyzers:
        experiment_analyzers['{}-{}'.format(analyzer.experiment.name,
                                            analyzer.experiment.exp_time)] = analyzer
    return experiment_analyzers

def get_experiment(tarfile_remotepath, remote_ip, remote_username, load_queue):
    # check if tarfile already here
    # copy tarfile from remote machine to local machine (data directory)
    experiment_name = os.path.basename(tarfile_remotepath[:-len('.tar.gz')])
    tarfile_localpath = os.path.join(DATAPATH_RAW, '{}.tar.gz'.format(experiment_name))
    if not os.path.isfile(tarfile_localpath):
        print('Copying remotepath {} to localpath {}'.format(
                    tarfile_remotepath, tarfile_localpath))
        cmd = 'scp {}@{}:{} {}'.format(remote_username, remote_ip,
                                        tarfile_remotepath, tarfile_localpath)
        subprocess.run(cmd, check=True, shell=True,
                        stdout = subprocess.DEVNULL,
                        stderr=subprocess.PIPE)
    # get experiment description file & stored in processed data path
    experiment_description_filename = '{}.json'.format(experiment_name)
    experiment_description_localpath = os.path.join(DATAPATH_PROCESSED,
                                                    experiment_description_filename)
    if not os.path.isfile(experiment_description_localpath):
        with untarfile(tarfile_localpath, experiment_description_filename) as f:
            experiment_description = json.load(f)
        with open(experiment_description_localpath, 'w') as f:
            json.dump(experiment_description, f)
    else:
        with open(experiment_description_localpath) as f:
            experiment_description = json.load(f)
    try:
        experiment = Experiment(tarfile_localpath=tarfile_localpath,
                                **experiment_description)
    except TypeError as e:
        print('Encountered type error when creaing experiment. Try old JSON file format...')
        with open(experiment_description_localpath) as f:
            experiment_description = json.loads(json.loads(f.read().replace('=', ':')))
        experiment = Experiment(tarfile_localpath=tarfile_localpath,
                                **experiment_description)
    experiment_analyzer = ExperimentAnalyzer(experiment, load_queue=load_queue)
    return experiment_analyzer

def tohex(x):
    try:
        return int(x, 16)
    except ValueError:
        print("Value error converting {} to hex".format(x))
        return 0