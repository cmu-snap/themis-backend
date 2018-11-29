from airflow.hooks.mysql_hook import MySqlHook

airflow_db = MySqlHook('airflow_db')

get_completed_experiments_query = ("SELECT hostname, unixname, execution_date, end_date "
                                   "FROM task_instance  "
                                   "WHERE task_id='run_experiment' AND state='success';")
successful_experiments = airflow_db.get_records(airflow_db)
#for hostname, unixname, execution_date in succesful_experiments:
    
    
