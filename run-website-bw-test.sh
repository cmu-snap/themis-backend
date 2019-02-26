WEBSITE=$1
URL=$2

OUTPUT_FILENAME=/tmp/website-bw-test-$(hostname -s).csv
PCAP_FILENAME=/tmp/$WEBSITE.pcap

for i in $(seq 1 3)
do
	 touch $OUTPUT_FILENAME
	 printf $WEBSITE, >> $OUTPUT_FILENAME
	 
	 sudo tcpdump -n --packet-buffered --snapshot-length=65535 --interface enp1s0f0 -w $PCAP_FILENAME host $WEBSITE &
	 timeout 30s wget -O/dev/null -q --no-check-certificate --no-cache --delete-after --connect-timeout=10 --tries=3 -P /tmp/ $URL
	 sudo pkill tcpdump
	 
	 capinfos -TMmruy $PCAP_FILENAME >> $OUTPUT_FILENAME || echo ,, >> $OUTPUT_FILENAME
	 sudo rm -f $PCAP_FILENAME
done
