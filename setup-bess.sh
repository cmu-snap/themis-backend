install_bess() {
    cd /opt/
    sudo git clone https://github.com/NetSys/bess.git
    sudo chown -R $USER:dna-PG0 /opt/bess
    git checkout 523f768ff9d9cac59e42b2e0a5c29c182232f3b5
    sudo apt-get update
    sudo apt-get install -y software-properties-common
    sudo apt-add-repository -y ppa:ansible/ansible
    sudo apt-get update
    sudo apt-get install -y ansible
    ansible-playbook -K -t package -i localhost, -c local env/bess.yml
    sudo reboot
}

# must enable hugepages every time after a restart
# TOOD: make this permanent
enable_hugepages() {
    sudo sysctl vm.nr_hugepages=1024
    echo 1024 | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-2048kB/nr_hugepages
    echo 1024 | sudo tee /sys/devices/system/node/node1/hugepages/hugepages-2048kB/nr_hugepages
    sudo systcl -p
}

# might have to run this twice to get it to work
build_bess() {
    opt/cctestbed/setup-links.sh
    pip install protobuf
    /opt/bess/build.py protobuf
    /opt/bess/build.py
}

# connect bess to physical NIC ports
connect_bess() {
    enable_hugepages
    cd /opt/cctestbed && python3.6 connect_bess.py
}

$1

