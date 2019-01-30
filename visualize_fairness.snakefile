
import pandas as pd
import glob

# youtube broken
#WEBSITE_NAMES=['explorebk.com','ditchingsuburbia.com','cypress.io','asset-intertech.com','kingsoftstore.com', 'nttdata.com']
WEBSITE_NAMES=['youtube.com']
TESTS=pd.read_csv('fairness_test_description.csv').set_index('test_name')
TEST_NAMES = list(TESTS.index)
EXP_NAME_PATTERN='data-websites/{exp_name, .*(' + '|'.join(WEBSITE_NAMES) + ').*}.fairness.tar.gz'

EXP_NAMES, = glob_wildcards(EXP_NAME_PATTERN)
EXP_NAMES = '5bw-75rtt-16q-youtube.com-10svideo-bbr-240s-20190123T185430'

def get_metric_files(wildcards):
    if 'video' in wildcards.exp_name:
        return {'http': 'data-websites/{}.http'.format(wildcards.exp_name),
                'description': 'data-websites/{}.json'.format(wildcards.exp_name),
                'tshark': 'data-websites/{}.tshark'.format(wildcards.exp_name)}
    else:
        return {'tshark': 'data-websites/{}.tshark'.format(wildcards.exp_name),
                'description': 'data-websites/{}.json'.format(wildcards.exp_name)}
    
def get_all_test_results_input(wildcards):
    all_test_results = {}
    if 'video' in wildcards.test_name:
        metric_file_suffix = '.http'
    else:
        metric_file_suffix = '.tshark'
    baseline_pattern = TESTS.loc[wildcards.test_name]['baseline_name_pattern']
    test_pattern = TESTS.loc[wildcards.test_name]['test_name_pattern'].format(wildcards.website_name)
    return {
        'baseline_metrics_files':glob.glob('data-websites/{}{}'.format(
            baseline_pattern,
            metrics_file_suffix)),
        'test_metrics':glob.glob('data-websites/{}.metrics'.format(test_pattern))}

def get_all_website_results_input(wildcards):
    return expand('data-websites/' + wildcards.website_name + ':{test_name}.sitefairness',test_name=TEST_NAMES)


rule all:
    input:
        expand('data-websites/{exp_name}.metric',exp_name=EXP_NAMES)
        #expand('data-websites/{website_name}.sitefairness', website_name=WEBSITE_NAMES)
        
rule load_tarfile:
    input:
        exp_tarfile='data-websites/{exp_name}.fairness.tar.gz'
    params:
        raw_tarfile='{exp_name}.tar.gz'
    output:
        raw_tarfile=temp('data-websites/{exp_name, .*\d}.tar.gz')
    shell:
        """
        tar -C data-websites/ -xzvf {input.exp_tarfile} data-raw/{params.raw_tarfile} --strip-components=1
        """

rule load_exp_description:
    input:
        exp_tarfile='data-websites/{exp_name}.tar.gz'
    params:
        exp_description='{exp_name}.json'
    output:
        'data-websites/{exp_name}.json'
    shell:
        """
        tar -C data-websites/ -xzvf {input.exp_tarfile} {params.exp_description}
        """

        
rule load_tshark:
    input:
        exp_tarfile='data-websites/{exp_name}.fairness.tar.gz'
    params:
        tshark='{exp_name}.tshark'
    output:
        'data-websites/{exp_name}.tshark'
    shell:
        """
        tar -C data-websites/ -xzvf {input.exp_tarfile} data-processed/{params.tshark} --strip-components=1
        """

rule load_http:
    input:
        exp_tarfile='data-websites/{exp_name}.fairness.tar.gz'
    params:
        http='{exp_name}.http'
    output:
        'data-websites/{exp_name}.http'
    shell:
        """
        tar -C data-websites/ -xzvf {input.exp_tarfile} data-processed/{params.http} --strip-components=1
        """

        
