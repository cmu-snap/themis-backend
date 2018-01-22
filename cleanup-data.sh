TCPDUMP_LOG=$1
TARFILE=$2
EXP_NAME=$3

# generate csv
tshark -T fields -E separator=, -E quote=d -r $TCPDUMP_LOG -e frame.time_relative -e tcp.len -e tcp.analysis.ack_rtt > /tmp/$EXP_NAME.csv

# tar results
tar -cvzf $TARFILE -C /tmp /tmp/*$EXP_NAME*
