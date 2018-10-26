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


HOST_CLIENT = Host(**{'ifname_remote': 'enp6s0f1',
                      'ifname_local': 'enp6s0f0',
                      'ip_lan':'192.0.0.4',
                      'ip_wan':get_host_ip_wan('cctestbed-client'),
                      'pci':'06:00.0',
                      'key_filename':get_host_key_filename('cctestbed-client'),
                      'username':get_host_username('cctestbed-client')})

HOST_CLIENT_TEMPLATE = {'ifname_remote': 'enp6s0f1',
                      'ifname_local': 'enp6s0f0',
                      'ip_lan':'192.0.0.4',
                      'ip_wan':None,
                      'pci':'06:00.0',
                      'key_filename':get_host_key_filename('cctestbed-client'),
                      'username':get_host_username('cctestbed-client')}

HOST_SERVER = Host(**{'ifname_remote':'enp6s0f1',
               'ifname_local':'enp6s0f1',
               'ip_lan':'192.0.0.2',
               'ip_wan':get_host_ip_wan('cctestbed-server'),
               'pci':'06:00.1',
               'key_filename':get_host_key_filename('cctestbed-server'),
               'username':get_host_username('cctestbed-server')})


