
# TODO: persist experiment data to redis
# TODO: figure out how to only load local exps with the correct ccalgs & ntwrk conditions

EXP_NAME_PATTERN='data-raw/{exp_name, bic-15bw-85rtt-128q-us-east-1-.*}.tar.gz'
#EXP_NAME_PATTERN='data-raw/{exp_name,.*-us-east-1-.*}.tar.gz'
AWS_EXP_NAMES, = glob_wildcards(EXP_NAME_PATTERN)
CCALGS = ['bic', 'cdg', 'dctcp', 'highspeed', 'htcp', 'hybla', 'illinois', 'lp', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']

# won't need all the wildcards so make an input function to tell us
# which one we actually need given an exp_name
def get_local_exps(wildcards):
    import re
    import glob
    import os
    
    ntwrk_conditions = re.match('.*-(\d+bw-\d+rtt-\d+q).*',
                                wildcards.exp_name).groups()[0]
    experiments = []
    for ccalg in CCALGS:
        # select most recent experiment with this pattern
        files = sorted(glob.glob('data-raw/{}-{}*.tar.gz'.format(ccalg,
                                                                 ntwrk_conditions)))
        experiments.append(os.path.basename(files[0])[:-7])
    return experiments

def get_local_exps_features(wildcards):
    experiments = get_local_exps(wildcards)
    return expand('data-processed/{exp_name}.features',
                  exp_name=experiments)

def get_local_exps_plots(wildcards):
    experiments = get_local_exps(wildcards)
    return expand('graphics/{exp_name}.png',
                  exp_name=experiments)

# decidde which subset of local experiments we actually need to compute dtw for this exp
def get_dtws(wildcards):
    experiments = get_local_exps(wildcards)
    dtws=expand('data-processed/{testing_exp_name}.{training_exp_name}.dtw',
                testing_exp_name=wildcards.exp_name, training_exp_name=experiments)
    return dtws
    
# specify final output of the pipeline
rule all:
    input:
        # all aws plots
        expand('graphics/{exp_name}.png', exp_name=AWS_EXP_NAMES),
        # all local exp plots
        # expand('graphics/{exp_name}.png', exp_name=LOCAL_EXP_NAMES),
        # get_local_exps_plots,
        # all aws results ,
        all_results='data-processed/classify-aws-exps.csv'

rule store_all_results:
    input:
        classify=expand('data-processed/{exp_name}.classify', exp_name=AWS_EXP_NAMES),
        results=expand('data-processed/{exp_name}.metadata', exp_name=AWS_EXP_NAMES)
    output:
        all_results='data-processed/classify-aws-exps.csv'
    run:
        import pandas
        import json

        all_exp_results = []
        for exp_results in input.all_results:
            with open(exp_results) as f:
                all_exp_results.append(json.load(f))
        df_all_results = pd.DataFrame(all_exp_results).set_index('name')
        df_all_results.to_csv(output.all_results)


# todo: rule for making all local experiment plots

rule load_raw_queue_data:
    input:
        'data-raw/{exp_name}.tar.gz'
    params:
        queue_filename='queue-{exp_name}.txt'
    output:
        temp('data-raw/queue-{exp_name}.txt')
    shell:
        """
        tar -C data-raw/ -xzvf {input} {params.queue_filename}
        sort -k 2 -o {output} {output} \
        && grep ^.*,.*,.*,.*,.*,.*,.*,.*,.*$ {output} > {output}.tmp \
        && mv {output}.tmp {output}
        """

rule load_exp_description:
    input:
        exp_tarfile='data-raw/{exp_name}.tar.gz'
    params:
        exp_description='{exp_name}.json'
    output:
        'data-processed/{exp_name}.json'
    shell:
        """
        tar -C data-processed/ -xzvf {input.exp_tarfile} {params.exp_description}
        """

rule store_queue_hdf:
    input:
        raw_queue_data='data-raw/queue-{exp_name}.txt'
    output:
        hdf_queue='data-processed/queue-{exp_name}.h5'
    run:
        import pandas as pd
        import numpy as np

        def tohex(x):
            try:
                return int(x, 16)
            except ValueError:
                print("Value error converting {} to hex".format(x))
                return 0

        df = pd.read_csv(input.raw_queue_data, names = ['dequeued',
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

        with pd.HDFStore(output.hdf_queue, mode='w') as store:
            store.append('df_queue',
                         df,
                         format='table',
                         data_columns=['src', 'dropped', 'dequeued'])

rule compute_flow_features:
    input:
        queue_store='data-processed/queue-{exp_name}.h5',
        exp_description='data-processed/{exp_name}.json'
    output:
        features=temp('data-processed/{exp_name}.features')
    run:
        import pandas as pd
        import json
        from data_analysis.prediction import get_labels_dtw, get_deltas_dtw, resample_dtw, get_features_dtw
        import re

        with open(input.exp_description) as f:
            exp_description = json.load(f)
        flow_ccalg = exp_description['flows'][0][0]
        queue_size = exp_description['queue_size']
        resample_interval =  int(re.match('.*bw-(.*)rtt',
                                          exp_description['name']).groups()[0])

        with pd.HDFStore(input.queue_store, mode='r') as hdf_queue:
            df_queue = hdf_queue.select('df_queue', columns=['size'])
            df_queue = df_queue['size']
            df_queue.name = flow_ccalg
            df_queue = df_queue.sort_index()
            # there could be duplicate rows if batch size is every greater than 1
            # want to keep last entry for any duplicated rows
            df_queue = df_queue[~df_queue.index.duplicated(keep='last')]
            df_queue = df_queue / queue_size

            resampled = resample_dtw(df_queue, resample_interval)
            deltas = get_deltas_dtw(resampled)
            labels = get_labels_dtw(deltas)
            features = get_features_dtw(labels)
            features.to_csv(output.features, header=['queue_occupancy'], index=False)

rule plot_flow_features:
    input:
        exp_description='data-processed/{exp_name}.json',
        features='data-processed/{exp_name}.features'
    output:
        features_plot='graphics/{exp_name}.png'
    run:
        import matplotlib.pyplot as plt
        import matplotlib.style as style
        import pandas as pd
        import re

        plt.rcParams.update(plt.rcParamsDefault)
        style.use(['seaborn-colorblind', 'seaborn-paper', 'seaborn-white'])
        plt.rc('font', size=12)
        plt.rc('axes', titlesize=12, titleweight='bold', labelsize=12)
        plt.rc('xtick', labelsize=12)
        plt.rc('ytick', labelsize=12)
        plt.rc('legend', fontsize=12)
        plt.rc('figure', titlesize=12)
        plt.rc('lines', linewidth=3)
        plt.rc('axes.spines', right=False, top=False)

        with open(input.exp_description) as f:
            resample_interval =  int(re.match('.*bw-(.*)rtt',
                                    json.load(f)['name']).groups()[0])

        df_features = pd.read_csv(input.features)
        df_features.index = df_features.index * resample_interval / 1000
        ax = df_features.plot(legend=False)
        ax.set_xlabel('time (s)')
        ax.set_ylabel('queue occupancy \n (packets)')
        ax.figure.savefig(output.features_plot,
                          transparent=True,
                          bbox_inches='tight')

##### CLASSIFICATION ######

# upon failure will make empty file -- possible log doesn't exist
rule load_exp_ping_log:
    input:
        exp_tarfile='data-raw/{exp_name}.tar.gz'
    params:
        exp_ping_log='ping-{exp_name}.txt'
    output:
        ping=temp('data-raw/ping-{exp_name}.txt')
    shell:
        """
        tar -C data-raw/ -xzvf {input.exp_tarfile} {params.exp_ping_log} \
        || touch {output.ping}
        """

rule load_exp_tcpdump:
    input:
        exp_tarfile='data-raw/{exp_name}.tar.gz'
    params:
        exp_tcpdump_log='server-tcpdump-{exp_name}.pcap'
    output:
        tcpdump=temp('data-raw/server-tcpdump-{exp_name}.pcap')
    shell:
        """
        tar -C data-raw/ -xzvf {input.exp_tarfile} {params.exp_tcpdump_log}
        """

# upon failure will make empty file -- file may not exist
rule load_exp_capinfos:
    input:
        exp_tarfile='data-raw/{exp_name}.tar.gz'
    params:
        exp_capinfos_log='capinfos-{exp_name}.txt'
    output:
        capinfos=temp('data-raw/capinfos-{exp_name}.txt')
    shell:
        """
        tar -C data-raw/ -xzvf {input.exp_tarfile} {params.exp_capinfos_log} \
        || touch {output.capinfos}
        """

rule get_metadata:
    input:
        exp_description='data-processed/{exp_name}.json',
        tcpdump='data-raw/server-tcpdump-{exp_name}.pcap',
        ping='data-raw/ping-{exp_name}.txt',
        capinfos='data-raw/capinfos-{exp_name}.txt'
    output:
        metadata='data-processed/{exp_name}.metadata'
    run:
        import re
        import pandas as pd
        import numpy as np
        import subprocess

        def get_rtt_ping():
            with open(input.ping_log) as f:
                ping_data = f.read()
                if ping_data.strip() != '':
                    ping_regex = re.compile('(SENT|RECV) \((.*)s\)')
                    ping_events = [ping_regex.match(row).groups() for row in ping_data.split('\n') if ping_regex.match(row)]
                    df_ping = pd.DataFrame(ping_events)
                    df_ping.columns = ['event','time']
                    df_ping['time'] = pd.to_numeric(df_ping['time'])
                    df_ping = df_ping.pivot(columns='event', values='time').bfill().iloc[::2]
                    df_ping = (df_ping['RECV'] - df_ping['SENT']) * 1000
                    return {'rtt_mean': df_ping.mean(), 'rtt_std': df_ping.std()}
                else:
                    return {'rtt_mean': None, 'rtt_std': None}

        def get_bw_tcpdump():
            with open(input.capinfos) as f:
                capinfos_data = f.read()
            if capinfos_data.strip() == '':
                cmd = 'capinfos -iTm {}'.format(input.tcpdump)
                capinfos_data = subprocess.run(cmd, shell=True,
                                               stdout=subprocess.PIPE).stdout.decode(
                                                   'utf-8')
            try:
                bw = capinfos_data.split('\n')[1].split(',')[-1]
                return float(bw) / 10**6
            except:
                bw = None
                return None

        def get_loss_rate_tcpdump():
            # get number packets dropped from queue
            with pd.HDFStore(input.queue_store, mode='r') as hdf_queue:
                df_queue = hdf_queue.select('df_queue')
                df_queue = df_queue[~df_queue.index.duplicated(keep='last')]
                num_dropped_queue =  len(df_queue[df_queue['dropped']])

                # get number of packets dropped total
                tshark_cmd = ('tshark -r {} -Tfields '
                              '-e tcp.analysis.retransmission '
                              '-e tcp.analysis.out_of_order '
                              '-e tcp.analysis.lost_segment'.format(input.tcpdump))
                tshark_results = subprocess.run(tshark_cmd,
                                                shell=True,
                                                stdout=subprocess.PIPE).stdout.decode(
                                                    'utf-8')

                # note: skip first packet which is always marked as a retransmission for some reason
                try:
                    df_tcpdump = pd.DataFrame([row.split('\t') for row in tshark_results.strip().split('\n')][1:]).replace('',np.nan)
                    df_tcpdump.columns = ['retransmission','out_of_order','lost_segment']
                    num_lost_tcpdump = (len(df_tcpdump[~df_tcpdump['out_of_order'].isnull()])
                                        + len(df_tcpdump[~df_tcpdump['retransmission'].isnull()]))
                except ValueError as e:
                    num_lost_tcpdump = 0

                num_pkts_dequeued = len(df_queue[df_queue['dequeued']])
                return {'pkts_dropped_queue': num_dropped_queue,
                        'pkts_lost_tcpdump': num_lost_tcpdump,
                        'pkts_dequeued':num_pkts_dequeued}

        metadata = {}
        with open(input.exp_description) as f:
            exp = json.load(f)

            metadata['rtt'] = int(re.match('.*bw-(.*)rtt',
                                           exp_description['name']).groups()[0])
            metadata['btlbw'] = int(exp['btlbw'])
            meatdata['queue_size'] = int(exp['queue_size'])
            metadata['rtt_measured'] = float(exp['rtt_measured'])
            metadata['name'] = params.exp_name
            metadata['delay_added'] = int(exp['flows'][0][3])
            metadata['rtt_initial'] = metadata['rtt_measured'] - metadata['delay_added']

            #if 'ping_log' in exp['logs']:
            metadata.update(get_rtt_ping())
            metadata['bw_measured'] = get_bw_tcpdump()
            metadata.update(get_loss_rate_tcpdump())
            if metadata['bw_measured'] is not None:
                metadata['observed_bw_diff'] = (round(metadata['bw_measured'])
                                                / metadata['btlbw'])
            else:
                metadata['observed_bw_diff'] = None
            
        with open({output.metadata}) as f:
            json.dump(metadata, f)


rule compute_dtw:
    input:
        metadata='data-processed/{testing_exp_name}.metadata',
        testing_flow='data-processed/{testing_exp_name}.features',
        training_flow='data-processed/{training_exp_name}.features'
    output:
        dtw=temp('data-processed/{testing_exp_name}.{training_exp_name}.dtw')

        
rule classify_flows:
    input:
        metadata='data-processed/{exp_name}.features',
        dtws=get_dtws
    output:
        classify='data-processed/{exp_name}.classify'

    # add all distances to results, add smallest distance, check if invalid
    

"""    
rule get_training_flows:
    input:
        testing_flow='data-processed/{exp_name, ^((?!(-local-)).)*$}.features',
        metadata='data-processed/{exp_name, ^((?!(-local-)).)*$}.metadata'
    output:
        temp(training_flows='data-processed/{exp_name}.training')
    run:
        with open(input.metadata) as f:
            metadata = json.load(f)
        training_flows = []
        for ccalg in CCALGS:
            # TODOL figure this out
            

rule classify_flow:
    input:
        testing_flow='data-processed/{exp_name, ^((?!(-local-)).)*$}.features'
        exp_description='data-processed/{exp_name}.json'
        #training_flows=[
        #    'data-processed/{training_exp_name}.features',
        #    training_exp_name=LOCAL_EXP_NAMES)
        training_flows='data-processed/{exp_name}.training'
    params:
        exp_name='{exp_name}'
    output:
        classify_results=temp('data-processed/{exp_name}.classify')
    run:

       X = pd.read_csv(input.testing_flow)
"""




# rule classify
# rule metadata
# rule mark invalid
