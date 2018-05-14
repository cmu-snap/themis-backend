CODEPATH = '/Users/rware/Documents/research/code/cctestbed'
DATAPATH = '/Users/rware/Documents/research/data/cctestbed'

import sys
sys.path.insert(0, CODEPATH)
import cctestbedv2 as cctestbed
import paramiko
import os
import tarfile
import json
import yaml

REMOTE_IP_ADDR = '128.2.208.131'
REMOTE_USERNAME = 'ranysha'

def load_experiments(experiment_names):
    ssh_client = cctestbed.get_ssh_client(REMOTE_IP_ADDR,
                                           username=REMOTE_USERNAME)
    for experiment_name in experiment_names:
        # copy tarfile from remote machine to local machine (data directory)
        remotepath = '/tmp/{}.tar.gz'.format(experiment_name)
        localpath = os.path.join(DATAPATH, '{}.tar.gz').format(
            experiment_name)
        sftp_client = ssh_client.open_sftp()
        sftp_client.get(remotepath,
                        localpath)
        with tarfile.open() as tar:
            # get experiment description file
            with tar.extractfile('{}.json'.format(experiment_name)) as f:
                experiment_description = json.load(f)
            experiment_config_filename = experiment_description['config_filename']
            # get config file
            with tar.extractfile(os.path.basename(experiment_config_filename)) as f:
                config = yaml.safe_load(f)

        sftp_client.close()
    ssh_client.close()
