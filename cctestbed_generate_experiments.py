import argparse
import yaml
import sys
from itertools import product
from config import HOST_SERVER, HOST_CLIENT, HOST_AWS_TEMPLATE

HOST_TARO = {'ifname_remote': 'ens13',
             'ifname_local': 'ens3f0',
             'ip_lan': '192.0.0.1',
             'ip_wan': '128.2.208.128',
             'pci': '05:00.0',
             'key_filename': '/home/ranysha/.ssh/id_rsa',
             'username': 'ranysha'}

HOST_POTATO = {'ifname_remote': 'ens13',
               'ifname_local': 'ens13',
               'ip_lan': '192.0.0.4',
               'ip_wan': '128.2.208.104',
               'pci': '8b:00.0',
               'key_filename': '/home/ranysha/.ssh/id_rsa',
               'username': 'ranysha'}

HOST_AWS = {'ifname_remote': 'eth0',
            'ifname_local': 'ens3f0',
            'ip_lan': '172.31.21.221',
            'ip_wan': '35.160.118.3',
            'pci': '05:00.0',
            'key_filename': '/home/ranysha/.ssh/rware.pem',
            'username': 'ubuntu'}

HOST_AWS_LONDON = {'ifname_remote': 'eth0',
                   'ifname_local': 'ens3f0',
                   'ip_lan': '172.31.28.46',
                   'ip_wan': '18.130.112.215',
                   'pci': '05:00.0',
                   'key_filename': '/home/ranysha/.ssh/rware-london.pem',
                   'username':'ubuntu'}

HOST_AWS_TOKYO = {'ifname_remote': 'eth0',
                  'ifname_local': 'ens3f0',
                  'ip_lan': '172.31.47.182',
                  'ip_wan': '18.179.13.219',
                  'pci': '05:00.0',
                  'key_filename': '/home/ranysha/.ssh/rware-tokyo.pem',
                  'username': 'ubuntu'}

HOST_AWS_PAULO = {'ifname_remote': 'eth0',
                  'ifname_local': 'ens3f0',
                  'ip_lan': '172.31.9.149',
                  'ip_wan': '18.231.117.80',
                  'pci': '05:00.0',
                  'key_filename': '/home/ranysha/.ssh/rware-paulo.pem',
                  'username':'ubuntu'}

hosts = {'potato': HOST_POTATO,
         'taro': HOST_TARO,
         'aws': HOST_AWS,
         'aws_london': HOST_AWS_LONDON,
         'aws_tokyo': HOST_AWS_TOKYO,
         'client': HOST_CLIENT,
         'server': HOST_SERVER,
         'aws_paulo': HOST_AWS_PAULO}

def all_ccalgs_config(server, client, btlbw, rtt, end_time, exp_name_suffix=None,
                      queue_sizes = [64, 128, 256, 512, 1024, 2048, 4096]):
    config = {}
    if not client['ip_lan'].startswith('192.0.0'):
        config['server_nat_ip'] = '128.2.208.128'
    config['server'] = server
    config['client'] = client
    config['experiments'] = {}

    ccalgs = ['bbr', 'cubic', 'reno']
    for ccalg in ccalgs:
        for size in queue_sizes:
            if exp_name_suffix is None:
                experiment_name = '{}-{}bw-{}rtt-{}q'.format(
                    ccalg,btlbw, rtt, int(size))
            else:
                experiment_name = '{}-{}bw-{}rtt-{}q-{}'.format(
                    ccalg,btlbw, rtt, int(size), exp_name_suffix)
            experiment = {'btlbw': btlbw,
                          'queue_size': int(size)}
            flows = [{'ccalg': ccalg,
                      'start_time': 0,
                      'end_time': end_time,
                      'rtt': rtt}]
            experiment['flows'] = flows
            config['experiments'][experiment_name] = experiment
    return config

def ccalg_predict_config_websites(btlbw, rtt, end_time, queue_size, exp_name_suffix=None):
    config = {}
    config['server'] = HOST_SERVER
    config['client'] = HOST_CLIENT
    config['experiments'] = {}

    #ccalgs = ['bbr', 'cubic', 'reno']
    ccalgs = [ 'bic', 'cdg', 'dctcp', 'highspeed', 'htcp', 'hybla', 'illinois', 'lp', 'nv', 'scalable', 'vegas', 'veno', 'westwood', 'yeah']
    for ccalg in ccalgs:
        if exp_name_suffix is None:
            experiment_name = '{}-{}bw-{}rtt-{}q'.format(
                ccalg,btlbw, rtt, int(queue_size))
        else:
            experiment_name = '{}-{}bw-{}rtt-{}q-{}'.format(
                ccalg,btlbw, rtt, int(queue_size), exp_name_suffix)
            experiment = {'btlbw': btlbw,
                          'queue_size': int(queue_size)}
            flows = [{'ccalg': ccalg,
                      'start_time': 0,
                      'end_time': end_time,
                      'rtt': rtt}]
            experiment['flows'] = flows
            config['experiments'][experiment_name] = experiment
    return config


