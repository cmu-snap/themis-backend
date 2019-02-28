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
    # Turn stdout bytes into string
    output = process.stdout.decode('utf-8') 
    print('OUTPUT')
    print(output)
    return process.returncode
    """
    # TODO: Check output for error statement to see if failed
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
    """
#run_ccalg_fairness({
#    'website': 'ssa.gov',
#    'filename': 'https://www.ssa.gov/pubs/audio/EN-05-10035.mp3',
#    'btlbw': 10,
#    'rtt': 75,
#    'queue_size': 512,
#    'test': 'iperf-website',
#    'competing_ccalg': 'cubic'})

    
