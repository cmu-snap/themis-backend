import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import subprocess, glob, json, os, sys
import argparse

COLORS = plt.rcParams['axes.prop_cycle'].by_key()['color']

DIR = os.path.dirname(os.path.realpath(sys.argv[0]))
DATA_DIR = '/tmp/data-websites'
df_tests = pd.read_csv('{}/fairness_test_description.csv'.format(DIR)) 

def make_plot(website, ccas, exp_dir):
    results = get_fairness_results(website, exp_dir)
    paths = []

    for cca in ccas:
        df_to_plot = (pd
                .DataFrame(results)
                .drop_duplicates()
                .assign(fairness=lambda x: x.apply(
                    lambda df: (df['metric'] / df['baseline']) * (1/df['expected_baseline']) if df['test']!='webpage' else (df['baseline'] / df['metric']) * (1/df['expected_baseline']), axis=1))
                .groupby(['cca','queue_bdp','test'])['fairness']
                .median()
                .unstack(0)
                .reset_index()
                .assign(test=lambda x: x.apply(lambda df:'{}\n{:g} BDP'.format(df['test'],df['queue_bdp']), axis=1))
                ).set_index('test').sort_index(ascending=True)[ccas]
        
        ax = plot_fairness(df_to_plot[cca].sort_index(), '')
        path = '{}/{}/{}-vs-{}.png'.format(DATA_DIR, exp_dir, website, cca)
        ax.figure.savefig(path, bbox_inches='tight')
        paths.append(path)

    return paths

def plot_fairness(df, title, **kwargs):
    from math import pi
    
    fig = plt.figure(figsize=(16,4))
    #ax = fig.add_subplot(111, polar=True)

    # number of variable
    categories=df.index
    N = len(categories)

    # We are going to plot the first line of the data frame.
    # But we need to repeat the first value to close the circular graph:
    values=df.values.tolist()
    values += values[:1]
    #values

    # What will be the angle of each axis in the plot? (we divide the plot / number of variable)
    angles = [n / float(N) * 2 * pi for n in range(N)]
    angles += angles[:1]

    # Initialise the spider plot
    ax = plt.subplot(111, polar=True)

    # Draw one axe per variable + add labels labels yet
    plt.xticks(angles[:-1], categories, color='grey', size=13)
    ax.tick_params(axis='x', pad=20)

    # Draw ylabels
    ax.set_rlabel_position(10)
    plt.yticks([0.5,1.0,1.5], ["0.5","1.0","1.5"], color="black", size=10, fontweight='bold')
    plt.ylim(0,2)

    # Highlight 1.0 line
    gridlines = ax.yaxis.get_gridlines()
    gridlines[1].set_color(COLORS[2])
    gridlines[1].set_linewidth(2)
    gridlines[1].set_linestyle('--')

    # Plot data
    ax.plot(angles, values, linewidth=1, linestyle='solid', marker='o', **kwargs)

    # Fill area
    ax.fill(angles, values, COLORS[0], alpha=0.1)
    ax.set_title(title, pad=45)

    fig.tight_layout()
    
    return ax


