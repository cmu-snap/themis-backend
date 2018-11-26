PRIVATE_IP=$1
sudo iptables --flush
sudo iptables --table nat --flush
sudo iptables --delete-chain
sudo iptables --table nat --delete-chain
echo 1 | sudo tee -a /proc/sys/net/ipv4/ip_forward
PUBLIC_IP=$(ifconfig enp1s0f0 | grep 'inet addr:' | cut -d: -f2 | cut -d' ' -f1)
sudo iptables -t nat -A POSTROUTING --source $PRIVATE_IP -o enp1s0f0 -j SNAT --to $PUBLIC_IP
