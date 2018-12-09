NUM_TESTBEDS=$1
# need git secret to do git updates
echo -n GIT SECRET:
read -s GIT_SECRET
echo 

create_ssh_alias () {
    bess_node=$1

    echo Host $bess_node >> ~/.ssh/config
    echo "    HostName $(dig +short bess-$i.cca-predict.dna-PG0.wisc.cloudlab.us cname)" >> /home/ranysha/.ssh/config
    echo "    User rware" >> /home/ranysha/.ssh/config
    echo "    IdentityFile /home/ranysha/.ssh/rware_cloudlab.pem" >> /home/ranysha/.ssh/config
    echo "    StrictHostKeyChecking no" >> /home/ranysha/.ssh/config
    echo >> /home/ranysha/.ssh/config

}

update_git() {
    bess_node=$1
    ssh $bess_node "cd /opt/cctestbed && git pull https://rware:$GIT_SECRET@github.com/rware/cctestbed.git cloudlab"
}

setup_cloudlab() {
    bess_node=$1
    ssh $bess_node python3.6 /opt/cctestbed/setup_cloudlab.py
    scp $bess_node:/opt/cctestbed/host_info.pkl /opt/cctestbed/cctestbed_host_info_$bess_node.pkl
}

configure_aws() {
    bess_node=$1
    scp /home/ranysha/.ssh/rware*.pem $bess_node:~/.ssh/
    ssh $bess_node "mkdir ~/.aws"
    scp /home/ranysha/.aws/* $bess_node:~/.aws/
}

setup_airflow() {
    bess_node=$1
    ssh $bess_node "sudo pip3.6 install Celery" && \
	ssh $bess_node "export AIRFLOW_GPL_UNIDECODE=1; sudo pip3.6 install apache-airflow[celery,ssh]" && \
	ssh $bess_node "sudo mkdir /opt/airflow" && \
	ssh $bess_node "sudo chown -R rware:dna-PG0 /opt/airflow" &&\
	ssh $bess_node "sudo mkdir /usr/lib/systemd/system" && \
	ssh $bess_node "sudo apt-get install -y libmysqlclient-dev" && \
	ssh $bess_node "sudo pip3.6 install mysqlclient" && \
	ssh $bess_node "ln -s /opt/cctestbed/airflow-dags /opt/airflow/dags" && \
	scp /opt/airflow/airflow.cfg.cloudlab $bess_node:/opt/airflow/airflow.cfg && \
	scp /opt/airflow/airflow.cloudlab $bess_node:/opt/airflow/airflow && \
	scp /opt/airflow/airflow-worker.service $bess_node:/opt/airflow/ && \
	ssh $bess_node "sudo mv /opt/airflow/airflow-worker.service /usr/lib/systemd/system/" && \
	ssh $bess_node "sudo service airflow-worker start"
}

    
# clear ssh config file
echo '' > ~/.ssh/config

for i in $(seq 1 $NUM_TESTBEDS)
do
    bess_node_name=bess-$i
    echo Configuring $bess_node_name...
    # add aliases for each bess node
    echo [$bess_node_name] Creating ssh alias...
    create_ssh_alias $bess_node_name && \
        echo [$bess_node_name] Updating git... && \
	update_git $bess_node_name && \
	echo [$bess_node_name] Configuring aws... && \
	configure_aws $bess_node_name && \
	echo [$bess_node_name] Installing cctestbed... && \
	setup_cloudlab $bess_node_name && \
	echo [$bess_node_name] Installing airflow... && \	
	setup_airflow $bess_node_name
done