def get_fairness_results(website_name, exp_dir):
    all_testing_results = []
    for _, test in df_tests.iterrows():
        baseline_exp_pattern = '{}/{}.fairness.tar.gz'.format(DATA_DIR, test['baseline_name_pattern'])
        test_exp_pattern = '{}/{}/{}.metric'.format(DATA_DIR, exp_dir, test['test_name_pattern'].format(website_name))
        baseline_exp_filenames = glob.glob(baseline_exp_pattern)
        test_exp_filenames = glob.glob(test_exp_pattern)
        num_testing = len(test_exp_filenames)
        num_baseline = len(baseline_exp_filenames)
        if num_testing > num_baseline:
            test_exp_filenames = sorted(test_exp_filenames)[-3:]
        print(num_testing, num_baseline, test['test_name'])

        for testing_filename, baseline_filename in zip(test_exp_filenames, baseline_exp_filenames):

            with open(testing_filename) as f:
                testing_results = json.load(f)
                total_runtime = testing_results['runtime']
            if testing_results['test'] == 'video':
                http = baseline_filename[:-len('.features.tar.gz')] + '.http'
                if not os.path.isfile(http):
                    subprocess.run('tar -C {}/ -xzvf {} data-processed/{} --strip-components=1'.format(
                        DATA_DIR, baseline_filename, os.path.basename(http)), 
                        check=True, shell=True)
                    assert(os.path.isfile(http))

                df_http = (pd.read_csv(http,
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
                baseline_metric = (df_http
                                   .set_index('time_relative')
                                   .sort_index()[:total_runtime])['bitrate'].mean()
                testing_results['baseline'] = baseline_metric
                testing_results['testing_exp_name'] = os.path.basename(testing_filename)[:-len('.tshark')]
                testing_results['baseline_exp_name'] = os.path.basename(baseline_filename)[:-len('.baseline')]
                testing_results['test_name'] = test['test_name']
                testing_results.update(test.drop('Unnamed: 0').to_dict())
                testing_results['expected_baseline'] = (2.5/3.7)
                all_testing_results.append(testing_results)
            elif testing_results['test'] == 'apache':
                tshark = baseline_filename[:-len('.features.tar.gz')] + '.tshark'
                if not os.path.isfile(tshark):
                    subprocess.run('tar -C {}/ -xzvf {} data-processed/{} --strip-components=1'.format(
                        DATA_DIR, baseline_filename, os.path.basename(tshark)), 
                        check=True, shell=True)
                    assert(os.path.isfile(tshark))
                df_tshark = pd.read_csv(tshark,
                                         header=None,
                                         names=['stream','src','srcport',
                                                'dst','dstport','time_relative','len'])
                baseline_metric = df_tshark['time_relative'].max()
                testing_results['baseline'] = baseline_metric
                testing_results['testing_exp_name'] = os.path.basename(testing_filename)[:-len('.metric')]
                testing_results['baseline_exp_name'] = os.path.basename(baseline_filename)[:-len('.baseline')]
                testing_results['test_name'] = test['test_name']
                testing_results.update(test.drop('Unnamed: 0').to_dict())
            elif (testing_results['test'] == 'iperf1') | (testing_results['test'] == 'iperf16'):
                tshark = baseline_filename[:-len('.features.tar.gz')] + '.tshark'
                if not os.path.isfile(tshark):
                    subprocess.run('tar -C {}/ -xzvf {} data-processed/{} --strip-components=1'.format(
                        DATA_DIR, baseline_filename, os.path.basename(tshark)), 
                        check=True, shell=True)
                    assert(os.path.isfile(tshark))
                df_tshark = pd.read_csv(tshark,
                                header=None,
                                names=['stream','src','srcport',
                                       'dst','dstport','time_relative','len'])

                baseline_metric = df_tshark.set_index('time_relative').sort_index()[:total_runtime]['len'].sum() / total_runtime

                testing_results['baseline'] = baseline_metric
                testing_results['testing_exp_name'] = os.path.basename(testing_filename)[:-len('.metric')]
                testing_results['baseline_exp_name'] = os.path.basename(baseline_filename)[:-len('.baseline')]
                testing_results['test_name'] = test['test_name']
                testing_results.update(test.drop('Unnamed: 0').to_dict())
            if testing_results['test'] == 'apache':
                testing_results['test'] = 'webpage'
            all_testing_results.append(testing_results)
    return all_testing_results

def parse_args():
    parser = argparse.ArgumentParser(description='Create plots for fairness experiments')
    parser.add_argument('--website', required=True, help='Website used in the experiment')
    parser.add_argument('--ccas', nargs='+', dest='ccas', required=True, help='Competing CCAs used in the experiment')
    parser.add_argument('--exp_dir', required=True, help='Experiment data directory')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()
    paths = make_plot(args.website, args.ccas, args.exp_dir)
    print(' '.join(paths))