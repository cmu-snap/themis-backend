import glob

NTWRK_CONDITIONS = [(5,35,16), (5,85,64), (5,130,64), (5,275,128), (10,35,32), (10,85,128), (10,130,128), (10,275,256), (15,35,64), (15,85,128), (15,130,256), (15,275,512)]
CCAS = ['cubic','reno','bbr', 'bic', 'cdg', 'highspeed', 'htcp', 'hybla', 'illinois', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']

rtt_diffs = [1, 1+.1, 1-.1, 1+.05, 1-.05, 1+.25, 1-.25,1+.5,1-.5,1+.75,1-.75,1+1]
LOCAL_EXPS_DICT = {}
for bw, rtt, q in NTWRK_CONDITIONS:
    for rtt_diff in rtt_diffs:
        testing_exp = '{}bw-{}rtt-{}q'.format(bw, int(rtt*rtt_diff), q)
        LOCAL_EXPS_DICT[testing_exp] = []
        for exp in glob.glob('/opt/cctestbed/data-training/*{}bw-{}rtt-{}q-local-*.features'.format(bw, rtt, q)):
            LOCAL_EXPS_DICT[testing_exp].append(os.path.basename(exp)[:-9])
        assert(len(LOCAL_EXPS_DICT[testing_exp]) == len(CCAS))

WEBSITE_RESULTS_OUTPUT='data-websites/classify-websites-20181230.csv'

EXP_NAMES, = glob_wildcards('data-websites/{exp_name}.website.tar.gz')


def get_local_exps(wildcards):
    import re
    # made this regex specific to webite experiments
    ntwrk_conditions = re.match('(\d+bw-\d+rtt-\d+q).*',
                                wildcards.exp_name).groups()[0]
    experiments = LOCAL_EXPS_DICT[ntwrk_conditions]
    return experiments


def get_local_exps_features(wildcards):
    experiments = get_local_exps(wildcards)
    return expand('data-training/{exp_name}.features',
                  exp_name=experiments)

rule all:
    input:
        expand('graphics/{exp_name}-classify.png', exp_name=EXP_NAMES),
        

rule load_results:
    input:
        tarfile='data-websites/{exp_name}.website.tar.gz'
    output:
        result=temp('data-websites/{exp_name}.results')
    params:
        tarfile_fullpath='/opt/cctestbed/data-websites/{exp_name}.website.tar.gz',
        results_tarpath='data-processed/{exp_name}.results'
    shell:
        """
        tar -C /opt/cctestbed/data-websites/ -xzvf {params.tarfile_fullpath} {params.results_tarpath} --strip-components=1
        """

        
rule load_features:
    input:
        tarfile='data-websites/{exp_name}.website.tar.gz'
    output:
        features=temp('data-websites/{exp_name}.features')
    params:
        tarfile_fullpath='/opt/cctestbed/data-websites/{exp_name}.website.tar.gz',
        features_tarpath='data-processed/{exp_name}.features'
    shell:
        """
        tar -C /opt/cctestbed/data-websites/ -xzvf {params.tarfile_fullpath} {params.features_tarpath} --strip-components=1
        """

rule merge_results:
    input:
        results=expand('data-websites/{exp_name}.results', exp_name=EXP_NAMES),
    output:
        all_results=WEBSITE_RESULTS_OUTPUT
    run:
        import pandas as pd
        import json

        all_exp_results = []
        for exp_results in input.results:
            with open(exp_results) as f:
                all_exp_results.append(json.load(f))
        df_all_results = pd.DataFrame(all_exp_results)
        df_all_results.to_csv(output.all_results, index=False)
    

rule plot_results:
    input:
        results='data-websites/{exp_name}.results',
        features='data-websites/{exp_name}.features',
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
        df_training = pd.read_csv('data-training/{}.features'.format(training_exp_name)).squeeze()
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
