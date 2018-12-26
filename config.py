import pickle

with open('/opt/cctestbed/host_info.pkl','rb') as f:  # Python 3: open(..., 'rb')
    HOST_SERVER, HOST_CLIENT = pickle.load(f)

HOST_CLIENT_TEMPLATE = HOST_CLIENT._asdict()
HOST_CLIENT_TEMPLATE['ip_wan'] = None

HOST_AWS_TEMPLATE = HOST_CLIENT_TEMPLATE.copy()
HOST_AWS_TEMPLATE['ifname_remote'] = 'eth0'
HOST_AWS_TEMPLATE['ip_lan'] = None
HOST_AWS_TEMPLATE['ip_wan'] = None
HOST_AWS_TEMPLATE['key_filename'] = None
HOST_AWS_TEMPLATE['username'] = 'ubuntu'
