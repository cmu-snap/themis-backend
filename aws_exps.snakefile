# requires wireshark, tcpdump

# TODO: persist experiment data to redis
# TODO: figure out how to only load local exps with the correct ccalgs & ntwrk condition
# TODO: how to get figures of local exps in the all part?

aws_regions = ['ap-northeast-1', 'ap-northeast-2', 'sa-east-1','ap-southeast-1','ap-southeast-2','eu-central-1', 'us-east-1','us-east-2','us-west-1', 'ca-central-1', 'eu-west-3','eu-west-2', 'us-west-2', 'ap-south-1','eu-west-1'] 
EXP_NAME_PATTERN='data-raw/{exp_name, .*q-(' + '|'.join(aws_regions) + ')-.*}.tar.gz'
#EXP_NAME_PATTERN='data-raw/{exp_name, .*bic-5bw-85rtt-64q-us-east-1-20181117T235955.*}.tar.gz' 
AWS_EXP_NAMES, = glob_wildcards(EXP_NAME_PATTERN)
CCALGS = ['bic', 'cdg', 'dctcp', 'highspeed', 'htcp', 'hybla', 'illinois', 'lp',
          'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']
NTWRK_CONDITIONS = [(5,35,16), (5,85,64), (5,130,64), (5,275,128), (10,35,32), (10,85,128), (10,130,128), (10,275,256), (15,35,64), (15,85,128), (15,130,256), (15,275,512)]
CCAS = ['cubic','reno','bbr', 'bic', 'cdg', 'highspeed', 'htcp', 'hybla', 'illinois', 'lp', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']
import glob
LOCAL_EXPS_DICT={'{}bw-{}rtt-{}q'.format(bw, rtt, q): glob.glob(
    'data-training/*{}bw-{}rtt-{}q-local-*.tar.gz'.format(bw, rtt, q)) for bw, rtt, q in NTWRK_CONDITIONS}

# reusable
EXP_NAMES=AWS_EXP_NAMES
CSV_OUTPUT_NAME='data-processed/classify-aws-exps-20181010.csv'

# won't need all the wildcards so make an input function to tell us
# which one we actually need given an exp_name
def get_local_exps(wildcards):
    import re
    import glob
    import os
    
    ntwrk_conditions = re.match('.*-(\d+bw-\d+rtt-\d+q).*',
                                wildcards.exp_name).groups()[0]
    #experiments = []
    #for ccalg in CCAS:
        # select most recent experiment with this pattern
    #    files = sorted(glob.glob('data-training/{}-{}-local-20181113*.tar.gz'.format(ccalg,
    #                                                             ntwrk_conditions)))
    experiments = list(map(lambda tarfile_path: os.path.basename(tarfile_path)[:-7], LOCAL_EXPS_DICT[ntwrk_conditions]))
    assert(len(experiments)==len(CCAS))
    return experiments

def get_local_exps_features(wildcards):
    experiments = get_local_exps(wildcards)
    return expand('data-processed/{exp_name}.features',
                  exp_name=experiments)

def get_local_exps_plots(wildcards):
    experiments = get_local_exps(wildcards)
    return expand('graphics/{exp_name}.png',
                  exp_name=experiments)

def get_local_exps_bwdiff(wildcards):
    experiments = get_local_exps(wildcards)
    # key is the ccalg
    return {exp_name.split('-')[0] :'data-processed/{exp_name}.bwdiff'.format(exp_name=exp_name) for exp_name in experiments}

# decidde which subset of local experiments we actually need to compute dtw for this exp
def get_dtws(wildcards):
    experiments = get_local_exps(wildcards)
    dtws=expand('data-processed/{testing_exp_name}:{training_exp_name}.dtw',
                testing_exp_name=wildcards.exp_name, training_exp_name=experiments)
    return dtws
    
# specify final output of the pipeline
rule all:
    input:
        # all aws plots
        #expand('graphics/{exp_name}.png', exp_name=LOSS_EXP_NAMES),
        # all local exp plots
        # expand('graphics/{exp_name}.png', exp_name=LOCAL_EXP_NAMES),
        # get_local_exps_plots,
        # all aws results ,
        expand('graphics/{exp_name}-classify.png', exp_name=EXP_NAMES),
        all_results=CSV_OUTPUT_NAME

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

        df = (pd
        .read_csv(input.raw_queue_data,
                  names = ['dequeued',
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
        .assign(seq=lambda df: df.astype(np.uint32))
        .assign(src=lambda df: df.astype( np.uint16))
        .assign(lineno=lambda df: df.index + 1)
        .set_index('time'))
        
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
        .ffill()
        .assign(time=lambda df: pd.to_datetime(df.time,
                                               infer_datetime_format=True,
                                               unit='ns'))
        .set_index('time'))
        
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
        features='data-processed/{exp_name}.features'
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
        features_plot='graphics/{exp_name, .*(\d+)}.png'
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
            resample_interval = int(re.match('.*bw-(.*)rtt',
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
        capinfos='data-raw/capinfos-{exp_name}.txt',
        hdf_queue='data-processed/queue-{exp_name}.h5'
    output:
        metadata='data-processed/{exp_name}.metadata'
    run:
        import re
        import pandas as pd
        import numpy as np
        import subprocess

        def get_rtt_ping():
            with open(input.ping) as f:
                ping_data = f.read()
                if ping_data.strip() != '' and ping_data.startswith('PING'):
                    ping_regex = re.compile('.*time=(.*)\s+ms')
                    ping_events = [float(ping_regex.match(row).groups()[0]) for row in ping_data.split('\n') if ping_regex.match(row)]
                    df_ping = pd.DataFrame(ping_events).squeeze()                    
                    return {'rtt_mean': df_ping.mean(), 'rtt_std': df_ping.std()}
                elif ping_data.strip() != '':
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
            with pd.HDFStore(input.hdf_queue, mode='r') as hdf_queue:
                df_queue = hdf_queue.select('df_queue')
                df_queue = df_queue[~df_queue.index.duplicated(keep='last')]
                num_dropped_queue =  len(df_queue[df_queue['dropped']])

                # get number of packets dropped total
                tshark_cmd = ('tshark -r {} -Tfields ' \
                '-e tcp.analysis.retransmission ' \
                '-e tcp.analysis.out_of_order ' \
                '-e tcp.analysis.lost_segment'.format(input.tcpdump))
                tshark_results = subprocess.run(tshark_cmd,shell=True,stdout=subprocess.PIPE).stdout.decode('utf-8')

                # note: skip first packet which is always marked as a retransmission for some reason
                try:
                    df_tcpdump = pd.DataFrame([row.split('\t') for row in tshark_results.strip().split('\n')][1:]).replace('',np.nan)
                    df_tcpdump.columns = ['retransmission','out_of_order','lost_segment']
                    num_lost_tcpdump = (len(df_tcpdump[~df_tcpdump['out_of_order'].isnull()]) + len(df_tcpdump[~df_tcpdump['retransmission'].isnull()]))
                except ValueError as e:
                    num_lost_tcpdump = 0

                num_pkts_dequeued = len(df_queue[df_queue['dequeued']])

                num_pkts_lost = max(0, num_lost_tcpdump-num_dropped_queue)
                return {'pkts_dropped_queue':num_dropped_queue, 'pkts_lost_tcpdump':num_lost_tcpdump, 'pkts_dequeued':num_pkts_dequeued, 'num_pkts_lost':num_pkts_lost}

        metadata = {}
        with open(input.exp_description) as f:
            exp = json.load(f)

            metadata['rtt'] = int(re.match('.*bw-(.*)rtt', exp['name']).groups()[0])
            metadata['btlbw'] = int(exp['btlbw'])
            metadata['queue_size'] = int(exp['queue_size'])
            metadata['rtt_measured'] = float(exp['rtt_measured'])
            metadata['exp_name'] = wildcards.exp_name
            metadata['delay_added'] = int(exp['flows'][0][3])
            metadata['rtt_initial'] = metadata['rtt_measured'] - metadata['delay_added']
            # awks -- sometimes this is NaN
            metadata['true_label'] = exp['flows'][0][0]
            
            #if 'ping_log' in exp['logs']:
            metadata.update(get_rtt_ping())
            metadata['bw_measured'] = get_bw_tcpdump()
            metadata.update(get_loss_rate_tcpdump())
            if metadata['bw_measured'] is not None:
                metadata['observed_bw_diff'] = (round(metadata['bw_measured']) / metadata['btlbw'])
            else:
                metadata['observed_bw_diff'] = None
            
        with open(output.metadata, 'w') as f:
            json.dump(metadata, f)


rule compute_dtw:
    input:
        testing_flow='data-processed/{testing_exp_name}.features',
        training_flow='data-processed/{training_exp_name}.features'
    output:
        dtw='data-processed/{testing_exp_name}:{training_exp_name}.dtw'
    run:
        from fastdtw import dtw
        import pandas as pd

        testing_flow = pd.read_csv(input.testing_flow).squeeze()
        training_flow = pd.read_csv(input.training_flow).squeeze()
        Y = training_flow[:len(testing_flow)]
        X = testing_flow[:len(Y)]
        distance = dtw(X,Y)[0]
        training_flow_ccalg = wildcards.training_exp_name.split('-')[0]
        dtw_result = {training_flow_ccalg: distance}
        
        with open(output.dtw, 'w') as f:
            json.dump(dtw_result, f)

rule classify_flow:
    input:
        metadata='data-processed/{exp_name}.metadata',
        dtws=get_dtws
    output:
        classify=temp('data-processed/{exp_name}.classify')
    run:
        import pandas as pd
        import json
        import os
        
        distances = {}
        num_ties = 0  # record if there any ties
        training_exp_names = {} # store the name of the exps so we can store winning exp
        for dtw in input.dtws:
            with open(dtw) as f:
                dist = json.load(f)
                training_exp_names[list(dist.keys())[0]] = os.path.basename(
                    dtw).split(':')[1][:-4]
                distances.update(dist)

        with open(input.metadata) as f:
            distances.update(json.load(f))

        # TODO: FIX THIS ERROR; INDEXING NOT WORKING
        classify_results = (pd.DataFrame([distances])
        .assign(predicted_label=lambda df: df[CCAS].idxmin(1))
        .assign(closest_distance=lambda df: df[CCAS].min(1))
        .assign(num_distance_ties=lambda df: (df[CCAS] == df.closest_distance).sum())
        .to_dict('index'))

        classify_results = classify_results[0]
        classify_results['closest_exp_name'] = training_exp_names[
            classify_results['predicted_label']]


        with open(output.classify, 'w') as f:
            json.dump(classify_results, f)

rule get_expected_bw:
    input:
        exp_description='data-processed/{exp_name}.json',
        capinfos='data-raw/capinfos-{exp_name}.txt',
        tcpdump='data-raw/server-tcpdump-{exp_name}.pcap'
    output:
        expected_bw_diff='data-processed/{exp_name}.bwdiff'
    run:
        import json
        import subprocess
        
        with open(input.exp_description) as f:
            experiment = json.load(f)

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

        btlbw = experiment['btlbw']
        bw_measured = get_bw_tcpdump()
        bw_diff = {'expected_bw_diff' : (round(bw_measured) / btlbw),
                   'expected_bw' : bw_measured}
                
        with open(output.expected_bw_diff, 'w') as f:
            json.dump(bw_diff, f)
        
rule check_bw_too_low:
    input:
        unpack(get_local_exps_bwdiff),
        classify='data-processed/{exp_name}.classify'
    output:
        bw_too_low=temp('data-processed/{exp_name}.bwtoolow')
    run:
        import json
        
        with open(input.classify) as f:
            classify_results=json.load(f)

        # check if bw too low
        predicted_label = classify_results['predicted_label']

        with open(getattr(input, predicted_label)) as f:
            bwtoolow = json.load(f)
            expected_bw_diff = bwtoolow['expected_bw_diff']
            expected_bw = bwtoolow['expected_bw']

        observed_bw_diff = classify_results['observed_bw_diff']   
        bw_too_low = expected_bw_diff > observed_bw_diff
        expected_bw_dict = {'expected_bw_diff': expected_bw_diff,
                       'expected_bw': expected_bw,
                       'bw_too_low': bw_too_low}
        
        with open(output.bw_too_low, 'w') as f:
            json.dump(expected_bw_dict, f)

rule merge_results:
    input:
        classify='data-processed/{exp_name}.classify',
        bw_too_low='data-processed/{exp_name}.bwtoolow'
    output:
        results='data-processed/{exp_name}.results'
    run:
        with open(input.classify) as f:
            results = json.load(f)
        with open(input.bw_too_low) as f:
            results.update(json.load(f))
        with open(output.results, 'w') as f:
            json.dump(results, f)

rule plot_results:
    input:
        results='data-processed/{exp_name}.results',
        features='data-processed/{exp_name}.features',
        training_features=get_local_exps_features
    output:
        results_plot='graphics/{exp_name}-classify.png'
    run:
        import json
        import matplotlib.pyplot as plt
        import matplotlib.style as style
        import pandas as pd

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

        with open(input.results) as f:
            results = json.load(f)

        training_exp_name = results['closest_exp_name']
        resample_interval = results['rtt']
        dtw_distance = results['closest_distance']
        ccalg = results['predicted_label']
        exp_name = results['exp_name']
        queue_size = results['queue_size']

        # hardcoded the filename of the training experimant 
        df_training = pd.read_csv('data-processed/{}.features'.format(training_exp_name)).squeeze()
        df_testing = pd.read_csv(input.features).squeeze()
        
        fig, axes = plt.subplots(1,1, figsize=(10,5))
        X = df_testing
        Y = df_training
        Y = Y[:len(X)]
        X = X[:len(Y)]
        X.index = X.index * resample_interval / 1000
        Y.index = Y.index * resample_interval / 1000
        ax=(X * queue_size).plot(ax=axes,
                                label='{}'.format(exp_name),
                                 alpha=0.7)
        ax=(Y * queue_size).plot(ax=axes, label='{}-training'.format(ccalg),
                                 ylim=(0,queue_size),
                                 alpha=0.7)
        ax.set_xlabel('time (s)')
        ax.set_ylabel('queue occupancy \n (packets)')
        ax.set_title('DTW distance={:.2f}'.format(dtw_distance))
        ax.legend()
        fig.tight_layout()
        ax.figure.savefig(output.results_plot,transparent=True,bbox_inches='tight')
        
rule store_all_results:
    input:
        results=expand('data-processed/{exp_name}.results', exp_name=EXP_NAMES),
    output:
        all_results=CSV_OUTPUT_NAME
    run:
        import pandas as pd
        import json

        all_exp_results = []
        for exp_results in input.results:
            with open(exp_results) as f:
                all_exp_results.append(json.load(f))
        df_all_results = pd.DataFrame(all_exp_results)
        df_all_results.to_csv(output.all_results, index=False)

                


                
