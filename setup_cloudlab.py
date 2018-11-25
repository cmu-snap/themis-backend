import subprocess
import os
import xml.etree.ElementTree as ET
import re
import pwd
import pickle

from cctestbedv2 import Host, get_interface_pci, connect_dpdk


USER = os.environ['USER']
# assume specific format for identity file
IDENTITY_FILE = '/users/{}/.ssh/{}_cloudlab.pem'.format(USER, USER)
    
def get_host_info():
    bess_hostname = subprocess.run('hostname', stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    bess_hostname = bess_hostname.split('.')[0]

    if bess_hostname == 'bess':
        server_hostname = 'server'
    else:
        num_testbed = bess_hostname.split('-')[-1]
        server_hostname = 'server-{}'.format(num_testbed)
        client_hostname = 'client-{}'.format(num_testbed)

    geni_namespace = {'geni':'http://www.geni.net/resources/rspec/3'}
    cloudlab_manifest = subprocess.run(['geni-get','manifest'], stdout=subprocess.PIPE).stdout
    root = ET.fromstring(cloudlab_manifest)

    server_ip_wan=root.find(
        '.geni:node[@client_id="{}"]/geni:host'.format(server_hostname),geni_namespace).attrib['ipv4']
    server_ip_lan=root.find(
        '.geni:node[@client_id="{}"]/geni:interface/geni:ip'.format(server_hostname),geni_namespace).attrib['address']
    server_if = root.findall(
        '.geni:link[@client_id="server-{}"]/geni:interface_ref'.format(bess_hostname),geni_namespace)[0].attrib['client_id'] 
    bess_server_ip =  root.find(
        '.geni:node[@client_id="{}"]/geni:interface[@client_id="{}"]/geni:ip'.format(bess_hostname, server_if),
        geni_namespace).attrib['address']
    server_ifname_local = subprocess.run("ifconfig | grep -B1 {} | head -n1 | awk '{{print $1}}'".format(
        bess_server_ip), shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    
    host_server = {'ifname_remote': None, 
                   'ifname_local': server_ifname_local,
                   'ip_lan': server_ip_lan,
                   'ip_wan': server_ip_wan,
                   'pci': get_interface_pci(server_ifname_local), 
                   'key_filename': IDENTITY_FILE,
                   'username': USER}

    client_ip_wan=root.find(
        '.geni:node[@client_id="{}"]/geni:host'.format(client_hostname),geni_namespace).attrib['ipv4']
    client_ip_lan=root.find(
        '.geni:node[@client_id="{}"]/geni:interface/geni:ip'.format(client_hostname),geni_namespace).attrib['address']
    client_if = root.findall(
        '.geni:link[@client_id="client-{}"]/geni:interface_ref'.format(bess_hostname),geni_namespace)[0].attrib['client_id'] 
    bess_client_ip =  root.find(
        '.geni:node[@client_id="{}"]/geni:interface[@client_id="{}"]/geni:ip'.format(bess_hostname, client_if),
        geni_namespace).attrib['address']
    client_ifname_local = subprocess.run("ifconfig | grep -B1 {} | head -n1 | awk '{{print $1}}'".format(
        bess_client_ip), shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    
    host_client = {'ifname_remote': None, 
                   'ifname_local': client_ifname_local,
                   'ip_lan': client_ip_lan,
                   'ip_wan': client_ip_wan,
                   'pci': get_interface_pci(client_ifname_local), 
                   'key_filename': IDENTITY_FILE,
                   'username': USER}

    create_ssh_config(host_server['ip_wan'], host_client['ip_wan'])
    server_ifname_remote = subprocess.run(
        "ssh -o StrictHostKeyChecking=no cctestbed-server ifconfig | grep -B1 {} | head -n1 | awk '{{print $1}}'".format(host_server['ip_lan']),
        shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    client_ifname_remote = subprocess.run(
        "ssh -o StrictHostKeyChecking=no cctestbed-client ifconfig | grep -B1 {} | head -n1 | awk '{{print $1}}'".format(host_client['ip_lan']),
        shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    host_server['ifname_remote'] = server_ifname_remote
    host_client['ifname_remote'] = client_ifname_remote
    host_server = Host(**host_server)
    host_client = Host(**host_client)
    
    return host_server, host_client

                   
def create_ssh_config(server_ip_wan, client_ip_wan):
    ssh_config = ('Host cctestbed-server \n'
                  '    HostName {} \n'
                  '    User {} \n'
                  '    IdentityFile {} \n'
                  'Host cctestbed-client \n'
                  '    HostName {} \n'
                  '    User {} \n'
                  '    IdentityFile {} \n').format(server_ip_wan, USER, IDENTITY_FILE,
                                                   client_ip_wan, USER, IDENTITY_FILE)
    with open('/users/{}/.ssh/config'.format(os.environ['USER']), 'w') as f:
        f.write(ssh_config)

def turn_off_tso(host_server, host_client):
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-server sudo ethtool -K {} tx off sg off tso off".format(host_server.ifname_remote)
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-client sudo ethtool -K {} tx off sg off tso off".format(host_client.ifname_remote)
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)

def add_route(host_server, host_client):
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-server sudo ip route add 192.0.0.0/24 dev {}".format(host_server.ifname_remote)
    proc = subprocess.run(cmd, shell=True)
    if proc.returncode != 0:
        print('WARNING: Assuming route already exists')
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-client sudo ip route add 192.0.0.0/24 dev {}".format(host_client.ifname_remote)
    proc = subprocess.run(cmd, shell=True)
    if proc.returncode != 0:
        print('WARNING: Assuming route already exists')

def add_arp_rule(host_server, host_client):
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-server ifconfig | grep -B1 'inet addr:{}'".format(host_server.ip_lan)
    stdout = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    server_hwaddr = re.match('.*HWaddr (.*)\n', stdout).groups()[0].strip()

    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-client ifconfig | grep -B1 'inet addr:{}'".format(host_client.ip_lan)
    stdout = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    client_hwaddr = re.match('.*HWaddr (.*)\n', stdout).groups()[0].strip()

    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-server sudo arp -s {} {}".format(host_client.ip_lan, client_hwaddr)
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)

    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-client sudo arp -s {} {}".format(host_server.ip_lan, server_hwaddr)
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)

def setup_nat():
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client /bin/bash /opt/cctestbed/setup-nat.sh'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)

def connect_bess(host_server, host_client):
    cmd= 'sudo sysctl vm.nr_hugepages=1024'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'echo 1024 | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'echo 1024 | sudo tee /sys/devices/system/node/node1/hugepages/hugepages-2048kB/nr_hugepages'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = '/opt/bess/build.py'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    connect_dpdk(host_server, host_client)

def export_environs(host_server, host_client):
    with open('/opt/cctestbed/host_info.pkl', 'wb') as f:  
        pickle.dump([host_server, host_client], f)

def add_disk_space():
    cmd = ('sudo /usr/local/etc/emulab/mkextrafs.pl -f -r sdb -s 1 /mnt '
           '&& sudo mkdir /mnt/tmp '
           '&& sudo chmod 1777 /mnt/tmp '
           '&& sudo cp /tmp/* /mnt/tmp '
           '&& sudo  rm -r /tmp '
           '&& sudo ln -s /mnt/tmp /tmp '
           '&& sudo chown -R rware:dna-PG0 /tmp/*')
    proc = subprocess.run(cmd, shell=True)
    if proc.returncode != 0:
        print('WARNING: Assuming disk space already added')

    cmd = ("sudo /usr/local/etc/emulab/mkextrafs.pl -f -r sdb -s 1 /mnt "
           "&& sudo mkdir /mnt/tmp "
           "&& sudo chmod 1777 /mnt/tmp "
           "&& sudo cp /tmp/* /mnt/tmp "
           "&& sudo rm -r /tmp "
           "&& sudo ln -s /mnt/tmp /tmp "
           "&& sudo chown -R rware:dna-PG0 /tmp/*")
    proc = subprocess.run("ssh -o StrictHostKeyChecking=no cctestbed-server '{}'".format(
        cmd), shell=True)
    if proc.returncode != 0:
        print('WARNING: Assuming disk space already added')
def load_all_ccalgs():
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-server 'for f in /lib/modules/$(uname -r)/kernel/net/ipv4/tcp_*; do sudo modprobe $(basename $f .ko); done'"
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-server sudo rmmod tcp_probe'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-client 'for f in /lib/modules/$(uname -r)/kernel/net/ipv4/tcp_*; do sudo modprobe $(basename $f .ko); done'"
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client sudo rmmod tcp_probe'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-server 'echo net.ipv4.tcp_allowed_congestion_control=cubic reno bic bbr cdg dctcp highspeed htcp hybla illinois lp nv scalable vegas veno westwood yeah | sudo tee -a /etc/sysctl.conf'"
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-server sudo sysctl -p'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = "ssh -o StrictHostKeyChecking=no cctestbed-client 'echo net.ipv4.tcp_allowed_congestion_control=cubic reno bic bbr cdg dctcp highspeed htcp hybla illinois lp nv scalable vegas veno westwood yeah | sudo tee -a /etc/sysctl.conf'"
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client sudo sysctl -p'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    
def increase_win_sizes():
    cmds = [
    'echo net.core.wmem_max = 16777216 | sudo tee -a /etc/sysctl.conf',
    'echo net.core.rmem_max = 16777216 | sudo tee -a /etc/sysctl.conf',
    'echo net.core.wmem_default = 16777216 | sudo tee -a /etc/sysctl.conf', 
    'echo net.core.rmem_default = 16777216 | sudo tee -a /etc/sysctl.conf',
    'echo net.ipv4.tcp_wmem = 10240 16777216 16777216 | sudo tee -a /etc/sysctl.conf',
    'echo net.ipv4.tcp_rmem = 10240 16777216 16777216 | sudo tee -a /etc/sysctl.conf',
    'sudo sysctl -p'
    ]
    for cmd in cmds:
        proc = subprocess.run('ssh -o StrictHostKeyChecking=no cctestbed-server {}'.format(cmd), shell=True)
        assert(proc.returncode == 0)
        proc = subprocess.run('ssh -o StrictHostKeyChecking=no cctestbed-client {}'.format(cmd), shell=True)
        assert(proc.returncode == 0)
    
def main():
    host_server, host_client = get_host_info()
    increase_win_sizes()
    turn_off_tso(host_server, host_client)
    add_route(host_server, host_client)
    add_arp_rule(host_server, host_client)
    setup_nat()
    load_all_ccalgs()
    export_environs(host_server, host_client)
    add_disk_space()
    connect_bess(host_server, host_client)

if __name__ == '__main__':
    main()


    
