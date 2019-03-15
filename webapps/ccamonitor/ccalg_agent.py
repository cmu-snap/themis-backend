import shlex, subprocess
import re
import json

# Call ccalg_fairness.py with the given arguments and return the experiment
# tar filename and unique experiment name
def run_ccalg_fairness(inputs):
    cmd = 'python3.6 /opt/cctestbed/ccalg_fairness.py --website {} {} --network {} {} {} --test {} --competing_ccalg {} --num_competing 1'
    args = shlex.split(cmd.format(
        inputs['website'],
        inputs['filename'],
        inputs['btlbw'],
        inputs['rtt'],
        inputs['queue_size'],
        inputs['test'],
        inputs['competing_ccalg']))
    process = subprocess.run(args, stdout=subprocess.PIPE)
    if process.returncode != 0:
        raise Exception('Experiment failed.')
    
    # Turn stdout bytes into string
    output = process.stdout.decode('utf-8') 
    regex_tar = r"tar_name=(.+) "
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

    
