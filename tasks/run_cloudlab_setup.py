import argparse
import subprocess

def parse_args():
    parser = argparse.ArgumentParser(description='Run cloudlab setup')
    parser.add_argument('testbed_ip', help='IP addresses of BESS nodes of testbeds',
                        nargs='+')
    parser.add_argument('cloudlab_username', help='Username for logging into Clouldab machines')
    parser.add_argument('cloudlab_private_key', help='Path to private key to copy to BESS node so it can SSH into the other nodes')
    args = parser.parse_args()
    return args

def main(testbed_ip, cloudlab_username, cloudlab_private_key):
    for ip in testbed_ip:
        # copy private key over to bess node
        proc = subprocess.run('scp {} {}@{}:~/.ssh/{}_cloudlab.pem'.format(
            cloudlab_private_key,
            cloudlab_username,
            ip,
            cloudlab_username),
                              shell=True)
        assert(proc.returncode == 0)

        # run testbed setup code to create host.pkl file
        proc = subprocess.run(
            'ssh {}@{} python3.6 /opt/cctestbed/setup_cloudlab.py'.format(
                cloudlab_username, ip), shell=True)
        assert(proc.returncode == 0)

        # copy host pkl file over here
        proc = subprocess.run(
            'scp {}@{}:/opt/cctestbed/host_info.pkl /tmp/host_info_{}.pkl'.format(
                cloudlab_username, ip, ip), shell=True)
        assert(proc.returncode == 0)

        
if __name__ == '__main__':
    args = parse_args()
    main(args.testbed_ip, args.cloudlab_username, args.cloudlab_private_key)
