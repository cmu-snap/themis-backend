import subprocess
import xml.etree.ElementTree as ET

geni_namespace = {'geni':'http://www.geni.net/resources/rspec/3'}

cloudlab_manifest = subprocess.run(['geni-get','manifest'], stdout=subprocess.PIPE).stdout
root = ET.fromstring(cloudlab_manifest)
nodes=root.findall('geni:node', geni_namespace)[0]
