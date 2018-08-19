import boto3
import botocore
import os
import stat
import yaml
import time
import logging
import paramiko
import command
import cctestbedv2 as cctestbed
import cctestbed_generate_experiments as generate_experiments
from contextlib import contextmanager
import getpass

from logging.config import fileConfig
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logging_config.ini')
fileConfig(log_file_path)    

def get_all_regions():
    """Get all EC2 regions"""
    ec2 = boto3.client('ec2')
    response = ec2.describe_regions()
    regions = [region['RegionName'] for region in response['Regions']]
    return regions

def get_ec2(region_name=None):
    """Get a boto3 client for EC2 with givien region"""
    return boto3.client('ec2', region_name=region_name)

def region_has_instance(ec2):
    """Return True if this EC2 region has atleast one
    instance.
    """
    response = ec2.describe_instances()
    if len(response['Reservations']) > 0:
        return True
    return False

def get_instance(region):
    """Return instance object from this region. Assumes there is only one"""
    running_filter = [{'Name': 'instance-state-name',
                                 'Values': ['running']}]
    # could have also done boto3.resource('ec2', region_name=region)
    instances = list(boto3
                     .resource('ec2',region_name=region)
                     .instances
                     .filter(Filters=running_filter).all())
    if len(instances) == 0:
        return None
    assert(len(instances) == 1)
    instance = instances[0]
    return instance
    

def get_key_pair_path(ec2):
    """Get key pairs for this EC2 region"""
    # assume only one key pair per region and
    # keys are always stored in ~/.ssh/<KeyName>.pem
    key_pair_name = get_key_name(ec2)
    if key_pair_name is None:
        return None
    else:
        key_pair_path = '/home/ranysha/.ssh/{}.pem'.format(key_pair_name)
        assert(os.path.isfile(key_pair_path))
        return key_pair_path

def get_key_name(ec2):
    response = ec2.describe_key_pairs()
    key_pairs = response['KeyPairs']
    if len(key_pairs) == 0:
        return None
    else:
        # key name must start with rware
        for key_pair in key_pairs:
            if key_pair['KeyName'].startswith('rware'):
                return key_pair['KeyName']
        return None
    
def create_key_pair(ec2, region_name):
    response = ec2.create_key_pair(KeyName='rware-{}'.format(region_name))
    key_pair_name = response['KeyName']
    key_pair_path = '/home/ranysha/.ssh/{}.pem'.format(key_pair_name)
    with open(key_pair_path, 'w') as f:
        f.write(response['KeyMaterial'])
    os.chmod(key_pair_path, stat.S_IRUSR | stat.S_IWUSR)
    return key_pair_path

@contextmanager
def region_start_instance(ec2):
    instance =  _region_start_instance(ec2)
    try:
        yield instance
    finally:
        instance.terminate()
        
def _region_start_instance(ec2, image_id=None):
    """Start an EC2 instance in this region"""
    # find an availabilty zone
    all_zones = ec2.describe_availability_zones()
    available_zone = None
    region_name = None
    for zone in all_zones['AvailabilityZones']:
        if zone['State'] == 'available':
            available_zone = zone['ZoneName']
            region_name = zone['RegionName']
            break
    # force specifici availability zone us-west-1c
    # TODO: remove this hard coding and keep retrying zones
    # until succesful if there is an error
    if region_name == 'us-west-1':
        available_zone = 'us-west-1c'
    if region_name == 'ap-northeast-1':
        available_zone = 'ap-northeast-1c'
    if available_zone is None:
        raise RuntimeError('Could not find any available zones')
    # get key name
    key_name = get_key_name(ec2)
    if image_id is None:
        image_id = list(boto3
                        .resource('ec2', region_name=region_name)
                        .images
                        .filter(Filters=[{'Name':'name',
                                          'Values': ['ubuntu/images/hvm-ssd/ubuntu-xenial-16.04-amd64-server-201806*']}])
                        .all())[0].id
    assert(key_name is not None)
    # create 1 ubuntu t2.micro instance
    instance = boto3.resource('ec2', region_name=region_name).create_instances(
        ImageId=image_id,
        InstanceType='t2.micro',
        Placement={
            'AvailabilityZone':available_zone},
        KeyName=key_name,
        NetworkInterfaces=[
            {'AssociatePublicIpAddress':True,
             'DeviceIndex':0}],
        MaxCount=1,
        MinCount=1)

    ssh_allow_rule = {'FromPort': 22,
                      'IpProtocol': 'tcp',
                      'IpRanges': [{'CidrIp':'0.0.0.0/0'}],
                      'Ipv6Ranges':[],
                      'PrefixListIds':[],
                      'ToPort': 22,
                      'UserIdGroupPairs': []}
    try:
        response = ec2.authorize_security_group_ingress(GroupName='default',
                                                        IpPermissions=[ssh_allow_rule])
    except botocore.exceptions.ClientError as e:
        if not (e.response['Error']['Code'] == 'InvalidPermission.Duplicate'):
            raise e
        
    return instance[0]

