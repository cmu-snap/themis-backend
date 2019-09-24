import argparse, logging
import glob, json, os, re
import shlex, subprocess
import matplotlib.pyplot as plt, numpy as np
from datetime import datetime
from logging.config import fileConfig

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

CLASSIFY_SNAKEFILE = os.path.join(CURRENT_DIR, 'classify_websites.snakefile')
CCALG_PREDICT = os.path.join(CURRENT_DIR, 'ccalg_predict.py')
LOGGING_CONFIG = os.path.join(CURRENT_DIR, 'classify_logging_config.ini')

DATA_PROCESSED = '/tmp/data-processed'
RESULTS_FILENAME = '{}/{}.results'
DATA_RAW = '/tmp/data-raw'
DATA_TMP = '/tmp/data-tmp'
DATA_TRAINING = os.path.join(CURRENT_DIR, 'data-training')

# Max number of times to rerun an experiment.
RUN_LIMIT = 3

# Parse the btlbw and rtt from an experiment name.
def parse_network_conditions(exp_name):
    bw = r"^(\d+)bw"
    rtt = r"^\d+bw-(\d+)rtt"
    return (re.findall(bw, exp_name)[0], re.findall(rtt, exp_name)[0])

# Remove all files with the given experiment name.
def remove_experiment(exp_name, exp_dir):
    pattern = '{}/{}*'
    files = glob.glob(pattern.format(DATA_RAW, exp_name))
    files.extend(glob.glob(pattern.format(DATA_TMP, exp_name)))
    files.extend(glob.glob(pattern.format(exp_dir, exp_name)))
    files.extend(glob.glob(pattern.format('/tmp', exp_name)))

    logging.info('Removing files for experiment {}'.format(exp_name))

    for f in files:
        os.remove(f)


def get_features(directory, exp_name, queue_size):
    features = []
    with open('{}/{}.features'.format(directory, exp_name)) as f:
        lines = f.readlines()[1:]
        features = [float(l.strip()) * queue_size for l in lines]
    return features


# For each of the given experiments, creates and saves a plot of the
# queue occupancy of both the experiment and the training data for the
# experiment's predicted label.
def plot_queue_occupancy(website, exp_names, exp_dir):
    logging.info('Creating plots for {}'.format(website))
    plot_dir = exp_dir + '/plots'
    if not os.path.exists(plot_dir):
        os.makedirs(plot_dir)

    features = '{}/{}.features'
    for name in exp_names:
        try:
            with open(RESULTS_FILENAME.format(exp_dir, name)) as f:
                results = json.load(f)
                queue_size = results['queue_size']
                closest_training = results['closest_exp_name']
                network_conditions = results['ntwrk_conditions']

                training_features = get_features(DATA_TRAINING, closest_training, queue_size)
                exp_features = get_features(exp_dir, name, queue_size)

                rtt = results['rtt']
                length = min(len(exp_features), len(training_features))
                time = np.arange(0, length * rtt, rtt).tolist()
                # Convert time from ms to s
                time[:] = [t / 1000 for t in time]

                closest_label = closest_training.split('-')[0]

                f, ax = plt.subplots()
                plt.plot(time, exp_features[:length], label=website)
                plt.plot(time, training_features[:length], label=closest_label + '-training')
                plt.ylabel('queue occupancy ewna (packets)')
                plt.xlabel('time (s)')
                plt.title('{}, predicted={}, network={}'.format(website, results['predicted_label'], network_conditions))
                text = 'dtw distance={}\ninvalid={}'.format(round(results[closest_label], 2), results['mark_invalid'])
                plt.text(0.3, 0.05, text, transform=ax.transAxes)
                plt.legend()
                plot_name = '{}/{}.png'.format(plot_dir, network_conditions)
                plt.savefig(plot_name)
                logging.info('Saved plot {}'.format(plot_name))

        except Exception as e:
            logging.exception(e)
            print(e)

    print('Finished queue occupancy plots')

# Classify the CCA of the given websites. Reruns any experiments from ccalg_predict.py
# which are marked invalid by classify_websites.snakefile up to 3 times. Of the final
# labeled flows, labels the website with the majority label or marks as unknown if
# no label has a majority.
def classify_websites(websites):
    for website, url in websites:
        logging.info('Starting classification for {} {}'.format(website, url))
        try:
            # Make directory for results
            today = datetime.now().strftime('%Y%m%dT%H%M%S')
            exp_dir = '{}/{}'.format(DATA_PROCESSED, website + '-' + today)
            if not os.path.exists(exp_dir):
                os.makedirs(exp_dir)

            completed_exps, invalid_exps = run_ccalg_predict(website, url, exp_dir)
            logging.info('Valid experiments {}'.format(completed_exps.values()))
            reruns = dict([(network, 1) for network in invalid_exps])

            while len(reruns) > 0:
                logging.info('Valid experiments {}'.format(completed_exps.values()))
                network_conditions = []
                for network, exp_name in invalid_exps.items():
                    if reruns[network] == RUN_LIMIT:
                        completed_exps[network] = exp_name
                        reruns.pop(network)
                    else:
                        remove_experiment(exp_name, exp_dir)
                        reruns[network] += 1
                        network_conditions.append(network)

                if len(network_conditions) > 0:
                    logging.info('Rerunning network conditions {}'.format(network_conditions))
                    labeled, invalid_exps = run_ccalg_predict(website, url, exp_dir, network_conditions)
                    for network, exp_name in labeled.items():
                        reruns.pop(network)
                        completed_exps[network] = exp_name
                        
            logging.info('Completed classification experiments for website {} url {}'.format(website, url))
            results_filename = output_results(website, url, completed_exps.values(), exp_dir)
            
        except Exception as e:
            logging.exception(e)
            print(e)

