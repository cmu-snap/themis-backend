#CODEPATH = '/Users/rware/Documents/research/code/cctestbed'
#DATAPATH_RAW = '/Users/rware/Documents/research/data/cctestbed/raw'
#DATAPATH_PROCESSED = '/Users/rware/Documents/research/data/cctestbed/processed'

CODEPATH = '/home/ranysha/cctestbed'
DATAPATH_RAW = '/home/ranysha/cctestbed/data-raw'
DATAPATH_PROCESSED = '/home/ranysha/cctestbed/data-processed'

import sys
sys.path.insert(0, CODEPATH)

from collections import namedtuple, Counter, defaultdict
from contextlib import contextmanager
import cctestbedv2 as cctestbed
import matplotlib.pyplot as plt
import pandas as pd
import datetime as dt
import paramiko
import os
import tarfile
import json
import yaml
import glob
import subprocess
import multiprocessing as mp

REMOTE_IP_ADDR = '128.2.208.131'
REMOTE_USERNAME = 'ranysha'
BYTES_TO_BITS = 8
BITS_TO_MEGABITS = 1.0 / 1000000.0
MILLISECONDS_TO_SECONDS = 1.0 / 1000.0

Host = namedtuple('Host', ['ifname_remote', 'ifname_local', 'ip_wan', 'ip_lan', 'pci', 'key_filename', 'username'])
Flow = namedtuple('Flow', ['ccalg', 'start_time', 'end_time', 'rtt',
                           'server_port', 'client_port', 'client_log', 'server_log'])

# Goal is to leave raw data in tarfile in DATAPATH_RAW and store all processed data in DATAPATH_PROCESSED

# TODO: don't load experiment if files already exist


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

"""
Each experiment has it's own experiment analyzer

Lazily populate dataframes for queue, tcpprobe
"""
class ExperimentAnalyzer:
    def __init__(self, experiment):
        self.experiment = experiment
        self._df_queue = None
        self._df_tcpprobe = None
        self._df_tcpdump_client = None
        self._df_tcpdump_server = None
        self._flow_sender_ports = None
        self._flow_names = None

    @property
    def df_queue(self):
        queue_log_tarpath = self.experiment.logs['queue_log']
        queue_log_localpath = os.path.join(DATAPATH_PROCESSED,
                                            '{}.csv'.format(os.path.join(queue_log_tarpath[:-len('.txt')])))
        if (self._df_queue is None) or (not os.path.isfile(queue_log_localpath)):
            # cleanup data and store processed data
            if not os.path.isfile(queue_log_localpath):
                if not os.path.isfile(os.path.join(DATAPATH_RAW, queue_log_tarpath)):
                    with untarfile(self.experiment.tarfile_localpath, queue_log_tarpath) as f:
                        # remove header=0, since there is no header
                        df = pd.read_csv(f, skipinitialspace=True,
                                names=['dequeued', 'time', 'src', 'seq', 'datalen',
                                        'size', 'dropped', 'queued', 'batch'])
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

    @property
    def flow_sender_ports(self):
        if self._flow_sender_ports is None:
            self._flow_sender_ports = {str(flow.client_port):flow.ccalg
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
                    flow_names[port] = '{}-{}'.format(ccalg, seen_ccalgs_counter[ccalg])
                else:
                    flow_names[port] = ccalg
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

    @property
    def df_tcpdump_server(self):
        raise NotImplementedError()

    def __repr__(self):
        attrs = self.__str__()
        return 'ExperimentAnalyzer({})'.format(attrs)

    def __str__(self):
        return str(self.experiment)

### helper functions

def load_experiments(experiment_name_patterns, remote=True, force_local=False, remote_username=REMOTE_USERNAME, remote_ip=REMOTE_IP_ADDR):
    """
    experiment_name_pattern : list of str
        Should be a pattern that will be called with '{}.tar.gz'.format(experiment_name_pattern)
    remote : bool, (default: True)
        If True, look for experiments remotely. If False, don't look for experiments remotely,
        only locally.
    force_local : bool, (default: False)
        If True, always look for local experiments. If False, only look for local experiments,
        if no remote experiments are found.
    """
    assert(type(experiment_name_patterns) is list)
    tarfile_remotepaths = []
    if remote:
        print('Searching for experiments on remote machine: {}'.format(remote_ip))
        with cctestbed.get_ssh_client(ip_addr=remote_ip,
                                      username=remote_username) as ssh_client:
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
                                                     experiment_name_pattern))
            tarfile_remotepaths += local_filepaths
            num_local_files += len(local_filepaths)
        if len(tarfile_remotepaths) == 0:
            raise ValueError(('Found no experiments on remote or local machine '
                            '{} with name pattern {}').format(
                                REMOTE_IP_ADDR, experiment_name_pattern))
        if num_local_files > 0:
            print('Found {} experiment(s) on local machine: {}'.format(num_local_files,
                                                                        tarfile_remotepaths[-num_local_files:]))
        else:
            print('Found 0 experiment(s) on local machines.')

    #experiments = {}
    with mp.Pool(10) as pool:
        experiments = pool.map(get_experiment, tarfile_remotepaths)
    #for tarfile_remotepath in tarfile_remotepaths:
    #    experiment_name, exp = get_experiment(tarfile_remotepath)
    #    experiments[experiment_name] = exp
    experiment_analyzers = {experiment_name:ExperimentAnalyzer(experiment)
                                for experiment_name, experiment in experiments} #experiments.items()}
    return experiment_analyzers