def clone_cctestbed(ec2, instance, git_secret, ec2_username='ubuntu'):
    key_pair_path = get_key_pair_path(ec2)
    cmd = ('cd /opt '
           '&& sudo chown -R ubuntu /opt '
           '&& git clone git@github.com:rware/cctestbed.git ')
    cmd = ('cd /opt'
           '&& sudo chown -R ubuntu /opt '
           '&& git clone https://rware:{}@github.com/rware/cctestbed.git').format(git_secret)
    with command.get_ssh_client(ip_addr=instance.public_ip_address,
                                username=ec2_username,
                                key_filename=key_pair_path) as ssh_client:
        session = ssh_client.get_transport().open_session()
        #paramiko.agent.AgentRequestHandler(session)
        session.set_combine_stderr(True)
        stdout = session.makefile()
        try:
            logging.info('Running cmd ({}): {}'.format(
                instance.public_ip_address, cmd.replace(git_secret, '****')))
            session.exec_command(cmd)
            exit_status =  session.recv_exit_status()
            return exit_status, stdout.read()
        except:
            stdout.close()

def run_ec2_command(ec2, instance, cmd, ec2_username='ubuntu'):
    key_pair_path = get_key_pair_path(ec2)
    with command.get_ssh_client(ip_addr=instance.public_ip_address,
                                username=ec2_username,
                                key_filename=key_pair_path) as ssh_client:
        _, stdout, stderr = command.exec_command(ssh_client,
                                                 instance.public_ip_address,
                                                 cmd)
        # actually should return a bad exit status
        exit_status =  stdout.channel.recv_exit_status()
        return exit_status, stdout.read()


def update_kernel(ec2, instance, ec2_username='ubuntu'):
    cmd = ('cd /opt/cctestbed '
           '&& ./setup-kernel.sh upgrade_kernel ')
    return run_ec2_command(ec2, instance, cmd, ec2_username)    
    
def install_iperf3(ec2, instance, ec2_username='ubuntu'):
    cmd = ('cd /opt/cctestbed '
           '&& ./setup-kernel.sh install_iperf3 ')
    return run_ec2_command(ec2, instance, cmd, ec2_username)

def wait_for_ssh(ec2, instance, ec2_username='ubuntu'):
    while True:
        try:
            with command.get_ssh_client(ip_addr=instance.public_ip_address,
                                        username=ec2_username,
                                        key_filename=get_key_pair_path(ec2)) as ssh_client:
                _, stdout, stderr = command.exec_command(ssh_client,
                                                         instance.public_ip_address,
                                                         'echo "TESTING SSH CONNECTION"')
                break
        except:
            logging.info('Waiting 60s for machine to boot')
            time.sleep(60)


def setup_ec2(ec2, instance, git_secret, ec2_username='ubuntu'):
    wait_for_ssh(ec2, instance)
    logging.info('Cloning cctestbed')
    exit_status, stdout = clone_cctestbed(ec2, instance, git_secret, ec2_username)
    logging.info(stdout)
    logging.info('Updating kernel')
    exit_status, stdout = update_kernel(ec2, instance, ec2_username)
    logging.info(stdout)
    # make sure machine has time to reboot
    logging.info('Waiting 60s for machine to reboot')    
    time.sleep(60)
    wait_for_ssh(ec2, instance)
    exit_status, stdout = install_iperf3(ec2, instance, ec2_username)
    logging.info(stdout)
    cmds = [
    'cd /opt/cctestbed/tcp_bbr_measure && make',
    'echo net.core.wmem_max = 16777216 | sudo tee -a /etc/sysctl.conf',
    'echo net.core.rmem_max = 16777216 | sudo tee -a /etc/sysctl.conf',
    'echo net.core.wmem_default = 16777216 | sudo tee -a /etc/sysctl.conf', 
    'echo net.core.rmem_default = 16777216 | sudo tee -a /etc/sysctl.conf',
    'echo net.ipv4.tcp_wmem = 10240 16777216 16777216 | sudo tee -a /etc/sysctl.conf',
    'net.ipv4.tcp_rmem = 10240 16777216 16777216 | sudo tee -a /etc/sysctl.conf',
    'sudo sysctl -p'
    ]
    for cmd in cmds:
        exit_status, stdout = run_ec2_command(ec2, instance, cmd)
        logging.info(stdout)    

