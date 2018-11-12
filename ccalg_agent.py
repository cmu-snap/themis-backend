import shlex, subprocess
import re

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