def get_experiment(tarfile_remotepath):
    # check if tarfile already here
    # copy tarfile from remote machine to local machine (data directory)
    experiment_name = os.path.basename(tarfile_remotepath[:-len('.tar.gz')])
    tarfile_localpath = os.path.join(DATAPATH_RAW, '{}.tar.gz'.format(experiment_name))
    if not os.path.isfile(tarfile_localpath):
        with cctestbed.get_ssh_client(REMOTE_IP_ADDR, username=REMOTE_USERNAME) as ssh_client:
            sftp_client = ssh_client.open_sftp()
            try:
                print('Copying remotepath {} to localpath {}'.format(
                    tarfile_remotepath, tarfile_localpath))
                sftp_client.get(tarfile_remotepath,
                                tarfile_localpath)
            finally:
                sftp_client.close()
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
    experiment = Experiment(tarfile_localpath=tarfile_localpath,
                            **experiment_description)
    return experiment_name, experiment


@contextmanager
def untarfile(tar_filename, filename, untar_dir=DATAPATH_RAW, delete_file=True):
    file_localpath = os.path.join(untar_dir, filename)
    try:
        print('Extracting file {} from {} to {}'.format(filename, tar_filename, file_localpath))
        cmd = 'cd {} && tar -xzvf {} {}'.format(untar_dir,
                                                os.path.join(tar_filename),
                                                filename)
        completed_proc = subprocess.run(cmd, shell=True)
        f = open(file_localpath)
        yield f
    finally:
        f.close()
        if delete_file:
            print('Deleting file {}'.format(file_localpath))
            os.remove(file_localpath)


@contextmanager
def untarfile_extract(tar_filename, filename):
    file_localpath = os.path.join(DATAPATH_RAW, filename)
    try:
        with tarfile.open(tar_filename, 'r:gz') as tar:
            # get experiment description file
            #experiment_description_filename = '{}.json'.format(experiment_name)
            print('Extracting file {} from {} to {}'.format(filename, tar_filename, file_localpath))
            tar.extract(filename, path=DATAPATH_RAW)
        # return path to the file
        yield file_localpath
    finally:
        os.remove(file_localpath)



##### PLOTS ######

def plot_queue(experiment_analyzer, window_size, include_ports=False,
                zoom=None, hline=None, plot=True, drops=False, size=False, save=False, **kwargs):
    df_queue = experiment_analyzer.df_queue
    queue = df_queue.rename(columns=experiment_analyzer.flow_names)
    sender_ports = list(experiment_analyzer.flow_names.keys())
    flow_names = list(experiment_analyzer.flow_names.values())
    start_time = df_queue[df_queue.sort_index().src.isin(sender_ports)].index[0]

    if size:
        queue = queue[['size'] + flow_names]
    else:
        queue = queue[flow_names]
    queue = queue.loc[start_time:]
    queue = queue.resample('{}ms'.format(window_size)).mean().ffill()
    queue.index = (queue.index - queue.index[0]).total_seconds()
    if len(flow_names) == 1:
        queue = queue[flow_names]
    if plot:
        if len(flow_names) > 1:
            ax = queue.plot(xlim=zoom, **kwargs)
            ax.set_xlabel('time (seconds)')
            ax.set_ylabel('num packets in queue')
        else:
            if drops:
                _, axes = plt.subplots()
                colors = plt.rcParams['axes.prop_cycle'].by_key()['color']
                tmp = df_queue[df_queue.dropped==1]
                tmp.index = (tmp.index - df_queue.index[0]).total_seconds()
                ((tmp['dropped']+tmp['dropped']+128)
                    .reset_index()
                    .plot
                    .scatter(x='time (s)',
                            y='dropped',
                            marker='x',
                            color=colors[1],
                            ax=axes))
                queue.plot(title='Average Queue Size ({}ms window)'.format(window_size), xlim=zoom, ax=axes, **kwargs)
                axes.set_xlabel('time (seconds)')
                axes.set_ylabel('num packets in queue')
            else:
                queue = queue[flow_names]
                #ax = queue.plot(title='Average Queue Size ({}ms window)'.format(window_size), xlim=zoom)
                ax = queue.plot(title='Average Queue Size ({}ms window)'.format(window_size), xlim=zoom, **kwargs)
                ax.set_xlabel('time (seconds)')
                ax.set_ylabel('num packets in queue')
                if hline:
                    ax.axhline(y=hline, linewidth=4, color='r')
        if save:
            return ax
    return queue