def install_kernel_modules(ec2, instance, ec2_username='ubuntu'):
    cmds = [
        'cd /opt/cctestbed/tcp_bbr_measure && sudo insmod tcp_probe_ray.ko',
        'sudo modprobe tcp_bbr',
        'sudo ethtool -K eth0 tx off sg off tso off'
    ]
    for cmd in cmds:
        exit_status, stdout = run_ec2_command(ec2, instance, cmd, ec2_username)
        logging.info(stdout)    

        
@contextmanager
def add_nat_rule(instance, nat_ip='128.2.208.128', nat_username='ranysha',
                 nat_key_filename='/home/ranysha/.ssh/id_rsa'):
    """Will delete NAT rule when you exit context"""
    try:
        yield _add_nat_rule(instance, nat_ip, nat_username, nat_key_filename)
    finally:
        with command.get_ssh_client(ip_addr=nat_ip, username=nat_username,
                                    key_filename=nat_key_filename) as ssh_client:
            cmd = 'sudo iptables -t nat --delete PREROUTING 4'
            _, stdout, stderr = command.exec_command(ssh_client, nat_ip, cmd)

def _add_nat_rule(instance, nat_ip='128.2.208.128', nat_username='ranysha',
                 nat_key_filename='/home/ranysha/.ssh/id_rsa'):
    with command.get_ssh_client(ip_addr=nat_ip, username=nat_username,
                                key_filename=nat_key_filename) as ssh_client:
        cmd = ('sudo iptables -t nat -A PREROUTING -i enp11s0f0 '
               '--source {} -j DNAT --to-destination 192.0.0.4').format(
                   instance.public_ip_address)
        _, stdout, stderr = command.exec_command(ssh_client, nat_ip, cmd)
        exit_status =  stdout.channel.recv_exit_status()
        return exit_status, stdout.read()

