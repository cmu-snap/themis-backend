import shlex, subprocess
import re
import json
import redis

redis_host = 'localhost'
redis_port = 6379
redis_password = ''


def dequeue_experiment(conn):
    packed = conn.blpop(['queue:experiment'], 0)
    if packed:
        print('Dequeued experiment')
        inputs = json.loads(packed[1])
        # TODO: Set experiment status
        (tar, name) = run_experiment(inputs)
        if tar != '' and name != '':
            # Store experiment with experiment name as key
            experiment = {
                'tar': tar,
                'website1': inputs['website1'],
                'file1': inputs['file1'],
                'website2': inputs['website2'],
                'file2': inputs['file2'],
                'btlbw': inputs['btlbw'],
                'rtt': inputs['rtt']
            }
            conn.hmset(name, experiment)
            print('Stored experiment name {}'.format(name))
            return 0

    print('Failed to get experiment name')
    return -1
    
# Call ccalg_predict.py with the given arguments and return the experiment
# tar filename and unique experiment name
def run_experiment(inputs):
    cmd = 'python3.6 ccalg_compare.py --website {} {} {} {} {}'
    network = ''
    # Add network option if network conditions in inputs
    if inputs['btlbw'] != '' and inputs['rtt'] != '':
        network = '--network {} {}'.format(inputs['btlbw'], inputs['rtt'])

    args = shlex.split(cmd.format(
        inputs['website1'],
        inputs['file1'],
        inputs['website2'],
        inputs['file2'],
        network))
    process = subprocess.run(args, stdout=subprocess.PIPE)
    # Turn stdout bytes into string
    output = process.stdout.decode('utf-8') 

    regex_tar = r"tar_filename=(.+) "
    regex_name = r"exp_name=(.+)\n"
    tar = ''
    name = ''
    if re.search(regex_tar, output):
        match = re.search(regex_tar, output)
        tar = match.group(1)

    if re.search(regex_name, output):
        match = re.search(regex_name, output)
        name = match.group(1)

    return (tar, name)

def main():
    r = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password)
    while(True):
        dequeue_experiment(r)

if __name__ == '__main__':
    main()
