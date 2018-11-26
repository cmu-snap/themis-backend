import shlex, subprocess
import re
import json
import redis

redis_host = 'localhost'
redis_port = 6379
redis_password = ''

def queue_experiment(conn, website, filename, btlbw, rtt):
    inputs = {
        'website': website,
        'file': filename,
        'btlbw': btlbw,
        'rtt': rtt
    }

    conn.rpush('queue:experiment', json.dumps(inputs))

def dequeue_experiment(conn):
    packed = conn.blpop(['queue:experiment'], 0)
    if packed:
        inputs = json.loads(packed[1])
        # TODO: Set experiment status
        (tar, name) = run_experiment(inputs['website'], inputs['filename'], inputs['btlbw'], inputs['rtt'])
        if tar == '' or name == '':
            print('Failed to get experiment name')
            return -1
        
        # Store experiment with experiment name as key
        experiment = {
            'tar': tar,
            'website': inputs['website'],
            'filename': inputs['filename'],
            'btlbw': inputs['btlbw'],
            'rtt': inputs['rtt']
        }
        conn.hmset(name, experiment)
        return 0
    
# Call ccalg_predict.py with the given arguments and return the experiment
# tar filename and unique experiment name
def run_experiment(website, filename, btlbw, rtt):
    cmd = 'python3.6 ccalg_predict.py --website {} {} --network {} {}'
    args = shlex.split(cmd.format(website, filename, btlbw, rtt))
    output = subprocess.run(args, stdout=subprocess.PIPE)
    
    regex_tar = r"tar_filename=(.+\n)"
    regex_name = r"exp_name=(.+\n)"
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
