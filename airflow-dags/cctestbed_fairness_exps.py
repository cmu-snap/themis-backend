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
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
    "queue":"cca_predict",
}

with DAG("cctestbed_fairness",
         default_args=default_args,
         schedule_interval=None) as dag:
    website_fairness = BashOperator(
        task_id="website_fairness",
        bash_command=("cd /opt/cctestbed && "
                      "python3.6 /opt/cctestbed/ccalg_fairness.py {{ dag_run.conf['cmdline_args'] }} && snakemake -j 40 -s /opt/cctestbed/fairness_websites.snakefile --keep-going -d /tmp/ --latency-wait 120"))
    
