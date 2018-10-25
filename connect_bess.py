from cctestbedv2 import connect_dpdk, Host
from command import get_ssh_client, exec_command
import os
import paramiko

HOST_CLIENT = {'ifname_remote': 'enp6s0f1',
               'ifname_local': 'enp6s0f0',
               'ip_lan':'192.0.0.4',
               'ip_wan':None,
               'pci':'06:00.0',
               'key_filename':None,
               'username':'rware'}

HOST_SERVER = {'ifname_remote':'enp6s0f1',
               'ifname_local':'enp6s0f1',
               'ip_lan':'192.0.0.2',
               'ip_wan':None,
               'pci':'06:00.1',
               'key_filename':None,
               'username':'rware'}

def get_ssh_config():
    ssh_config_filepath = '/users/{}/.ssh/config'.format(os.environ.get('USER'))
    ssh_config = paramiko.config.SSHConfig()
    with open(ssh_config_filepath) as f:
        ssh_config.parse(f)
    return ssh_config

def get_ip_wan(host):
    host_config = get_ssh_config().lookup(host)
    return host_config['hostname']

def get_key_filename(host):
    host_config = get_ssh_config().lookup(host)
    return host_config['identityfile'][0]

def main():
    server_ip_wan = get_ip_wan('cctestbed-server')
    server_key_filename = get_key_filename('cctestbed-server')
    client_ip_wan = get_ip_wan('cctestbed-client')
    client_key_filename = get_key_filename('cctestbed-client')

    server = HOST_SERVER
    server['ip_wan'] = server_ip_wan
    server['key_filename'] = server_key_filename
    server = Host(**server)
    
    client = HOST_CLIENT
    client['ip_wan'] = client_ip_wan
    client['key_filename'] = client_key_filename
    client = Host(**client)
    
    connect_dpdk(server, client)
    
if __name__ == '__main__':
    main()
