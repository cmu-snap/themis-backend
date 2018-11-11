from cctestbedv2 import Host
import os
import paramiko

def get_ssh_config():
    ssh_config_filepath = '/users/{}/.ssh/config'.format(os.environ.get('USER'))
    ssh_config = paramiko.config.SSHConfig()
    with open(ssh_config_filepath) as f:
        ssh_config.parse(f)
    return ssh_config

def get_host_ip_wan(host):
    host_config = get_ssh_config().lookup(host)
    return host_config['hostname']

def get_host_key_filename(host):
    host_config = get_ssh_config().lookup(host)
    return host_config['identityfile'][0]

def get_host_username(host):
    host_config = get_ssh_config().lookup(host)
    return host_config['user']



HOST_CLIENT_TEMPLATE = {'ifname_remote': 'enp6s0f1',
                      'ifname_local': 'enp6s0f0',
                      'ip_lan':'192.0.0.4',
                      'ip_wan':None,
                      'pci':'06:00.0',
                      'key_filename':get_host_key_filename('cctestbed-client'),
                      'username':get_host_username('cctestbed-client')}

HOST_SERVER, HOST_CLIENT = get_host_info()
HOST_CLIENT_TEMPLATE = HOST_SERVER._as_dict()
HOST_CLIENT_TEMPLATE['ip_wan'] = None
