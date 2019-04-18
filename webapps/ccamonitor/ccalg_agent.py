import shlex, subprocess
import re, os

# Call ccalg_fairness.py with the given arguments and return experiment name
def run_ccalg_fairness(inputs):
    cmd = 'python3.6 /opt/cctestbed/ccalg_fairness.py --website {} {} --network {} {} {} --test {} --competing_ccalg {} --num_competing 1 --duration 240'
    args = shlex.split(cmd.format(
        inputs['website'],
        inputs['file_url'],
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
    regex_name = r"exp_name=(.+)\n"
    exp_name = ''
    if re.search(regex_name, output):
        match = re.search(regex_name, output)
        exp_name = match.group(1)

    return exp_name

def run_fairness_snakefile(exp_name, exp_id):
    if not os.path.isdir('/tmp/data-websites/{}'.format(exp_id)):
        os.mkdir('/tmp/data-websites/{}'.format(exp_id))
    cmd = 'snakemake --config exp_name={} metric_dir="data-websites/{}" -s /opt/cctestbed/fairness_websites.snakefile'
    args = shlex.split(cmd.format(exp_name, exp_id))
    process = subprocess.run(args, stdout=subprocess.PIPE)
    return process.returncode
    