# Outputs the final classification for the given website using the experiments
# in exp_names. Returns the name of the results file.
def output_results(website, url, exp_names, exp_dir):
    predicted_label = predict_label(website, url, exp_names, exp_dir)
    results_filename = RESULTS_FILENAME.format(exp_dir, website)
    keys = ['predicted_label',
            'mark_invalid',
            'closest_distance',
            'bw_too_low',
            'dist_too_high',
            'loss_too_high']

    with open(results_filename, 'w') as f:
        results = { 'website': website,
                    'url': url,
                    'predicted_label': predicted_label,
                    'experiments': [] }

        for name in exp_names:
            exp = { 'name': name }
            with open(RESULTS_FILENAME.format(exp_dir, name)) as exp_file:
                exp_results = json.load(exp_file)
                exp.update(dict([(k, exp_results[k]) for k in keys]))

            results['experiments'].append(exp)
        
        j = json.dumps(results, indent=2)
        predicted_logging = 'Predicted label {} for {} written to {}'.format(predicted_label, website, results_filename)
        print(predicted_logging)
        print(j)
        print(j, file=f)
        logging.info(predicted_logging)

    plot_queue_occupancy(website, exp_names, exp_dir)

    return results_filename


# Predict the label for the given website from the experiments in exp_names.
# If a label has a strict majority, the website is classified as that label.
# Otherwise the website is classified as unknown. Experiments marked as invalid
# are considered unknown.
def predict_label(website, url, exp_names, exp_dir):
    logging.info('Predicting label for website {} url {}'.format(website, url))

    num_exps = len(exp_names)
    label_counts = {}

    for exp in exp_names:
        results_filename = RESULTS_FILENAME.format(exp_dir, exp)
        if os.path.isfile(results_filename):
            with open(results_filename) as f:
                results = json.load(f)
                if results['mark_invalid']:
                    logging.info('Experiment {} marked invalid'.format(exp))
                    if 'unknown' in label_counts:
                        label_counts['unknown'] += 1
                    else:
                        label_counts['unknown'] = 1
                else:
                    label = results['predicted_label']
                    logging.info('Experiment {} labeled {}'.format(exp, label))

                    if label in label_counts:
                        label_counts[label] += 1
                    else:
                        label_counts[label] = 1

    predicted_label = max(label_counts, key=label_counts.get)
    if label_counts[predicted_label] > num_exps / 2:
        return predicted_label

    return 'unknown'

# Run ccalg_predict.py for a single website and the given network conditions and
# classifies each of the resulting experiments. Returns (labeled, invalid) where
#   labeled: dictionary mapping (bw, rtt) to experiment name of all labeled experiments
#   invalid: dictionary mapping (bw, rtt) to experiment name of all invalid experiments
def run_ccalg_predict(website, url, exp_dir, network_conditions=[], skip_predict=False):
    exp_names = []
    if skip_predict:
        logging.info('Grabbing experiments from /tmp/data-raw')
        for exp in os.listdir(DATA_RAW):
            if exp.endswith('.tar.gz'):
                exp_names.append(exp[:exp.index('.tar')])
    else:
        logging.info('Running ccalg_predict.py for network conditions {}'.format(network_conditions))
        network_arg = ' '.join(['--network {} {}'.format(bw, rtt) for bw, rtt in network_conditions])
        cmd = 'python3.6 {} --website {} {} {} --f'.format(CCALG_PREDICT, website, url, network_arg)
        args = shlex.split(cmd)
        process = subprocess.run(args, stdout=subprocess.PIPE)

        if process.returncode != 0:
            raise Exception('Error running experiments for website {}, url {}, network {}'.format(
                website, url, network_conditions))
    
        # Turn stdout bytes into string
        output = process.stdout.decode('utf-8')
        regex_name=r"exp_name=(.+)\n"
        names = re.findall(regex_name, output)
        if len(names) == 0:
            raise Exception('Unable to get flows for website {}, url {}, network {}'.format(
                website, url, network_conditions))

        for exp in re.findall(regex_name, output):
            if os.path.exists('{}/{}.tar.gz'.format(DATA_RAW, exp)):
                exp_names.append(exp)

    logging.info('Ran experiments {}'.format(exp_names))

    return run_classify_snakefile(exp_names, exp_dir)


# Runs classify_websites.snakefile for the given experiment names and returns a list
# of the experiment names which were marked invalid. Returns (labeled, invalid) where
#   labeled: dictionary mapping (bw, rtt) to experiment name of all labeled experiments
#   invalid: dictionary mapping (bw, rtt) to experiment name of all invalid experiments
def run_classify_snakefile(exp_names, exp_dir):
    logging.info('Running classify snakefile for {}'.format(exp_names))
    cmd = 'snakemake --config exp_name="{}" results_dir="{}" -s {} --latency-wait 10'.format(
            ' '.join(exp_names), exp_dir, CLASSIFY_SNAKEFILE)
    args = shlex.split(cmd)
    process = subprocess.run(args, stdout=subprocess.PIPE)
    if process.returncode != 0:
        raise Exception('classify_websites.snakefile failed on {}'.format('\n'.join(exp_names)))

    invalid = {}
    labeled = {}

    for exp in exp_names:
        results_filename = RESULTS_FILENAME.format(exp_dir, exp)
        if os.path.isfile(results_filename):
            with open(results_filename) as f:
                results = json.load(f)
                if results['mark_invalid']:
                    invalid[(results['btlbw'], results['rtt'])] = exp
                else:
                    labeled[(results['btlbw'], results['rtt'])] = exp

    return (labeled, invalid)


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
    fileConfig(LOGGING_CONFIG)
    args = parse_args()
    classify_websites(args.websites)
