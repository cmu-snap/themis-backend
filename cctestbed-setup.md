# cctestbed Setup

Setup requires 3 machines, server, bess, and client. The server and client each need one interface connected to bess.  On Cloudlab this is done with a bess machine that has two interfaces, one connects to server, and one to client. Routing tables on the server and client are updated to all traffic going towards each other is sent through the bess machine. The machines cannot "ping" each other if BESS is not running. 

server <-----------> bess <-----------> client


The cctestbed scripts assume there is an ssh config on the bess machine (~/.ssh/config) that looks like this:
```sh
Host cctestbed-server
     HostName 128.104.222.116
     User rware
     IdentityFile ~/.ssh/rware_cloudlab.pem
Host cctestbed-client
     HostName 128.104.222.183
     User rware
     IdentityFile ~/.ssh/rware_cloudlab.pem
```

The setup-cloudlab.py scripts will create this file. Note, this file will not work outside of Cloudlab.

Below are instructions on how to get a testbed setup on Cloudlab.

Parenthesis indicate which machine to run commands on. Parts of commands that are user specific are illustrated as environment variables which should be adjusted for the user running the Cloudlab setup.

1. Create ssh keys just for Cloudlab so that the bess machine can ssh into the client and server machines. Add the pub key to Cloudlab and copy the private key to the the bess machine to `$HOME/.ssh/`. The prviate key must be named `$USER_cloudlab.pem` for `setup-cloudlab.py` scripts to work.
2. (bess, server, client) Get cctestbed code:
    ```sh
    cd /opt/
    # the user group is of course optional here
    # on Cloudlab this is set to dna-PG0
    sudo chown -R $USER:$USER_GROUP /opt
    # need the right permission to do this, cctestbed is private git repo
    # this does store git password in clear text in git configs
    git clone https://$GIT_USERNAME:$GIT_SECRET@github.com/rware/cctestbed.git 
    # use cloudlab branch
    git checkout remotes/origin/cloudlab
    ```
3. (bess, server, client) Update the kernel to v4.13. This will restart the machines when complete.
    ```sh
    cd /opt/cctestbed && ./setup-kernel.sh upgrade_kernel
    ```
4. (bess) Install python3.6 and cctestbed dependencies
    ```sh
    sudo add-apt-repository ppa:deadsnakes/ppa
    sudo apt-get update
    sudo apt-get install python3.6
    sudo apt-get install python3.6-dev
    sudo apt-get install tshark

    cd /tmp
    wget https://bootstrap.pypa.io/get-pip.py
    sudo python3.6 get-pip.py
    rm get-pip.py

    sudo pip3 install paramiko 
    sudo pip3 install pyyaml
    sudo pip3 install ipython
    sudo pip3 install pytest
    sudo pip3 install psutil
    sudo pip3 install pandas
    ```
5. (bess, server, client) Install nping from nmap.
    ```sh
    sudo apt-get install nmap
    ```
7. (bess) Install & build bess.
    ```sh
    cd /opt/cctestbed 
    # NOTE: install_bess script needs to be slightly modified for non-Cloudlab environment
    ./setup_bess.sh install_bess
    ./setup-bess.sh enable_hugepages()
    ```
8. (server, client) Install iperf3. (Only required to run controlled experiments)
    ```sh
    cd /opt/cctestbed && ./setup_kernel.sh install_iperf3
    ```
9. (client, server) Install modified tcpprobe. (Only required to run controlled experiments)
    ```sh
    cd /opt/cctestbed/tcp_bbr_measure && make && sudo insmod tcp_probe_ray.ko
    ```
10. (bess) Increase window sizes, turn off segmentation offloading, add routes, add arp rules, setup the nat, load all congestion control modules, connect interfaces to DPDK. Increase disk space. Store experiment results on BESS machine and need extra space on server in case downloaded files don't get deleted by wget. **THIS SCRIPT DOES NOT WORK OUTSIDE OF CLOUDLAB.**
    ```sh
    cd /opt/cctestbed && python3.6 setup_cloudlab.py
    ```
    
On system restart you must re-run turning off segmentation offloading, connecting DPDK to bess, enable huge pages, and load kernel modules.

# Running cctestbed experiment

iperf AWS experiment: (requires aws-cli and credentials setup)
```sh
cd /opt/cctestbed && python3.6 /opt/cctestbed/ccalg_predict_iperf.py -r us-west-1 -c cubic -n 15 35 64
```

iperf local experiment: 
```sh
cd /opt/cctestbed && python3.6 /opt/cctestbed/ccalg_predict_iperf.py -r local -c cubic -n 15 35 64
```

website experiment:
```sh
cd /opt/cctestbed && python3.6 /opt/cctestbed/ccalg_predict.py --website python.org "https://www.python.org/ftp/python/3.7.0/python-3.7.0-macosx10.6.pkg" --network 15 35
```

Rolling log file is /tmp/cctestbed-experiments.log

Experiment Data output is under `/tmp/$EXP_NAME.tar.gz`. (Probs not the best place to keep data because it will be deleted on system restart)


# Running many cctestbed experiments on a cluster using Airflow 

## Airflow setup

Airflow is a workflow management system that is used to distribute experiment jobs across cctestbeds and automatically re-run if there is a failure. The Airflow scheduler and webserver are run from Justine's potato machine. The scheduler is in charge of distributing jobs to the workers. The workers are run on the bess nodes of cctestbeds.

The Airflow webserver shows the status of cctestbed jobs running here: https://128.2.208.104:8080. A username and password is needed to access: https://airflow.apache.org/security.html#web-authentication


1. Add a host alias for machine to potato ssh config.
    ```sh
    Host $BESS_NODE_ALIAS
         HostName $BESS_NODE_IP
         User $USER
         IdentityFile $HOME/.ssh/$USER_cloudlab.pem
    ```
2. Install and run airflow worker.
    ```sh
    cd /opt/cctestbed && ./setup-airflow $BESS_NODE_ALIAS
    ```

Note: The setup-airflow script assumes the worker will listen to the cctestbed_aws queue. 

## Running experiments through Airflow

Example: run 1 reno iperf3 experiment

```sh
airflow trigger_dag cctestbed_local_partial --conf '{"cca":"reno", "ntwrk":"15 130 256"}'
```

The status of the job can be viewed at: https://128.2.208.104:8080.

# Some notable cctestbed code TODOs:

- Flow classification is currently a semi-manual process of downloading data to potato and running scripts for the classification. However, under certain conditions experiments may need to be re-run based on the output of the classification. Next task is to incorporate in Airflow tasks running classification and re-running experiments (with some threshold on the number of re-tries).

- Change data output from /tmp to /opt/cctestbed/data-raw

- Make sure bad data and incompleted experiment data is deleted from bess node

- Make sure website download data is deleted by server node