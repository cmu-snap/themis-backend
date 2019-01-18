# requires wireshark, tcpdump
import glob
import os
import json

workdir: "/tmp"
         
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
BYTES_TO_BITS = 8
BITS_TO_MEGABITS = 1.0 / 1e6

NTWRK_CONDITIONS = [(5,35,16), (5,85,64), (5,130,64), (5,275,128), (10,35,32), (10,85,128), (10,130,128), (10,275,256), (15,35,64), (15,85,128), (15,130,256), (15,275,512)]
CCAS = ['cubic','reno','bbr', 'bic', 'cdg', 'highspeed', 'htcp', 'hybla', 'illinois', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']
        
#EXP_NAMES, = glob_wildcards('data-raw/{exp_name}.tar.gz')
EXP_NAMES, = glob_wildcards('data-tmp/{exp_name}.tar.gz')           
    
# specify final output of the pipeline
rule all:
    input:
         #all_results=expand('{exp_name}.fairness.tar.gz', exp_name=EXP_NAMES)
         all_results=expand('data-processed/{exp_name}.bitrate',exp_name=EXP_NAMES)
         
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

rule load_exp_http:
    input:
        exp_tarfile='data-raw/{exp_name}.tar.gz'
    params:
        exp_http_log='http-{exp_name}.pcap'
    output:
        http_pcap=temp('data-raw/http-{exp_name}.pcap')
    shell:
        """
        tar -C data-raw/ -xzvf {input.exp_tarfile} {params.exp_http_log} || touch {output.http_pcap}
        """
        
rule load_description:
    input:
        exp_tarfile='data-raw/{exp_name}.tar.gz'
    params:
        exp_description='{exp_name}.json'
    output:
        description=temp('data-raw/{exp_name}.json')
    shell:
        """
        tar -C data-raw/ -xzvf {input.exp_tarfile} {params.exp_description}
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

rule get_tcpdump_analysis:
    input:
        tcpdump='data-raw/server-tcpdump-{exp_name}.pcap',
        queue='data-processed/queue-{exp_name}.h5'
    output:
        tcpdump_analysis='data-processed/{exp_name}.tshark'
    run:
        import pandas as pd
        
        # get ports seen by the queue -- only need this for website flows tho
        with pd.HDFStore(input.queue, mode='r') as hdf_queue:
            df_queue = hdf_queue.select('df_queue')
        queue_seen_ports = df_queue['src'].astype('str').unique()
        ports_filter = 'tcp.port eq {}'.format(' or tcp.port eq '.join(
            queue_seen_ports))

        shell('tshark -2 -r {} -R "{}" -T fields -e tcp.stream -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport -e tcp.time_relative -e tcp.len -E separator=, > {}'.format(
                    input.tcpdump, ports_filter, output.tcpdump_analysis))

        
rule get_goodput:
    input:
        tcpdump_analysis='data-processed/{exp_name}.tshark',
        description='data-raw/{exp_name}.json'
    output:
        goodput='data-processed/{exp_name}.goodput',
    run:
        import json
        import pandas as pd
        from cctestbedv2 import Flow, Host

        with open(input.description) as f:
            description = json.load(f)

        df_tshark = pd.read_csv(input.tcpdump_analysis,
                                header=None,
                                names=['stream','src','srcport',
                                       'dst','dstport','time_relative','len'])
        
        df_goodput = (df_tshark
                      .groupby('stream')
                      .agg({'src':'first','srcport':'first','dst':'first',
                            'dstport':'first','len':'sum','time_relative':'last'})
                      .assign(goodput=lambda df: (df['len'] / df['time_relative']) * BYTES_TO_BITS * BITS_TO_MEGABITS)
                      .rename({'time_relative':'fct'}, axis=1)
        )
        
        flow_ports = {}
        for idx, flow in enumerate(description['flows']):
            # reconstruct flow objects from json description
            flow_obj = Flow(*flow)
            host_obj = Host(*flow_obj.client)
            flow_obj = flow_obj._replace(client=host_obj)
            
            if flow_obj.kind == 'website':
                website_ip = flow_obj.client.ip_wan
                flow_port = df_goodput[df_goodput['dst'] == website_ip]['srcport'].iloc[0]
            elif flow_obj.kind == 'iperf':
                flow_port = flow_obj.client_port
            elif flow_obj.kind == 'apache':
                flow_port = df_goodput[df_goodput['dstport'] == 1234]['srcport'].iloc[0]
            elif flow_obj.kind == 'video':
                flow_port = None

            assert(not flow_port in flow_ports)
            flow_ports[flow_port] = idx
            
        num_flow = pd.Series(flow_ports)
        num_flow.name = 'num_flow'
        df_goodput = df_goodput.set_index('srcport').join(num_flow)
        df_goodput.to_csv(output.goodput)
        

rule get_http_analysis:
    input:
        http_pcap='data-raw/http-{exp_name}.pcap'
    output:
        http_analysis='data-processed/{exp_name}.http'
    shell:
        """
        tshark -2 -r {input.http_pcap} -T fields -e tcp.stream -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport -e frame.time_relative -e http.request.uri -E separator=, | grep bunny_ > {output.http_analysis}
        """
   
        
rule get_avg_bitrate:
    input:
        http_analysis='data-processed/{exp_name}.http'
    output:
        bitrate='data-processed/{exp_name}.bitrate'
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
        exp_tarfile='data-raw/{exp_name}.tar.gz',
        goodput='data-processed/{exp_name}.goodput',
        queue='data-processed/queue-{exp_name}.h5',
        tcpdump_analysis='data-processed/{exp_name}.tshark',
        bitrate='data-processed/{exp_name}.bitrate',
        http='data-processed/{exp_name}.http'
    output:
        compressed_results='{exp_name}.fairness.tar.gz'
    shell:
        """
        tar -czvf {output.compressed_results} {input.goodput} {input.exp_tarfile} {input.queue} {input.tcpdump_analysis} {input.bitrate} {input.http} && scp -o StrictHostKeyChecking=no -i /users/rware/.ssh/rware-potato.pem {output.compressed_results} ranysha@128.2.208.104:/opt/cctestbed/data-websites/ && rm data-tmp/*{wildcards.exp_name}*
        """
       
    
