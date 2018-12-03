configure() {
    BESS=$2
    ssh -t $BESS "cd /opt/cctestbed && git pull" && \
	ssh $BESS "sudo pip3.6 install Celery" && \
	ssh $BESS "export AIRFLOW_GPL_UNIDECODE=1; sudo pip3.6 install apache-airflow[celery,ssh]" && \
	ssh $BESS "sudo mkdir /opt/airflow" && \
	ssh $BESS "sudo chown -R rware:dna-PG0 /opt/airflow" &&\
	ssh $BESS "sudo mkdir /usr/lib/systemd/system" && \
	ssh $BESS "sudo apt-get install -y libmysqlclient-dev" && \
	ssh $BESS "sudo pip3.6 install mysqlclient" && \
	ssh $BESS "ln -s /opt/cctestbed/airflow-dags /opt/airflow/dags" && \
	scp /opt/airflow/airflow.cfg.cloudlab $BESS:/opt/airflow/airflow.cfg && \
	scp /opt/airflow/airflow.cloudlab $BESS:/opt/airflow/airflow && \
	scp /opt/airflow/airflow-worker.service $BESS:/opt/airflow/ && \
	ssh $BESS "sudo mv /opt/airflow/airflow-worker.service /usr/lib/systemd/system/" && \
	ssh $BESS "sudo service airflow-worker start"
}

configure
