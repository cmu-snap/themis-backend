import json
import redis
import argparse

redis_host = 'localhost'
redis_port = 6379
redis_password = ''

def queue_experiment(conn, websites, ntwrk_conditions):
    inputs = {
        'website1': websites[0],
        'file1': websites[1],
        'website2': websites[2],
        'file2': websites[3],
        'btlbw': ntwrk_conditions[0],
        'rtt': ntwrk_conditions[1]
    }

    conn.rpush('queue:experiment', json.dumps(inputs))
    print('Pushed experiment={}'.format(inputs))

# Parse commandline arguments
def parse_args():
    parser = argparse.ArgumentParser(
        description='Queue cctestbed experiment on two websites to classify which CCA each website is using')
    parser.add_argument(
        '--website, -w',
        nargs=4,
        action='append',
        required='True',
        metavar=('WEBSITE1', 'FILE_URL1', 'WEBSITE2', 'FILE_URL2'),
        dest='websites',
        help='Urls of files to download from two websites.')
    parser.add_argument(
        '--network, -n',
        nargs=2,
        action='append',
        metavar=('BTLBW', 'RTT'),
        dest='ntwrk_conditions',
        type=int,
        help='Network conditions for downloads from websites.')

    args = parser.parse_args()
    args.websites = args.websites[0]
    if args.ntwrk_conditions is None:
        args.ntwrk_conditions = ['', '']
    else:
        args.ntwrk_conditions = args.ntwrk_conditions[0]
    return args

def main(websites, ntwrk_conditions):
    r = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password)
    queue_experiment(r, websites, ntwrk_conditions)

if __name__ == '__main__':
    args = parse_args()
    main(args.websites, args.ntwrk_conditions)
