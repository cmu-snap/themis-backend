import subprocess
import getpass

def update_git(git_secret, host):
    #cmd = 'git add /opt/cctestbed/airflow-dags/* && git commit -m "Autocommit: Syncing airflow dags" && git push https://rware:{}@github.com/rware/cctestbed.git cloudlab'
    #proc = subprocess.run(cmd, shell=True)
    #assert(proc.returncode == 0)
    
    cmd = 'ssh {} "cd /opt/cctestbed/ && git pull https://rware:{}@github.com/rware/cctestbed.git cloudlab"'.format(host, git_secret)
    proc = subprocess.run(cmd, shell=True)
    if proc.returncode != 0:
        raise ValueError('Error updating git for host: {}'.format(host))

def main(git_secret):
    for host in 'bess-2','bess-3','bess-4','bess-5':
        update_git(git_secret, host)

if __name__ == '__main__':
    git_secret = getpass.getpass('Github secret: ')
    main(git_secret)
