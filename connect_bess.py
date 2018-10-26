from cctestbedv2 import connect_dpdk
from config import HOST_CLIENT, HOST_SERVER

def main():
    server = HOST_SERVER     
    client = HOST_CLIENT
    connect_dpdk(server, client)
    
if __name__ == '__main__':
    main()
