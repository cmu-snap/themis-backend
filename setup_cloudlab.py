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

def setup_nat(host_server, host_client):
    cmds = ['sudo iptables --flush',
            'sudo iptables --table nat --flush',
            'sudo iptables --delete-chain',
            'sudo iptables --table nat --delete-chain',
            'echo 1 | sudo tee -a /proc/sys/net/ipv4/ip_forward',
            'sudo iptables -t nat -A POSTROUTING --source {} -o enp1s0f0 -j SNAT --to {}'.format(host_server.ip_lan, host_client.ip_wan)]

    for cmd in cmds:
        proc = subprocess.run(
            'ssh -o StrictHostKeyChecking=no cctestbed-client {}'.format(cmd),
            shell=True)
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
    cmd = ('sudo /usr/local/etc/emulab/mkextrafs.pl -f -r sdc -s 1 /mnt '
           '&& sudo mkdir /mnt/tmp '
           '&& sudo chmod 1777 /mnt/tmp '
           '&& sudo cp -R /tmp/* /mnt/tmp '
           '&& sudo  rm -r /tmp '
           '&& sudo ln -s /mnt/tmp /tmp '
           '&& sudo chown -R {}:dna-PG0 /tmp/*'.format(USER))
    proc = subprocess.run(cmd, shell=True)
    if proc.returncode != 0:
        print('WARNING: Assuming disk space already added')

    cmd = ("sudo /usr/local/etc/emulab/mkextrafs.pl -f -r sdb -s 1 /mnt "
           "&& sudo mkdir /mnt/tmp "
           "&& sudo chmod 1777 /mnt/tmp "
           "&& sudo cp -R /tmp/* /mnt/tmp "
           "&& sudo rm -r /tmp "
           "&& sudo ln -s /mnt/tmp /tmp "
           "&& sudo chown -R {}:dna-PG0 /tmp/*".format(USER))
    proc = subprocess.run("ssh -o StrictHostKeyChecking=no cctestbed-server '{}'".format(
        cmd), shell=True)
    if proc.returncode != 0:
        print('WARNING: Assuming disk space already added')
    proc = subprocess.run("ssh -o StrictHostKeyChecking=no cctestbed-client '{}'".format(
        cmd), shell=True)
    if proc.returncode != 0:
        print('WARNING: Assuming disk space already added')

def setup_links():
    proc = subprocess.run("./setup-links.sh", shell=True)
    assert(proc.returncode == 0)
        
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
        proc = subprocess.run('ssh -o StrictHostKeyChecking=no cctestbed-server "{}"'.format(cmd), shell=True)
        assert(proc.returncode == 0)
        proc = subprocess.run('ssh -o StrictHostKeyChecking=no cctestbed-client "{}"'.format(cmd), shell=True)
        assert(proc.returncode == 0)

def setup_webserver(host_client):
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "sudo apt-get install -y apache2"'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "sudo service apache2 stop"'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "cd /var/www/html && sudo wget --no-check-certificate --adjust-extension --span-hosts --convert-links --backup-converted --page-requisites www.nytimes.com"'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "echo Listen {}:1234 | sudo tee -a /etc/apache2/apache2.conf"'.format(host_client.ip_lan)
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "sudo service apache2 start"'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)

    # install chrome on the server
    server_cmds = ['sudo apt-get update',
            'sudo apt-get install -y libappindicator1 fonts-liberation ffmpeg',
            'wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb',
            'sudo dpkg -i google-chrome*.deb',
            'sudo apt-get install -yf', # install missing dependencies
            'rm google-chrome-stable_current_amd64.deb']
    for cmd in server_cmds:
        proc = subprocess.run('ssh -o StrictHostKeyChecking=no cctestbed-server {}'.format(cmd), shell=True)

    # add link for video data
    proc = subprocess.run('ssh -o StrictHostKeyChecking=no cctestbed-client "ln -fs /mnt/video/* /var/www/html/"', shell=True)

    # add index.html and javascript
    proc = subprocess.run('scp -o StrictHostKeyChecking=no /opt/cctestbed/www/* cctestbed-client:/var/www/html/"', shell=True)
    
    """
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "sudo chown -R rware:dna-PG0 /var/www"'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    # this command takes like an hour! wget parallel?
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "cd /var/www/html && wget -r ftp://ftp-itec.uni-klu.ac.at/pub/datasets/DASHDataset2014/BigBuckBunny/10sec/"'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)
    cmd = 'ssh -o StrictHostKeyChecking=no cctestbed-client "cd /var/www/html && mv ftp-itec.uni-klu.ac.at/pub/datasets/DASHDataset2014/BigBuckBunny/10sec/* ."'
    proc = subprocess.run(cmd, shell=True)
    assert(proc.returncode == 0)

    # install chrome on the server
    cmds = ['sudo apt-get update',
            'sudo apt-get install -y libappindicator1 fonts-liberation ffmpeg',
            'wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb',
            'sudo dpkg -i google-chrome*.deb',
            'sudo apt-get install -f' # install missing dependencies
            'rm google-chrome-stable_current_amd64.deb']
    """

def add_disk_space_apache():
    cmds = [
        'sudo /usr/local/etc/emulab/mkextrafs.pl -f -r sdb -s 1 /mnt',
        'sudo mkdir /mnt/html',
        'sudo chown -R rware:dna-PG0 /mnt/html',
        'cp -R /var/www/html/* /mnt/html',
        'rm -r /var/www/*']

def setup_data_analysis():
    cmds = [
        "sudo pip3.6 install snakemake",
        "sudo pip3.6 install tables",
        "sudo pip3.6 install matplotlib",
        "sudo pip3.6 install sklearn",
        "sudo pip3.6 install fastdtw",
        "sudo mkdir /tmp/data-raw",
        "sudo mkdir /tmp/data-processed",
        "sudo mkdir /tmp/data-websites",
        #"sudo mv /tmp/*.tar.gz /tmp/data-raw/",
        "sudo chown -R {}:dna-PG0 /tmp/data-websites".format(USER),
        "sudo chown -R {}:dna-PG0 /tmp/data-processed".format(USER),
        "sudo chown -R {}:dna-PG0 /tmp/data-raw".format(USER)]
    for cmd in cmds:
        proc = subprocess.run(cmd, shell=True)
        assert(proc.returncode == 0)

        
    
def main():
    # check if identity file exists & works
    if not os.path.isfile(IDENTITY_FILE):
        print('Could not find identify file: {}. Please add it to this machine to run cloudlab setup'.format(IDENTITY_FILE))
        exit(1)

    host_server, host_client = get_host_info()
    increase_win_sizes()
    turn_off_tso(host_server, host_client)
    add_route(host_server, host_client)
    add_arp_rule(host_server, host_client)
    setup_nat(host_server, host_client)
    load_all_ccalgs()
    export_environs(host_server, host_client)
    add_disk_space()
    connect_bess(host_server, host_client)
    setup_webserver(host_client)
    setup_data_analysis()
    setup_links()
    
if __name__ == '__main__':
    main()


    