def ccalg_predict_config(btlbw, rtts, end_time, queue_sizes,
                         exp_name_suffix=None, ccalgs=None, loss=None):
    config = {}
    config['server'] = HOST_SERVER._asdict()
    config['client'] = HOST_CLIENT._asdict()
    config['experiments'] = {}

    if ccalgs is None:
        ccalgs = ['bbr', 'cubic', 'reno']
    if loss is None:
        loss = [None]
    for rtt in rtts:
        for queue_size in queue_sizes:
            for ccalg in ccalgs:
                for loss_rate in loss:
                    if exp_name_suffix is None:
                        experiment_name = '{}-{}bw-{}rtt-{}q'.format(
                            ccalg,btlbw, rtt, int(queue_size))
                    else:
                        experiment_name = '{}-{}bw-{}rtt-{}q-{}'.format(
                            ccalg,btlbw, rtt, int(queue_size), exp_name_suffix)

                    if loss_rate is not None:
                        experiment_name = '{}-{}bw-{}rtt-{}q-{}loss-{}'.format(
                            ccalg, btlbw, rtt, int(queue_size), float(loss_rate), exp_name_suffix)
                        experiment = {'btlbw': btlbw,
                                      'queue_size': int(queue_size),
                                      'loss_rate': float(loss_rate)}
                    else:
                        experiment = {'btlbw': btlbw,
                                      'queue_size': int(queue_size)}
                    flows = [{'ccalg': ccalg,
                              'start_time': 0,
                              'end_time': end_time,
                              'rtt': int(rtt)}]
                    experiment['flows'] = flows
                    config['experiments'][experiment_name] = experiment
    return config


def cubic_bbr_config(server, client, btlbw, rtt, queue_size, end_time):
    config = {}
    config['server'] = server
    config['client'] = client
    config['experiments'] = {}
    #num_flows = [1,2,4,8,16,32]
    num_flows = [1,4,16]
    """"
    # bbr alone experiments
    for num_bbr_flows in num_flows:
        experiment_name = 'bbr{}'.format(num_bbr_flows)
        experiment = {'btlbw': btlbw,
                      'queue_size': queue_size}
        experiment['flows'] = [{'ccalg': 'bbr',
                                'start_time': 0,
                                'end_time': end_time,
                                'rtt': rtt} for _ in range(num_bbr_flows)]
        config['experiments'][experiment_name] = experiment
    """
    # cubic vs. bbr experiments
    for num_cubic_flows, num_bbr_flows in product(num_flows, repeat=2):
        experiment_name = 'cubic{}-bbr{}'.format(num_cubic_flows, num_bbr_flows)
        experiment = {'btlbw': btlbw,
                      'queue_size': queue_size}
        cubic_flows = [{'ccalg': 'cubic',
                        'start_time': 0,
                        'end_time': end_time,
                        'rtt': rtt} for _ in range(num_cubic_flows)]
        bbr_flows = [{'ccalg': 'bbr',
                      'start_time': 0,
                      'end_time': end_time,
                      'rtt': rtt} for _ in range(num_bbr_flows)]
        experiment['flows'] = cubic_flows + bbr_flows
        config['experiments'][experiment_name] = experiment
    return config

def cubic_bbr_bdp_config(server, client, end_time):
    config = {}
    config['server'] = HOST_SERVER._as_dict()
    config['client'] = client
    config['experiments'] = {}

                
    #experiment_params = [{'btlbw':400, 'rtt':30, 'bdp':1024},
    #                     {'btlbw':10, 'rtt':3, 'bdp':4}]

    experiment_params = [{'btlbw':100, 'rtt':1, 'bdp':8},
                         {'btlbw':15, 'rtt':100, 'bdp':128},
                         {'btlbw':120, 'rtt':100, 'bdp':1024}]
                         #{'btlbw':400, 'rtt':30, 'bdp':1024},
                         #{'btlbw':10, 'rtt':3, 'bdp':4}]

    for params in experiment_params:
        btlbw  = params['btlbw']
        rtt = params['rtt']
        bdp = params['bdp']
        queue_sizes_as_bdp = [0.25, 0.5, 1.0, 4.0, 16.0]
        queue_sizes = list(map(lambda x: x*bdp, queue_sizes_as_bdp))
                         
        for size in queue_sizes:
            if size >=4:
                experiment_name = 'cubic-bbr-{}bw-{}rtt-{}q'.format(btlbw, rtt, int(size))
                experiment = {'btlbw': btlbw,
                              'queue_size': int(size)}
                cubic_flows = [{'ccalg': 'cubic',
                                'start_time': 0,
                                'end_time': end_time,
                                'rtt': rtt}]
                bbr_flows = [{'ccalg': 'bbr',
                              'start_time': 0,
                              'end_time': end_time,
                              'rtt': rtt}] 
                experiment['flows'] = cubic_flows + bbr_flows
                config['experiments'][experiment_name] = experiment
    return config

