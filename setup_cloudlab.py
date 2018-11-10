import subprocess
import os
import xml.etree.ElementTree as ET

geni_namespace = {'geni':'http://www.geni.net/resources/rspec/3'}
cloudlab_manifest = subprocess.run(['geni-get','manifest'], stdout=subprocess.PIPE).stdout
root = ET.fromstring(cloudlab_manifest)
server_ip_wan=root.find('.geni:node[@client_id="server"]/geni:host',geni_namespace).attrib['ipv4']
client_ip_wan=root.find('.geni:node[@client_id="client"]/geni:host',geni_namespace).attrib['ipv4']
bess_ip_wan=root.find('.geni:node[@client_id="bess"]/geni:host',geni_namespace).attrib['ipv4']

USER = os.environ['USER']
IDENTITY_FILE = '/users/{}/.ssh/{}_cloudlab.pem'.format(USER, USER)
ssh_config = ('Host cctestbed-server \n'
              '    HostName {} \n'
              '    User {} \n'
              '    IdentityFile {} \n'
              'Host cctestbed-client \n'
              '    HostName {} \n'
              '    User {} \n'
              '    IdentityFile {} \n'
              ).format(server_ip_wan, USER, IDENTITY_FILE,
                       client_ip_wan, USER, IDENTITY_FILE)

              
# create config file
with open('/users/{}/.ssh/config'.format(os.environ['USER']), 'w') as f:
    f.write(ssh_config)
    
