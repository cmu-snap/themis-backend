import os
import glob

NTWRK_CONDITIONS = [(5,35,16), (5,85,64), (5,130,64), (5,275,128), (10,35,32), (10,85,128), (10,130,128), (10,275,256), (15,35,64), (15,85,128), (15,130,256), (15,275,512)]
CCAS = ['cubic','reno','bbr', 'bic', 'cdg', 'highspeed', 'htcp', 'hybla', 'illinois', 'lp', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']

LOCAL_EXPS_DICT={'{}bw-{}rtt-{}q'.format(bw, rtt, q): glob.glob(
    'data-training/*{}bw-{}rtt-{}q-local-*.tar.gz'.format(bw, rtt, q)) for bw, rtt, q in NTWRK_CONDITIONS}

EXP_NAMES=[os.path.basename(exp)[:-7] for key, value in LOCAL_EXPS_DICT.items() for exp in value]

# specify final output of the pipeline
rule all:
    input:
        all_features=expand('data-training/{exp_name}.features', exp_name=EXP_NAMES),
        all_hdf_queues=expand('data-training/queue-{exp_name}.h5', exp_name=EXP_NAMES),
        all_exp_descriptions=expand('data-training/{exp_name}.json', exp_name=EXP_NAMES),
        all_metadata=expand('data-training/{exp_name}.metadata', exp_name=EXP_NAMES)
        
rule load_raw_queue_data:
    input:
        'data-training/{exp_name}.tar.gz'
    params:
        queue_filename='queue-{exp_name}.txt'
    output:
        temp('data-training/queue-{exp_name}.txt')
    shell:
        """
        tar -C data-training -xzvf {input} {params.queue_filename}
        sort -k 2 -o {output} {output} \
        && grep ^.*,.*,.*,.*,.*,.*,.*,.*,.*$ {output} > {output}.tmp \
        && mv {output}.tmp {output}
        """

rule load_exp_description:
    input:
        exp_tarfile='data-training/{exp_name}.tar.gz'
    params:
        exp_description='{exp_name}.json'
    output:
        'data-training/{exp_name}.json'
    shell:
        """
        tar -C data-training -xzvf {input.exp_tarfile} {params.exp_description}
        """

rule store_queue_hdf:
    input:
        raw_queue_data='data-training/queue-{exp_name}.txt'
    output:
        hdf_queue='data-training/queue-{exp_name}.h5'
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
        queue_store='data-training/queue-{exp_name}.h5',
        exp_description='data-training/{exp_name}.json'
    output:
        features='data-training/{exp_name}.features'
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



# upon failure will make empty file -- possible log doesn't exist

rule load_exp_tcpdump:
    input:
        exp_tarfile='data-training/{exp_name}.tar.gz'
    params:
        exp_tcpdump_log='server-tcpdump-{exp_name}.pcap'
    output:
        tcpdump=temp('data-training/server-tcpdump-{exp_name}.pcap')
    shell:
        """
        tar -C data-training -xzvf {input.exp_tarfile} {params.exp_tcpdump_log}
        """

# upon failure will make empty file -- file may not exist
rule load_exp_capinfos:
    input:
        exp_tarfile='data-training/{exp_name}.tar.gz'
    params:
        exp_capinfos_log='capinfos-{exp_name}.txt'
    output:
        capinfos=temp('data-training/capinfos-{exp_name}.txt')
    shell:
        """
        tar -C data-training -xzvf {input.exp_tarfile} {params.exp_capinfos_log} \
        || touch {output.capinfos}
        """

rule get_metadata:
    input:
        exp_description='data-training/{exp_name}.json',
        tcpdump='data-training/server-tcpdump-{exp_name}.pcap',
        capinfos='data-training/capinfos-{exp_name}.txt',
        hdf_queue='data-training/queue-{exp_name}.h5'
    output:
        metadata='data-training/{exp_name}.metadata'
    run:
        import re
        import pandas as pd
        import numpy as np
        import subprocess

        def get_rtt_ping():
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