def bbr_config(server, client, end_time, bdp=32):
    config = {}
    config['server'] = server
    config['client'] = client
    config['experiments'] = {}
    if bdp == 32:
        #queue_sizes = [8, 16, 32, 64, 128, 256, 512, 1024]
        queue_size = 1024
        btlbw = 10
        rtt = 40
    elif bdp == 512:
        #queue_sizes = [128, 256, 512, 1024, 2048, 4096, 8192, 16384]
        queue_size = 16384
        btlbw = 100
        rtt = 60
    elif bdp == 256:
        #queue_sizes = [64, 128, 256, 512, 1024, 2048, 4096, 8192]
        queue_size = 8192
        btlbw = 1000
        rtt = 3
    else:
        raise ValueError("BDP must be one of {32, 256, 512}")

    num_flows = [1,2,4,8,16,32]
    # bbr alone experiments
    for num_bbr_flows in num_flows:
        experiment_name = 'bbr{}-{}bdp'.format(num_bbr_flows, bdp)
        experiment = {'btlbw': btlbw,
                      'queue_size': queue_size}
        experiment['flows'] = [{'ccalg': 'bbr',
                                'start_time': 0,
                                'end_time': end_time,
                                'rtt': rtt} for _ in range(num_bbr_flows)]
        config['experiments'][experiment_name] = experiment        
    return config


# note the queue size must be a power of 2
def cloudlab_config(cca, end_time, queue_size=1024, btlbw=10, rtt=40, kind='iperf'):
    config = {}
    config['server'] = dict(HOST_SERVER._asdict())
    config['client'] = dict(HOST_CLIENT._asdict())
    config['experiments'] = {}
    
    num_flows = [1]
    # cca alone experiments
    for num_cca_flows in num_flows:
        experiment_name = '{}{}-{}bw-{}rtt-{}q'.format(cca, num_cca_flows, btlbw, rtt, queue_size)
        experiment = {'btlbw': btlbw,
                      'queue_size': queue_size}
        experiment['flows'] = [{'ccalg': cca,
                                'start_time': 0,
                                'end_time': end_time,
                                'rtt': rtt,
                                'kind' : kind} for _ in range(num_cca_flows)]
        config['experiments'][experiment_name] = experiment        
    return config


def main(argv):
    args = parse_args(argv)
    print(args)
    server = hosts[args.server]
    client = hosts[args.client]
    if args.experiment_type == 'cloudlab':
        config = cloudlab_config(cca=args.cca, end_time=args.end_time, queue_size=args.queue_size, btlbw=args.btlbw, rtt=args.rtt, 
                                 kind=args.kind)
    if args.experiment_type == 'cubic-bbr':
        config = cubic_bbr_config(server, client, btlbw=args.btlbw,
                                  rtt=args.rtt, queue_size=args.queue_size,
                                  end_time=args.end_time)
    if args.experiment_type == 'cubic-bbr-bdp':
        config = cubic_bbr_bdp_config(server, client,
                                      end_time=args.end_time)
    if args.experiment_type == 'bbr':
        config = bbr_config(server, client, end_time=args.end_time, bdp=args.bdp)
    if args.experiment_type == 'all-ccalgs':
        config = all_ccalgs_config(server, client, end_time=args.end_time,
                            btlbw=args.btlbw, rtt=args.rtt)
    if args.experiment_type == 'ccalg-predict':
        config = ccalg_predict_config(server, client, end_time=args.end_time, queue_size=args.queue_size,
                                   btlbw=args.btlbw, rtt=args.rtt, exp_name_suffix=args.exp_name_suffix)        
    with open(args.filename, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    print('EXPERIMENTS:\n')
    print('\n'.join(config['experiments'].keys()))
        
def parse_args(argv):
    parser = argparse.ArgumentParser(
        description='Config file generator for cctestbed experiments')
    parser.add_argument('experiment_type', choices=['cubic-bbr',
                                                    'cubic-bbr-bdp',
                                                    'bbr',
                                                    'all-ccalgs',
                                                    'ccalg-predict',
                                                    'cloudlab'],
                        help='kind of experiment')
    parser.add_argument('filename',
                        help='filename for the generated config file')
    parser.add_argument('client', choices=['taro','client','aws',
                                           'aws_london', 'aws_tokyo', 'aws_paulo'],
                        help='client host')
    parser.add_argument('server', choices=['potato','server'],
                        help='server host')
    parser.add_argument('--cca', required=False,
                        help='congestion control algorithm')
    parser.add_argument('--bdp', type = int, required=False,
                        help='bandwidth delay product')
    parser.add_argument('--btlbw', type=int, required=False, help='bottleneck bandwidth in mbps', default=10)
    parser.add_argument('--rtt', default=40, type=int, required=False, help='round trip time for all flows in ms')
    parser.add_argument('--queue_size', default=1024, required=False, type=int,
                        help='size of bottleneck queue in packets')
    parser.add_argument('--exp_name_suffix', required=False, help='experiment name suffix')
    parser.add_argument('--kind', default='iperf', required=False,
                        help='Type of traffic; This can be either video or iperf')
    parser.add_argument('end_time', type=int, help='length of experiment in seconds')
    args = parser.parse_args(argv)
    return args
    
if __name__ == '__main__':
    argv = sys.argv[1:]
    main(argv)
    #pass
