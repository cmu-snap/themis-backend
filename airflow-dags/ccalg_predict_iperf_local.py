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

ntwrk_conditions = [(5,35,16), (5,85,64), (5,130,64), (5,275,128), (10,35,32), (10,85,128), (10,130,128), (10,275,256), (15,35,64), (15,85,128), (15,130,256), (15,275,512)]


    
"""
with DAG("cctestbed_local",
         default_args=default_args,
         schedule_interval=None) as dag:
    run_experiment = BashOperator(task_id='run_experiment',
                                  bash_command=(
                                      "cd /opt/cctestbed && "
    "python3.6 /opt/cctestbed/ccalg_predict_iperf.py -r local -c {{ dag_run.conf['cca'] }} --force"))

"""