def get_goodput_timeseries(experiment_analyzer, window_size):
    df_queue = experiment_analyzer.df_queue
    transfer_time = window_size * MILLISECONDS_TO_SECONDS
    transfer_size = (df_queue[df_queue.dequeued==1]
                     .groupby('src')
                     .datalen
                     .resample('{}ms'.format(window_size))
                     .sum()
                     .unstack(level='src')
                     .fillna(0))
    transfer_size = (transfer_size * BYTES_TO_BITS) * BITS_TO_MEGABITS
    goodput = transfer_size / transfer_time
    goodput.index = (goodput.index - goodput.index[0]).total_seconds()
    goodput = goodput.rename(columns=experiment_analyzer.flow_names) # this won't work when the flows have the same name!
    goodput = goodput[list(experiment_analyzer.flow_names.values())]
    return goodput

def get_goodput_timeseries_ccalg(goodput):
    goodput_ccalg_avg = pd.DataFrame()
    goodput_ccalg_std = pd.DataFrame()
    each_ccalgs_columns = defaultdict(list)
    for col in goodput.columns:
        ccalg = col.split('-')[0]
        each_ccalgs_columns[ccalg].append(col)
    for ccalg, cols in each_ccalgs_columns.items():
        col_name = '{} {} flows'.format(len(cols), ccalg)
        goodput_ccalg_avg[col_name] = goodput[cols].mean(1)
        goodput_ccalg_std[col_name] = goodput[cols].std(1)
    return goodput_ccalg_avg, goodput_ccalg_std

def plot_goodput(experiment_analyzer, window_size=None, save=False, ccalg=False, **kwargs):
    """Return the table used for plotting"""
    if window_size is None:
        # use the rtt of the first flow as the window size
        window_size = experiment_analyzer.experiment.flows[0].rtt
    goodput = get_goodput_timeseries(experiment_analyzer, window_size)
    if ccalg:
        goodput, goodput_ccalg_std = get_goodput_timeseries_ccalg(goodput)
        ax = goodput.plot(yerr=goodput_ccalg_std, **kwargs)
    else:
        ax = goodput.plot(**kwargs)
    ax.set_xlabel('time (seconds)')
    ax.set_ylabel('goodput (mbps)')
    if save:
        return ax
    return goodput

def get_goodput_fraction(experiment_analyzers):
    goodput_fraction_table = []
    for _, analyzer in experiment_analyzers.items():
        each_ccalgs_rows = defaultdict(list)
        goodput = analyzer.get_total_goodput(interval=(150,290))
        for row in goodput.index:
            ccalg = row.split('-')[0]
            each_ccalgs_rows[ccalg].append(row)
        goodput_fraction_row = {}
        for ccalg, rows in each_ccalgs_rows.items():
            goodput_fraction_row['num_{}_flows'.format(ccalg)] = len(rows)
            goodput_fraction_row[ccalg] = goodput[rows].sum() / goodput.sum()
            goodput_fraction_row['bdp'] = '{} mbps, {} ms'.format(
                analyzer.experiment.btlbw, analyzer.experiment.flows[0].rtt)
            goodput_fraction_row['queue_size'] = analyzer.experiment.queue_size
        goodput_fraction_table.append(goodput_fraction_row)
    return pd.DataFrame.from_dict(goodput_fraction_table)

def get_tcpprobe_columns_per_flow(experiment_analyzer, col):
    """Return tcpprobe dataframe with a column per flow for a given value 'col'.
    Parameters:
    -----------
    experiment_analyzer : ExperimentAnalyzer
        experiment we want to get tcpprobe dataframe from
    column: list of str
        columns we want to get values for individually from each flow
    """
    #assert(type(cols) is list)
    tcpprobe = experiment_analyzer.df_tcpprobe.copy()
    tcpprobe['sender'] = tcpprobe['sender'].apply(lambda x: x.split(':')[-1])
    tcpprobe = tcpprobe.pivot(columns='sender', values=col)
    flow_sender_ports = list(experiment_analyzer.flow_sender_ports.keys())
    tcpprobe = tcpprobe[flow_sender_ports].rename(columns=experiment_analyzer.flow_names)
    return tcpprobe

def get_tcpprobe_avg(experiment_analyzer):
    """Get avg per flow """
    pass

def get_queue_occupancy_per_flow(experiment_analyzer, window_size):
    flow_sender_ports = list(experiment_analyzer.flow_sender_ports.keys())
    queue_occupancy = (experiment_analyzer
                        .df_queue[flow_sender_ports]
                        .resample('{}ms'.format(window_size))
                        .last()
                        .ffill())
    queue_occupancy.index = (queue_occupancy.index - queue_occupancy.index[0]).total_seconds()
    return queue_occupancy

