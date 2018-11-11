import pickle

with open('/opt/cctestbed/host_info.pkl','rb') as f:  # Python 3: open(..., 'rb')
    HOST_SERVER, HOST_CLIENT = pickle.load(f)

HOST_CLIENT_TEMPLATE = HOST_SERVER._asdict()
HOST_CLIENT_TEMPLATE['ip_wan'] = None
