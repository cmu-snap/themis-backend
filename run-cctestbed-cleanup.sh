EXP_NAME=$1
TAR_FILENAME=$2
EXP_CONFIG_FILENAME=$3
SERVER_TCPDUMP=$4
LOGS=( "$@" )
LOGS=${LOGS[@]:4}

# check if experiment has any data in the queue
queue_has_data() {
    QUEUE_FILE=/tmp/queue-$EXP_NAME.txt
    if [ -s $QUEUE_FILE ]
    then
	return 0
    else
	# output to stderr
	( >&2 echo WARNING: Found empty queue file $QUEUE_FILE for experiment $EXP_NAME. )
 	return 1
    fi
}

move_config_file() {
    if [ -e $EXP_CONFIG_FILENAME ]
    then
	cp $EXP_CONFIG_FILENAME /tmp/
	return 0
    else
	( >&2 echo WARNING: Config file $EXP_CONFIG_FILENAME does not exist for experiment $EXP_NAME. )
	return 1
    fi
}

get_tcpdump_rtts() {
    tshark -r "$SERVER_TCPDUMP" -Tfields -e frame.time_relative -e tcp.analysis.ack_rtt > /tmp/rtt-$EXP_NAME.txt
}

get_bitrate() {
    capinfos -iTm $SERVER_TCPDUMP > /tmp/capinfos-$EXP_NAME.txt
}

if queue_has_data
then
    get_tcpdump_rtts
    get_bitrate
    if move_config_file
    then
	cd /tmp && tar -czf $TAR_FILENAME $(cd /tmp/ && ls $LOGS $(basename $EXP_CONFIG_FILENAME) 2> /dev/null)
	rm -f /tmp/$(basename $EXP_CONFIG_FILENAME)
	cd /tmp/ && rm -f $LOGS
	# added for website experiments 
	mkdir -p /tmp/data-tmp/
	cp $TAR_FILENAME /tmp/data-tmp/
	mkdir -p /tmp/data-raw/
	mv $TAR_FILENAME /tmp/data-raw/
    else
	cd /tmp && tar -czf $TAR_FILENAME $(ls $LOGS 2> /dev/null)
	cd /tmp/ && rm -f $LOGS
	# added for website experiments 
	mkdir -p /tmp/data-tmp/
	cp $TAR_FILENAME /tmp/data-tmp/
	mkdir -p /tmp/data-raw/
	mv $TAR_FILENAME /tmp/data-raw/
    fi
else
    :
fi


#echo EXP_NAME=$EXP_NAME
#echo TAR_FILENAME=$TAR_FILENAME
#echo EXP_CONFIG_FILENAME=$EXP_CONFIG_FILENAME
#echo LOGS=$LOGS


