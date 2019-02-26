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
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
    "queue":"cca_predict",
    # 'queue': 'bash_queue',
    # 'pool': 'backfill',
    # 'priority_weight': 10,
    # 'end_date': datetime(2016, 1, 1),
}

with DAG("cctestbed_website",
         default_args=default_args,
         schedule_interval=None) as dag:
    classify_wesbite_flows = BashOperator(
        task_id="classify_website_flows",
        bash_command=("cd /opt/cctestbed && "
                      "python3.6 /opt/cctestbed/ccalg_predict.py {{ dag_run.conf['cmdline_args'] }}; snakemake -j 40 -s /opt/cctestbed/classify_websites.snakefile --keep-going -d /tmp/ --latency-wait 120 || snakemake -j 40 -s /opt/cctestbed/classify_websites.snakefile --keep-going -d /tmp/ --latency-wait 120"))
    
