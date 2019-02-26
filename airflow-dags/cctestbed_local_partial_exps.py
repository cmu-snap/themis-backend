from airflow import DAG
from airflow.operators.bash_operator import BashOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2015, 6, 1),
    "email": ["airflow@airflow.com"],
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 5,
    "retry_delay": timedelta(minutes=1),
    "queue":"cctestbed_aws",
    # 'queue': 'bash_queue',
    # 'pool': 'backfill',
    # 'priority_weight': 10,
    # 'end_date': datetime(2016, 1, 1),
}

with DAG("cctestbed_local_partial",
         default_args=default_args,
         schedule_interval=None) as dag:
    run_experiment = BashOperator(task_id='run_experiment',
                                  bash_command=(
                                      "cd /opt/cctestbed && "
    "python3.6 /opt/cctestbed/ccalg_predict_iperf.py -r local -c {{ dag_run.conf['cca'] }} -n {{ dag_run.conf['ntwrk'] }} --force"))

