install_iperf3() {
    # install latest version of iperf3
    #wget http://downloads.es.net/pub/iperf/iperf-3-current.tar.gz
    sudo apt-get -y update
    sudo apt-get -y install build-essential
    sudo apt-get -y install emacs24
    wget  https://github.com/esnet/iperf/archive/3.5.tar.gz
    #tar -xzf iperf-3-current.tar.gz
    tar -xvzf 3.5.tar.gz
    cd iperf-3*
    ./configure && make && sudo make install
    sudo apt-get -y remove lib32z1
    sudo apt-get -y install lib32z1 # need this for some reason for iperf3
    cd ..
    sudo rm -r iperf-3* 3.5.tar.gz
}

upgrade_kernel() {
    # install new version of the kernel 4.13
    sudo wget http://kernel.ubuntu.com/~kernel-ppa/mainline/v4.13/linux-headers-4.13.0-041300_4.13.0-041300.201709031731_all.deb
    sudo wget http://kernel.ubuntu.com/~kernel-ppa/mainline/v4.13/linux-headers-4.13.0-041300-generic_4.13.0-041300.201709031731_amd64.deb
    sudo wget http://kernel.ubuntu.com/~kernel-ppa/mainline/v4.13/linux-image-4.13.0-041300-generic_4.13.0-041300.201709031731_amd64.deb
    sudo dpkg -i *.deb
    sudo rm *.deb
    sudo sed -i -e 's/GRUB_DEFAULT=0/GRUB_DEFAULT="Advanced options for Ubuntu>Ubuntu, with Linux 4.13.0-041300-generic"/g' /etc/default/grub
    sudo update-grub
    sudo reboot
    #reboot
    # after reboot:
    #modprobe tcp_bbr
}

$1
