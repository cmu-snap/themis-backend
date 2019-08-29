# requires wireshark, tcpdump
import glob
import os
import json

#workdir: "/tmp"
         

def get_metric_files(wildcards):
    if 'video' in wildcards.exp_name:
        return {'http': 'data-imc-2019/{}.http'.format(wildcards.exp_name),
                'description': 'data-imc-2019/{}.json'.format(wildcards.exp_name),
                'tshark': 'data-imc-2019/{}.tshark'.format(wildcards.exp_name)}
    else:
        return {'tshark': 'data-imc-2019/{}.tshark'.format(wildcards.exp_name),
                'description': 'data-imc-2019/{}.json'.format(wildcards.exp_name)}
def get_metric_files_list(wildcards):
    if 'video' in wildcards.exp_name:
        return {'metric_files':['data-imc-2019/{}.http'.format(wildcards.exp_name),
                'data-imc-2019/{}.tshark'.format(wildcards.exp_name)]}
    else:
        return {'metric_files':['data-imc-2019/{}.tshark'.format(wildcards.exp_name)]}

    
            
BW_THRESHOLD=0.5
PKT_LOSS_THRESHOLD=0
BYTES_TO_BITS = 8
BITS_TO_MEGABITS = 1.0 / 1e6

NTWRK_CONDITIONS = [(5,35,16), (5,85,64), (5,130,64), (5,275,128), (10,35,32), (10,85,128), (10,130,128), (10,275,256), (15,35,64), (15,85,128), (15,130,256), (15,275,512)]
CCAS = ['cubic','reno','bbr', 'bic', 'cdg', 'highspeed', 'htcp', 'hybla', 'illinois', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']
        
#EXP_NAMES, = glob_wildcards('data-imc-2019/{exp_name}.tar.gz')
EXP_NAMES, = glob_wildcards('data-imc-2019/{exp_name}.tar.gz')           
    
# specify final output of the pipeline
rule all:
    input:
         #all_results=expand('{exp_name}.fairness.tar.gz', exp_name=EXP_NAMES)
         #all_results=expand('data-imc-2019/{exp_name}.tshark',exp_name=EXP_NAMES)
         all_results=expand('data-imc-2019/tcpprobe-{exp_name}.csv',exp_name=EXP_NAMES)
         
rule load_raw_queue_data:
    input:
        'data-imc-2019/{exp_name}.tar.gz'
    params:
        queue_filename='queue-{exp_name}.txt'
    output:
        temp('data-imc-2019/queue-{exp_name}.txt')
        #'data-imc-2019/queue-{exp_name}.txt'
    shell:
        """
        tar -C data-imc-2019/ -xzvf {input} {params.queue_filename}
        sort -k 2 -o {output} {output} \
        && grep ^.*,.*,.*,.*,.*,.*,.*,.*,.*$ {output} > {output}.tmp \
        && mv {output}.tmp {output}
        """

rule load_exp_description:
    input:
        exp_tarfile='data-imc-2019/{exp_name}.tar.gz'
    params:
        exp_description='{exp_name}.json'
    output:
        'data-imc-2019/{exp_name}.json'
    shell:
        """
        tar -C data-imc-2019/ -xzvf {input.exp_tarfile} {params.exp_description}
        """

rule load_exp_tcpdump:
    input:
        exp_tarfile='data-imc-2019/{exp_name}.tar.gz'
    params:
        exp_tcpdump_log='server-tcpdump-{exp_name}.pcap'
    output:
        tcpdump=temp('data-imc-2019/server-tcpdump-{exp_name}.pcap')
    shell:
        """
        tar -C data-imc-2019/ -xzvf {input.exp_tarfile} {params.exp_tcpdump_log}
        """

rule load_exp_http:
    input:
        exp_tarfile='data-imc-2019/{exp_name}.tar.gz'
    params:
        exp_http_log='http-{exp_name}.pcap'
    output:
        http_pcap=temp('data-imc-2019/http-{exp_name}.pcap')
    shell:
        """
        tar -C data-imc-2019/ -xzvf {input.exp_tarfile} {params.exp_http_log} || touch {output.http_pcap}
        """
        
rule load_description:
    input:
        exp_tarfile='data-imc-2019/{exp_name}.tar.gz'
    params:
        exp_description='{exp_name}.json'
    output:
        description=temp('data-imc-2019/{exp_name}.json')
    shell:
        """
        tar -C data-imc-2019/ -xzvf {input.exp_tarfile} {params.exp_description}
        """
        
rule store_queue_hdf:
    input:
        raw_queue_data='data-imc-2019/queue-{exp_name}.txt'
    output:
        hdf_queue='data-imc-2019/queue-{exp_name}.h5'
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

rule get_tcpdump_analysis:
    input:
        tcpdump='data-imc-2019/server-tcpdump-{exp_name}.pcap',
        queue='data-imc-2019/queue-{exp_name}.h5'
    output:
        tcpdump_analysis='data-imc-2019/{exp_name}.tshark'
    run:
        import pandas as pd
        
        # get ports seen by the queue -- only need this for website flows tho
        with pd.HDFStore(input.queue, mode='r') as hdf_queue:
            df_queue = hdf_queue.select('df_queue')
        queue_seen_ports = df_queue['src'].astype('str').unique()
        ports_filter = 'tcp.port eq {}'.format(' or tcp.port eq '.join(
            queue_seen_ports))

        shell('tshark -2 -r {} -R "{}" -T fields -e tcp.stream -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport -e tcp.time_relative -e tcp.len -e frame.time_relative -E separator=, -E occurrence=f > {}'.format(
                    input.tcpdump, ports_filter, output.tcpdump_analysis))

rule get_tcpprobe:
    input:
        exp_tarfile='data-imc-2019/{exp_name}.tar.gz',
        queue='data-imc-2019/queue-{exp_name}.h5',
        tshark='data-imc-2019/{exp_name}.tshark'
    output:
        tcpprobe='data-imc-2019/tcpprobe-{exp_name}.csv'
    run:
        import sys
        import os
        sys.path.append('/opt/cctestbed/data_analysis')
        from experiment import load_experiments

        exp_name = os.path.basename(input.exp_tarfile)[:-7]

        analyzers = load_experiments(['*{}*'.format(exp_name)], 
                                     remote=False,
                                     force_local=True,
                                     load_queue=True)
        tcpprobe = analyzers[exp_name].df_tcpprobe
        
        
rule get_metric:
    input:
        unpack(get_metric_files)
    output:
        metric='data-imc-2019/{exp_name}.metric'
    run:
        import json
        import pandas as pd
        from cctestbedv2 import Flow, Host
        
        with open(input.description) as f:
            description = json.load(f)

        flow_objs = {}
        for idx, flow in enumerate(description['flows']):
            # reconstruct flow objects from json description
            flow_obj = Flow(*flow)
            host_obj = Host(*flow_obj.client)
            flow_obj = flow_obj._replace(client=host_obj)
            flow_objs[idx] = flow_obj

        
        def is_test_data(df):
            return df['src'].isin(['192.0.0.2','192.0.0.4']) & df['dst'].isin(['192.0.0.2','192.0.0.4'])

        df_tshark = pd.read_csv(input.tshark,
                                header=None,
                                names=['stream','src','srcport',
                                       'dst','dstport','time_relative',
                                       'len','time'])
    
        df_testing = df_tshark.where(lambda df: is_test_data(df)).dropna(how='all')
        df_not_testing = df_tshark.where(lambda df: ~is_test_data(df)).dropna(how='all')
        assert(not df_testing.empty)
        assert(not df_not_testing.empty)
         
        df_testing_start = df_testing.sort_values('time').iloc[0]['time']
        df_not_testing_start = df_not_testing.sort_values('time').iloc[0]['time']
        df_testing_end = df_testing.sort_values('time').iloc[-1]['time']
        df_not_testing_end = df_not_testing.sort_values('time').iloc[-1]['time']
        
        start_time = max(df_testing_start, df_not_testing_start)
        end_time = min(df_not_testing_end, df_testing_end)
        runtime = end_time - start_time

        
        # make sure both flows are running

        df_testing_adjusted = df_testing.where(lambda df: df['time'] >= start_time).dropna(how='all').where(lambda df: df['time'] < end_time).dropna(how='all')
        df_not_testing_adjusted = df_not_testing.where(lambda df: df['time'] >= start_time).dropna(how='all').where(lambda df: df['time'] < end_time).dropna(how='all')
            
        assert(not df_testing_adjusted.empty)
        assert(not df_not_testing_adjusted.empty)

        
        df_testing_bytes = df_testing_adjusted['len'].sum()
        df_not_testing_bytes = df_not_testing_adjusted['len'].sum()

        
        results = {'runtime':runtime,
                   'start_time':start_time,
                   'end_time':end_time,
                   'service_bytes':df_not_testing_bytes,
                   'other_bytes':df_testing_bytes}
                   
        if (flow_objs[1].kind == 'video'):
            df_http = (pd.read_csv(input.http,
                                 header=None,
                                 names=['tcp_stream',
                                        'src_ip',
                                        'src_port',
                                        'dst_ip',
                                        'dst_port',
                                        'time_relative',
                                        'request_uri'])
                      .dropna(how='any')
                      .assign(bitrate=lambda df: (df['request_uri']
                                                  .str
                                                  .extract('/bunny_(\d+)bps/.*')
                                                  .astype('float')))
            )

            df_http = df_http.set_index('time_relative').loc[start_time:end_time]
            
            # get frames received before other flow finishes
            results['metric'] = df_http['bitrate'].mean()
            results['test'] = 'video'
        elif (flow_objs[1].kind == 'apache'):
            assert(df_testing_bytes == df_testing['len'].sum())
            results['metric'] = runtime
            results['test'] = 'apache'
        else:
            if (flow_objs[1].kind == 'iperf') & (len(flow_objs)==17):
                # need to find time first iperf flow stops and make that
                # the end time
                end_time = df_testing_adjusted.where(lambda df: df['srcport'].isin(range(5202,5217))).groupby('srcport')['time_relative'].max().min()
                runtime = end_time - start_time
                df_testing_adjusted = df_testing.where(lambda df: df['time'] >= start_time).dropna(how='all').where(lambda df: df['time'] < end_time).dropna(how='all')
                df_not_testing_adjusted = df_not_testing.where(lambda df: df['time'] >= start_time).dropna(how='all').where(lambda df: df['time'] < end_time).dropna(how='all')

                assert(not df_testing_adjusted.empty)
                assert(not df_not_testing_adjusted.empty)

                df_testing_bytes = df_testing_adjusted['len'].sum()
                df_not_testing_bytes = df_not_testing_adjusted['len'].sum()
                results = {'runtime':runtime,
                           'start_time':start_time,
                           'end_time':end_time,
                           'service_bytes':df_not_testing_bytes,
                           'other_bytes':df_testing_bytes,
                           'test': 'iperf16'}

                results['metric'] = df_testing_bytes / runtime
                
            else:
                results['metric'] = df_testing_bytes / runtime

                
                if 'diffrtt' in wildcards.exp_name:
                    results['test'] = 'diffrtt'
                else:
                    results['test'] = 'iperf1'        
            
        with open(output.metric,'w') as f:
            json.dump(results, f)

            
rule get_http_analysis:
    input:
        http_pcap='data-imc-2019/http-{exp_name}.pcap'
    output:
        http_analysis='data-imc-2019/{exp_name}.http'
    shell:
        """
        tshark -2 -r {input.http_pcap} -T fields -e tcp.stream -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport -e frame.time_relative -e http.request.uri -E separator=, | grep bunny_ > {output.http_analysis} || touch {output.http_analysis}
        """
   
        
rule get_avg_bitrate:
    input:
        http_analysis='data-imc-2019/{exp_name}.http'
    output:
        bitrate='data-imc-2019/{exp_name}.bitrate'
    run:
        import pandas as pd
        import os
        import json
        
        if os.stat(input.http_analysis).st_size == 0:
            shell('touch {output.bitrate}')
            return
        
        df = (pd.read_csv(input.http_analysis,
                         header=None,
                         names=['tcp_stream',
                                'src_ip',
                                'src_port',
                                'dst_ip',
                                'dst_port',
                                'time_relative',
                                'request_uri'])
              .dropna(how='any')
              .assign(bitrate=lambda df: (df['request_uri']
                                          .str
                                          .extract('/bunny_(\d+)bps/.*')
                                          .astype('float')))
        )
        
        per_flow_median = (df
                           .groupby(['src_ip','src_port',
                                     'dst_ip','dst_port'])['bitrate']
                           .mean().median())
        median = df['bitrate'].median()
        mean = df['bitrate'].mean()

        bitrate = {'per_flow_median': per_flow_median,
                   'median': median,
                   'mean': mean}
        with open(output.bitrate, 'w') as f:
            json.dump(bitrate, f)
        

rule scp_results:
    input:
        unpack(get_metric_files_list),
        exp_tarfile='data-imc-2019/{exp_name}.tar.gz',
        metric='data-imc-2019/{exp_name}.metric',
        queue='data-imc-2019/queue-{exp_name}.h5',
        #tcpdump_analysis='data-imc-2019/{exp_name}.tshark',
        #bitrate='data-imc-2019/{exp_name}.bitrate',
        #http='data-imc-2019/{exp_name}.http'
    output:
        compressed_results='{exp_name}.fairness.tar.gz'
    shell:
        """
        tar -czvf {output.compressed_results} {input.metric} {input.exp_tarfile} {input.queue} $(ls data-imc-2019/{wildcards.exp_name}.http) data-imc-2019/{wildcards.exp_name}.tshark  --strip-components=1 && scp -o StrictHostKeyChecking=no -i /users/rware/.ssh/rware-potato.pem {output.compressed_results} ranysha@128.2.208.104:/opt/cctestbed/data-websites/ && rm data-tmp/*{wildcards.exp_name}*
        """
       
    
