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

    conn.rpush('queue:experiment', json.dumps(inputs)

def dequeue_experiment(conn):
    packed = conn.blpop(['queue:experiment'], 0)
    if packed:
        inputs = json.loads(packed[1])
        # TODO: Set experiment status
        tar = run_experiment(inputs['website'], inputs['filename'], inputs['btlbw'], inputs['rtt'])
        # TODO: Store finished experiment in database
    
# Call ccalg_predict.py with the given arguments and return the experiment tar filename
def run_experiment(website, filename, btlbw, rtt):
    cmd = 'python3.6 ccalg_predict.py --website {} {} --network {} {}'
    args = shlex.split(cmd.format(website, filename, btlbw, rtt))
    output = subprocess.run(args, stdout=subprocess.PIPE)
    
    regex = r"tar_filename=(.+\n)"
    tar = ''
    if re.search(regex, output):
        match = re.search(regex, output)
        tar = match.group(1)

    return tar

def main():
    r = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password)
    # TODO: infinite loop dequeue_experiment

if __name__ == '__main__':
    main()
