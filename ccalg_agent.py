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
        inputs = json.loads(packed[1])
        # TODO: Set experiment status
        (tar, name) = run_experiment(inputs['website'], inputs['file'], inputs['btlbw'], inputs['rtt'])
        if tar != '' and name != '':
            # Store experiment with experiment name as key
            experiment = {
                'tar': tar,
                'website': inputs['website'],
                'file': inputs['file'],
                'btlbw': inputs['btlbw'],
                'rtt': inputs['rtt']
            }
            conn.hmset(name, experiment)
            return 0

    print('Failed to get experiment name')
    return -1
    
# Call ccalg_predict.py with the given arguments and return the experiment
# tar filename and unique experiment name
def run_experiment(website, filename, btlbw, rtt):
    cmd = 'python3.6 ccalg_predict.py --website {} {} --network {} {}'
    args = shlex.split(cmd.format(website, filename, btlbw, rtt))
    subprocess.run(args)
    #output = subprocess.run(args, stdout=subprocess.PIPE)
    
    #regex_tar = r"tar_filename=(.+\n)"
    #regex_name = r"exp_name=(.+\n)"
    #tar = ''
    #name = ''
    #if re.search(regex_tar, output):
    #    match = re.search(regex_tar, output)
    #    tar = match.group(1)

    #if re.search(regex_name, output):
    #    match = re.search(regex_name, output)
    #    name = match.group(1)

    #return (tar, name)

def main():
    r = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password)
    run_experiment('python.org', 'https://www.python.org/ftp/python/3.7.0/python-3.7.0-macosx10.6.pkg', 15, 355)
    #if dequeue_experiment(r) == 0:
    #    print('Successfully ran experiment')

    #while(True):
    #    dequeue_experiment(r)

if __name__ == '__main__':
    main()