rule get_metric:
    input:
        unpack(get_metric_files)
    output:
        metric='data-websites/{exp_name}.metric'
    run:
        import json
        import pandas as pd
        from cctestbedv2 import Flow, Host
        
        with open(input.description) as f:
            description = json.load(f)

        df_tshark = pd.read_csv(input.tshark,
                                header=None,
                                names=['stream','src','srcport',
                                       'dst','dstport','time_relative','len'])

        flow_objs = {}
        for idx, flow in enumerate(description['flows']):
            # reconstruct flow objects from json description
            flow_obj = Flow(*flow)
            host_obj = Host(*flow_obj.client)
            flow_obj = flow_obj._replace(client=host_obj)
            flow_objs[idx] = flow_obj
            
        if  (flow_objs[1].kind == 'iperf') & (len(flow_objs)==2):
            df_flow_runtimes = (df_tshark
             .where(lambda df: df['time_relative']==0).dropna(how='all')
             .sort_index()
             .assign(max_time=df_tshark.groupby('stream')['time_relative'].idxmax().sort_index().values)
            )


            last_flow_start = df_flow_runtimes.iloc[-1]
            assert(last_flow_start['dstport']==443) # should be website flow
            last_flow_start_index = last_flow_start.name
            if flow_objs[0].kind == 'chrome':
                assert((df_tshark.groupby('dstport')['len'].sum() > 10000000).sum()>=2)
                first_flow_end = df_flow_runtimes.set_index('srcport').loc[5556]
            else:
                first_flow_end = df_flow_runtimes.loc[df_flow_runtimes['max_time'].idxmin()]

            first_flow_end_index = first_flow_end['max_time']
            total_runtime = df_tshark.iloc[first_flow_end_index]['time_relative']

            metric = (df_tshark
             .loc[last_flow_start_index: first_flow_end_index]
             .groupby('dstport')
             ['len'].sum() / total_runtime
            )[5202]
            
            if 'diffrtt' in wildcards.exp_name:
                test='diffrtt'
            else:
                test='iperf1'
            results={'metric': metric,
                     'test': test,
                     'runtime': total_runtime}
        elif (flow_objs[1].kind == 'iperf') & (len(flow_objs)==17):

            df_flow_runtimes = (df_tshark
                                .where(lambda df: df['time_relative']==0).dropna(how='all')
                                .sort_index()
                                .assign(max_time=df_tshark.groupby('stream')['time_relative'].idxmax().sort_index().values)
            )

            last_flow_start = df_flow_runtimes.iloc[-1]
            last_flow_start_index = last_flow_start.name
            first_flow_end = df_flow_runtimes.loc[df_flow_runtimes['max_time'].idxmin()]
            first_flow_end_index = first_flow_end['max_time']
            total_runtime = df_tshark.iloc[first_flow_end_index]['time_relative']
            
            metric = (df_tshark
             .loc[last_flow_start_index:first_flow_end_index]
             .where(lambda df: df['dstport'].isin(list(range(5202,5218))))
             .dropna(how='all')['len'].sum() / total_runtime
            )
            test='iperf16'
            results={'metric': metric,
                     'test': test,
                     'runtime': total_runtime}
        elif (flow_objs[1].kind == 'apache'):
            assert(len(flow_objs)==2)
            df_flow_runtimes = (df_tshark
                                .where(lambda df: df['time_relative']==0).dropna(how='all')
                                .sort_index()
                                .assign(max_time=df_tshark.groupby('stream')['time_relative'].idxmax().sort_index().values)
            )

            assert(df_flow_runtimes.shape[0]>1) # make sure both flows running
            last_flow_start = df_flow_runtimes.iloc[-1]
            assert(last_flow_start['dstport']==1234) # should be apache flow
            last_flow_start_index = last_flow_start.name
            first_flow_end = df_flow_runtimes.loc[df_flow_runtimes['max_time'].idxmin()]
            assert(first_flow_end['dstport']==1234) # should be apache flow
            first_flow_end_index = first_flow_end['max_time']
            total_runtime = df_tshark.iloc[first_flow_end_index]['time_relative']

            # flow completion time
            metric = (df_tshark
             .loc[last_flow_start_index: first_flow_end_index]
             .sort_values('time_relative').groupby('dstport').last()['time_relative'][1234]
            ) # isn't this the same as total_runtime?
            #assert(metric==total_runtime)
            test='apache'
            results={'metric': metric,
                     'test': test,
                     'runtime': total_runtime}
        elif (flow_objs[1].kind == 'video'):
            df_flow_runtimes = (df_tshark
                                .where(lambda df: df['time_relative']==0).dropna(how='all')
                                .sort_index()
                                .assign(max_time=df_tshark.groupby('stream')['time_relative'].idxmax().sort_index().values)
            )
            
            last_flow_start = df_flow_runtimes.iloc[-1]
            if flow_objs[0].kind != 'chrome':
                assert(last_flow_start['dstport']==int(1234)) # should be video flow -- need for calc to work

            if flow_objs[0].kind == 'chrome':
                #assert((df_tshark.groupby('dstport')['len'].sum() > 10000000).sum()>=2
                first_flow_end = df_flow_runtimes.set_index('dst').loc['192.0.0.4'].sort_values('max_time').iloc[-1]
            else:
                first_flow_end = df_flow_runtimes.loc[df_flow_runtimes['max_time'].idxmin()]

            first_flow_end_index = first_flow_end['max_time']
            total_runtime = df_tshark.iloc[first_flow_end_index]['time_relative']

                
            last_flow_start_index = last_flow_start.name
            #first_flow_end = df_flow_runtimes.loc[df_flow_runtimes['max_time'].idxmin()]
            #assert(first_flow_end['dstport']==1234) # doesn't have to be video flow
            #first_flow_end_index = first_flow_end['max_time']
            total_runtime = df_tshark.iloc[first_flow_end_index]['time_relative']

            
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

            max_index_http = len(df_tshark.where(lambda df:(df['dstport']==1234) & (df['len']>0)).dropna(how='all')[:first_flow_end_index])
            df_http = df_http.loc[:max_index_http]

            # get frames received before other flow finishes
            per_flow_median = (df_http
                                   .groupby(['src_ip','src_port',
                                             'dst_ip','dst_port'])['bitrate']
                                   .mean().median())

            metric = df_http['bitrate'].mean()
            test = 'video'
            results={'metric': metric,'test': test, 'runtime': total_runtime}
        with open(output.metric,'w') as f:
            json.dump(results, f)

rule get_test_results:
    input:
        get_all_test_results_input
    output:
        test_results = 'data-websites/{website_name}:{test_name}.fairness'
    run:
        shell('touch {output.test_results}')

rule merge_website_results:
    input:
        get_all_website_results_input
    output:
        website_results = 'data-websites/{website_name}.sitefairness'
    run:
        shell('touch {output.website_results}')