def get_ec2_experiments(instance, ec2, region):
    server = generate_experiments.HOST_POTATO
    client = generate_experiments.HOST_AWS_TEMPLATE
    client['ip_wan'] = instance.public_ip_address
    client['ip_lan'] = instance.private_ip_address
    client['key_filename'] = get_key_pair_path(ec2)
    # create config and output
    config = generate_experiments.all_ccalgs_config(
        server, client,
        btlbw=10,
        rtt=1,
        end_time=60,
        exp_name_suffix=region.replace('-',''),
        queue_sizes=[32, 64, 128, 256, 512, 1024, 2048])
        #queue_sizes=[32, 64, 128, 256, 512])
    config_filename = 'experiments-all-ccalgs-aws-{}.yaml'.format(
        region.replace('-',''))
    logging.info('Writing config file {}'.format(config_filename))
    with open(config_filename, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    experiments = cctestbed.load_experiments(config,
                                             config_filename, force=True)
    return experiments

def run_ec2_experiments(experiments, instance):
    completed_experiment_procs = []
    logging.info('Going to run {} experiments.'.format(len(experiments)))
    with add_nat_rule(instance):
        for experiment in experiments.values():
            while True:
                try:
                    proc = experiment.run()
                    break
                except paramiko.ssh_exception.NoValidConnectionsError as e:
                    logging.warning('Could not connect to instance. Waiting 30s and retrying.')
                    time.sleep(30)
            completed_experiment_procs.append(proc)

    for proc in completed_experiment_procs:
        logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
        proc.wait()
        if proc.returncode != 0:
            logging.warning('Error running cmd PID={}'.format(proc.pid))

def get_region_image(region):
    aws_images = list(boto3
                      .resource('ec2', region_name=region)
                      .images
                      .filter(Filters=[{'Name':'name', 'Values':[region]}],
                              Owners=['self'])
                      .all())
    if len(aws_images) == 0:
        return None
    assert(len(aws_images) == 1)
    return aws_images[0]


def get_taro_experiments():
    regions = get_all_regions()
    for region in regions:
        exp_tarfiles = glob.glob(
            '/tmp/*{}-20180818*.tar.gz'.format(region.replace('-','')))
        for tarfile_localpath in exp_tarfiles:
            experiment_name = tarfile_remotepath[:-len('.tar.gz')]
            experiment_description_filename = '{}.json'.format(experiment_name)
            with untarfile(tarfile_localpath, experiment_description_filename) as f:
                experiment_description = json.load(f)
            with open(experiment_description_localpath, 'w') as f:
                json.dump(experiment_description, f)
                experiment = Experiment(tarfile_localpath=tarfile_localpath,
                                        **experiment_description)
            break
        break
    return experiment


        

def main(git_secret, force_create_instance=False):
    #regions = ['ap-south-1', 'eu-west-1']
    skip_regions = []
    #get_all_regions()
    
    regions = ['ap-northeast-1', 'ap-northeast-2', 'sa-east-1','ap-southeast-1','ap-southeast-2', 'eu-central-1', 'us-east-1','us-east-2','us-west-1', 'ca-central-1', 'eu-west-3', 'eu-west-2', 'us-west-2'] 

    logging.info('Found {} regions: {}'.format(len(regions), regions))
    # TODO: wait for all created images to be created
    created_images = []
    for region in regions:
        if region in skip_regions:
            logging.warning('Skipping region {}'.format(region))
            continue
        instance = get_instance(region)
        if (instance is None) or (force_create_instance):
            ec2_region = get_ec2(region)
            if get_key_name(ec2_region) is None:
                logging.warning('Creating key pair for region {}'.format(region))
                create_key_pair(ec2_region, region)        
            image = get_region_image(region)
            if image is None:
                image_id = None
            else:
                image_id = image.id
            logging.info('Creating instance for region {}'.format(region))
            instance = _region_start_instance(ec2_region, image_id)
            try:
                instance.wait_until_running()
                instance.load()
                if image is None:
                    logging.info('Setting up cctestbed on instance')
                    setup_ec2(ec2_region, instance, git_secret, ec2_username='ubuntu')
            except Exception as e:
                instance.stop()
                raise e
        wait_for_ssh(ec2_region, instance, ec2_username='ubuntu')
        # need to install kernel modules every time
        install_kernel_modules(ec2_region, instance, ec2_username='ubuntu')
        try:
            experiments = get_ec2_experiments(instance, ec2_region, region)
            run_ec2_experiments(experiments, instance)
        finally:
            logging.info('Stopping instance')
            instance.stop()
            wait_time = 0
            while (instance.state['Name'] != 'stopped' and wait_time < 300):
                time.sleep(5)
                wait_time += 5
                instance.load()
            if get_region_image(region) is None:
                # create ec2 image before terminating
                logging.info('Creating image for region {}'.format(region))
                try:
                    instance.create_image(Name=region)
                except Exception as e:
                    logging.error('Error while trying to create image: {}', e)

"""
def _main():
    # for each ec2 region, if there isn't already a running instance
    # 1- create key pair if there isn't one already; get_key_pair_path
    # 2- create ec2 instance
    # 3- wait until ec2 instance is running
    # 4- wait until ssh connectivity
    # 5- run ec2 instance setup
    #  - generate experiment config
    # 6- run cctestbed experiment
    # 7- delete ec2 machine
    # 8- delete nat rule
    regions = get_all_regions()
    logging.info('Found {} regions: {}'.format(len(regions), regions))
    for region in regions:
        logging.info('**REGION**: {}'.format(region))
        ec2 = get_ec2(region, ec2)
        if region_has_instance(ec2):
            logging.warning('Region already has a running instance so skipping')
            continue
        if get_key_name(ec2, region) is None:
            logging.warning('Creating key pair for region {}'.format(region))
            create_key_pair(ec2, region)
        logging.info('Creating instance for region {}'.format(region))
        with region_start_instance(ec2) as instance:
            logging.info('Waiting for instance to start running')
            instance.wait_until_running()
            instance.load()
            logging.info('Seting up instance for cctestbed experiments')
            setup_ec2(instance)
            server = generate_experiments.HOST_POTATO
            client = generate_experiments.HOST_AWS_TEMPLATE
            client['ip_wan'] = instance.public_ip_address
            client['ip_lan'] = instance.private_ip_address
            client['key_filename'] = get_key_pair_path(ec2)
            # create config and output
            config = generate_experiments.all_ccalgs_config(
                server, client,
                btlbw=10,
                rtt=1,
                end_time=60,
                exp_name_suffix=region.replace('-',''))
            config_filename = 'experiments-all-ccalgs-aws-{}.yaml'.format(
                region.replace('-',''))
            logging.info('Writing config file {}'.format(config_filename))
            with open(config_filename, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            # run cctestbed experiment
            experiments = cctestbed.load_experiments(config,
                                                     config_filename)
            completed_experiment_procs = []
            logging.info('Going to run {} experiments.'.format(len(experiments)))
            for experiment in experiments.values():
                proc = experiment.run()
                completed_experiment_procs.append(proc)
                break

            for proc in completed_experiment_procs:
                logging.info('Waiting for subprocess to finish PID={}'.format(proc.pid))
                proc.wait()
                if proc.returncode != 0:
                    logging.warning('Error running cmd PID={}'.format(proc.pid))
        break
"""

if __name__ == '__main__':
    #git_secret = getpass.getpass('Github secret: ')
    #main(git_secret, True)
    pass
