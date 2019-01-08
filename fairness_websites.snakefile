# requires wireshark, tcpdump
import glob
import os
import json

workdir: "/opt/cctestbed"
         
onsuccess:
    pass
    #shell('rm -f /tmp/data-tmp/*')
    # check if results are invalid
    #for result_file in glob.glob('/tmp/data-processed/*.results'):
    #    with open(result_file) as f:
    #        results = json.load(f)
    #        print(result_file, results['predicted_label'], results['mark_invalid'], results['bw_measured'],
    #              results['expected_bw'], results['num_pkts_lost'])
                
            
BW_THRESHOLD=0.5
PKT_LOSS_THRESHOLD=0

NTWRK_CONDITIONS = [(5,35,16), (5,85,64), (5,130,64), (5,275,128), (10,35,32), (10,85,128), (10,130,128), (10,275,256), (15,35,64), (15,85,128), (15,130,256), (15,275,512)]
CCAS = ['cubic','reno','bbr', 'bic', 'cdg', 'highspeed', 'htcp', 'hybla', 'illinois', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']
        
#EXP_NAMES, = glob_wildcards('data-raw/{exp_name}.tar.gz')
EXP_NAMES, = glob_wildcards('data-tmp/{exp_name}.tar.gz')           
    
# specify final output of the pipeline
rule all:
    input:
         all_results=expand('{exp_name}.fairness.tar.gz', exp_name=EXP_NAMES)
         #all_results=expand('data-processed/queue-{exp_name}.h5',exp_name=EXP_NAMES)
         
rule load_raw_queue_data:
    input:
        'data-raw/{exp_name}.tar.gz'
    params:
        queue_filename='queue-{exp_name}.txt'
    output:
        temp('data-raw/queue-{exp_name}.txt')
        #'data-raw/queue-{exp_name}.txt'
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
        .assign(lineno=lambda df: df.index + 1)
        .sort_values('time')
        .reset_index(drop=True))
        
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
        .join(df_flows)
        .sort_index() # unecessary
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

rule get_goodput_timeseries:
    input:
        queue='data-processed/queue-{exp_name}.h5'
    output:
        goodput='data-processed/{exp_name}.goodput'
    run:
        import pandas as pd

        with pd.HDFStore(input.queue, mode='r') as hdf_queue:
            df_queue = hdf_queue.select('df_queue')
        transfer_time = 1000 #ms
        goodput = (df_queue[df_queue['dequeued']]
         .groupby('src')
         .datalen
         .resample('{}ms'.format(transfer_time))
         .sum()
         .unstack(level='src')
         .fillna(0)
         .apply(lambda df: (df * BYTES_TO_BITS * BITS_TO_MEGABITS) / (transfer_time / 1000))
         .assign(relative_time=lambda df: (df.index - df.index[0]).total_seconds())
         .set_index('relative_time')
        )
        goodput.to_csv(output.goodput)
        
rule scp_results:
    input:
        exp_tarfile='data-raw/{exp_name}.tar.gz',
        goodput='data-processed/{exp_name}.goodput',
        queue='data-processed/queue-{exp_name}.h5',
    output:
        compressed_results='{exp_name}.fairness.tar.gz'
    shell:
       """
       tar -czvf {output.compressed_results} {input.goodput} {input.exp_tarfile} {input.queue} && scp -o StrictHostKeyChecking=no -i /users/rware/.ssh/rware-potato.pem {output.compressed_results} ranysha@128.2.208.104:/opt/cctestbed/data-websites/ && rm data-tmp/*{wildcards.exp_name}*
       """
       
    
