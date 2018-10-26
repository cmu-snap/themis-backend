sudo iptables --flush
sudo iptables --table nat --flush
sudo iptables --delete-chain
sudo iptables --table nat --delete-chain
echo 1 | sudo tee -a /proc/sys/net/ipv4/ip_forward
sudo iptables -t nat -A PREROUTING -i enp11s0f0 --source 35.160.118.3 -j DNAT --to-destination 192.0.0.4
sudo iptables -t nat -A POSTROUTING --destination 192.0.0.4 -o ens13 -j SNAT --to-source 192.0.0.1
sudo iptables -A FORWARD -i enp11s0f0 -j ACCEPT
