import json
import argparse
import redis
from rq import Queue

# For each network condition, compete against bbr and cubic iperf-website
def queue_experiment(queue, websites, ntwrk_conditions):
    if ntwrk_conditions is None:
        ntwrk_conditions = [[10, 75, 32], [10, 75, 64], [10, 75, 512]]
    tests = ['iperf-website']
    competing_ccalgs = ['cubic', 'bbr']

    for conditions in ntwrk_conditions:
        for test in tests:
            for competing_ccalg in competing_ccalgs:
                inputs = {
                    'website': websites[0],
                    'file': websites[1],
                    'btlbw': conditions[0],
                    'rtt': conditions[1],
                    'queue_size': conditions[2],
                    'test': test,
                    'competing_ccalg': competing_ccalg
                }
                print('Pushed experiment={}'.format(inputs))

# Parse commandline arguments
def parse_args():
    parser = argparse.ArgumentParser(
        description='Queue website to compete against generated traffic using ccalg_fairness.py')
    parser.add_argument(
        '--website, -w',
        nargs=2,
        action='append',
        required='True',
        metavar=('WEBSITE', 'FILE_URL'),
        dest='websites',
        help='Url of file to download from one website.')
    parser.add_argument(
        '--network, -n',
        nargs=3,
        action='append',
        metavar=('BTLBW', 'RTT', 'QUEUE_SIZE'),
        dest='ntwrk_conditions',
        type=int,
        help='Network conditions for download.')

    args = parser.parse_args()
    args.websites = args.websites[0]
    return args

"""def main(websites, ntwrk_conditions):
    queue = Queue(connection=Redis())
    queue_experiment(queue, websites, ntwrk_conditions)

if __name__ == '__main__':
    args = parse_args()
    main(args.websites, args.ntwrk_conditions)"""
