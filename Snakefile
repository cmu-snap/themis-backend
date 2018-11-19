
AWS_EXP_NAMES, = glob_wildcards('data-raw/{exp_name}.tar.gz')

# specify final output of the pipeline 
rule all:
    input:
        expand('graphics/{exp_name}.png',
               exp_name=AWS_EXP_NAMES)

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
        
        with open(input.exp_description) as f:
            exp_description = json.load(f)
        flow_ccalg = exp_description['flows'][0][0]
        queue_size = exp_description['queue_size']
        resample_interval = exp_description['flows'][0][3]
        
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
            resample_interval = json.load(f)['flows'][0][3]
        
        df_features = pd.read_csv(input.features)
        df_features.index = df_features.index * resample_interval / 1000
        ax = df_features.plot(legend=False)
        ax.set_xlabel('time (s)')
        ax.set_ylabel('queue occupancy \n (packets)')
        ax.figure.savefig(output.features_plot,
                          transparent=True,
                          bbox_inches='tight')

