from airflow import DAG
from airflow.operators.bash_operator import BashOperator
from datetime import datetime, timedelta

import ccalg_predict

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
    # 'queue': 'bash_queue',
    # 'pool': 'backfill',
    # 'priority_weight': 10,
    # 'end_date': datetime(2016, 1, 1),
}

def run_website_experiment(**kwargs):
    website = kwargs['dag_run'].conf.get('website')
    url = kwargs['dag_run'].conf.get('url')
    btlbw = kwargs['dag_run'].conf.get('btlbw')
    queue_size = kwargs['dag_run'].conf.get('queue_size')
    rtt = kwargs['dag_run'].conf.get('rtt')
    experiment = ccalg_predict.run_experiment(website, url, btlbw, queue_size, rtt, force=True, compress_logs=False)
    return experiment


with DAG("cctestbed_website",
         default_args=default_args,
         schedule_interval=None) as dag:
    task = PythonOperator(
        task_id='sleep_for_' + str(i),
        python_callable=my_sleeping_function,
        op_kwargs={'random_base': float(i) / 10},
        dag=dag,
    )

    run_experiment = PythonOperator(task_id='run_experiment',
                                    provide_context=True,
                                    python_callable=run_website_experiment,
                                    retries=3)
                                    #bash_command=(
                                    #    "cd /opt/cctestbed && "
                                    #    "python3.6 /opt/cctestbed/ccalg_predict_iperf.py {{ dag_run.conf['cmdline_args'] }}"))

    compute_flow_features = PythonOperator(task_id='compute_flow_features',
                                         bash_command=
    
