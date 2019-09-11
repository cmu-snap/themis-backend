import argparse
import json, os, re
import shlex, subprocess
from datetime import date

CLASSIFY_SNAKEFILE = '/opt/cctestbed/classify_websites.snakefile'
CCALG_PREDICT = '/opt/cctestbed/ccalg_predict.py'
RESULTS_DIR = '/tmp/data-processed'
# Max number of times to rerun an experiment.
RUN_LIMIT = 3

# Parse the btlbw and rtt from an experiment name.
def parse_network_conditions(exp_name):
    bw = r"^(\d+)bw"
    rtt = r"^\d+bw-(\d+)rtt"
    return (re.findall(bw, exp_name)[0], re.findall(rtt, exp_name)[0])


# Classify the CCA of the given websites. Reruns any experiments from ccalg_predict.py
# which are marked invalid by classify_websites.snakefile up to 3 times. Of the final
# labeled flows, labels the website with the majority label or marks as unknown if
# no label has a majority.
def classify_websites(websites):
    for website, url in websites:
        try:
            completed_exps, invalid_exps = run_ccalg_predict(website, url)
            reruns = dict([(network, 1) for network in invalid_exps])

            while any(reruns[network] < 3 for network in invalid_exps):
                network_conditions = []
                for network, exp_name in invalid_exps.items():
                    if reruns[network] == 3:
                        completed_exps.append(exp_name)
                    else:
                        reruns[network] += 1
                        network_conditions.append(network)

                labeled, invalid_exps = run_ccalg_predict(website, url, network_conditions)
                completed_exps.extend(labeled)

            print('Completed classify websits experiments for {}'.format(website))
            print(completed_exps)
            
            predicted_label = predict_label(completed_exps)
            today = date.today().strftime('%y-%m-%d')
            results_filename = '{}/{}-{}.results'.format(RESULTS_DIR, website, today)

            with open(results_filname, 'w') as f:
                f.write('{{ predicted_label: {} }}'.format(predicted_label))

            print('Predicted label {} written to {}'.format(predicted_label, results_filename))

        except Exception as e:
            print(e)


def predict_label(exp_names):
    num_exps = len(exp_names)
    label_counts = {}

    for exp in exp_names:
        results_filename = '{}/{}.results'.format(RESULTS_DIR, exp)
        if os.path.isfile(results_filename):
            with open(results_filename) as f:
                results = json.load(f)
                if results['predicted_label'] in label_counts:
                    label_counts[results['predicted_label']] += 1
                else:
                    label_counts[results['predicted_label']] = 1

    predicted_label = max(label_counts, key=label_counts.get)
    if label_counts[predicted_label] >= num_exps / 2:
        return predicted_label

    return 'unknown'

# Run ccalg_predict.py for a single website and the given network conditions and runs
# classifies each of the resulting experiments. Returns (labeled, invalid) where
#   labeled: list of labeled experiments
#   invalid: dictionary mapping (bw, rtt) to experiment name for all invalid experiments
def run_ccalg_predict(website, url, network_conditions=[], skip_predict=False):
    exp_names = []
    if skip_predict:
        for exp in os.listdir('/tmp/data-raw'):
            exp_names.append(exp[:exp.index('.tar')])
    else:
        network_arg = ' '.join(['--network {} {}'.format(bw, rtt) for bw, rtt in network_conditions])
        cmd = 'python3.6 {} --website {} {} {} --f'.format(CCALG_PREDICT, website, url, network_arg)
        args = shlex.split(cmd)
        process = subprocess.run(args, stdout=subprocess.PIPE)
        if process.returncode != 0:
            raise Exception('Could not run experiments for website: {} url: {} network: '.format(
                website, url, ' '.join(network_conditions)))
    
        # Turn stdout bytes into string
        output = process.stdout.decode('utf-8')
        regex_name=r"exp_name=(.+)\n"
        exp_names = re.findall(regex_name, output)

    invalid_exps = run_classify_snakefile(exp_names)
    labeled = [name for name in exp_names if name not in invalid_exps]
    invalid = dict([(parse_network_conditions(name), name) for name in invalid_exps])
    return (labeled, invalid)


# Runs classify_websites.snakefile for the given experiment names and returns a list
# of the experiment names which were marked invalid.
def run_classify_snakefile(exp_names):
    cmd = 'snakemake --config exp_name="{}" -s {} --latency-wait 10'.format(' '.join(exp_names), CLASSIFY_SNAKEFILE)
    args = shlex.split(cmd)
    process = subprocess.run(args, stdout=subprocess.PIPE)
    if process.returncode != 0:
        raise Exception('classify_websites.snakefile failed on {}'.format('\n'.join(exp_names)))

    invalid_exps = []

    for exp in exp_names:
        results_filename = '{}/{}.results'.format(RESULTS_DIR, exp)
        if os.path.isfile(results_filename):
            with open(results_filename) as f:
                results = json.load(f)
                if results['mark_invalid']:
                    invalid_exps.append(exp)

    return invalid_exps


def parse_args():
    parser = argparse.ArgumentParser(
            description='Runs the classification pipeline for each of the given websites to classify the congestion control algorithm of each website')
    parser.add_argument(
            '--website',
            nargs=2,
            action='append',
            required='True',
            metavar=('WEBSITE', 'FILE_URL'),
            dest='websites')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = parse_args()
    classify_websites(args.websites)
