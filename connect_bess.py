from cctestbedv2 import connect_dpdk, Host
from command import get_ssh_client, exec_command
from config import HOST_CLIENT, HOST_SERVER
import os
import paramiko

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
