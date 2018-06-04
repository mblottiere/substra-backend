'''
Get data generated by substra-network
'''

import os
from subprocess import call
from substrapp.conf import conf

from yaml import load, dump

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

SUBSTRA_NETWORK_PATH = os.environ.get('SUBSTRA_NETWORK_PATH', '../../substra-network/')
ORGS = ('owkin', 'chu-nantes')
current_user = os.environ.get('USER', 'toto')


def create_core_peer_config():
    for org_name in conf['orgs'].keys():
        org = conf['orgs'][org_name]
        for peer in org['peers']:
            stream = open('./core.yaml', 'r')
            yaml_data = load(stream, Loader=Loader)

            # override template here

            yaml_data['peer']['id'] = peer['host']
            yaml_data['peer']['address'] = '%(host)s:%(port)s' % {'host': peer['host'], 'port': peer['external_port']}
            yaml_data['peer']['localMspId'] = org['org_msp_id']
            yaml_data['peer']['mspConfigPath'] = '../user/msp'

            # yaml_data['peer']['tls']['cert']['file'] = '../tls/' + peer['name'] + '/cli-client.crt'
            # yaml_data['peer']['tls']['key']['file'] = '../tls/' + peer['name'] + '/cli-client.key'
            yaml_data['peer']['tls']['clientCert']['file'] = '../tls/' + peer['name'] + '/cli-client.crt'
            yaml_data['peer']['tls']['clientKey']['file'] = '../tls/' + peer['name'] + '/cli-client.key'
            yaml_data['peer']['tls']['enabled'] = 'true'
            yaml_data['peer']['tls']['rootcert']['file'] = '../ca-cert.pem'
            yaml_data['peer']['tls']['clientAuthRequired'] = 'true'
            yaml_data['peer']['tls']['clientRootCAs'] = ['../ca-cert.pem']


            yaml_data['logging']['level'] = 'debug'

            filename = './substrapp/conf/%(org_name)s/%(peer_name)s/core.yaml' % {'org_name': org_name,
                                                                                  'peer_name': peer['name']}
            with open(filename, 'w+') as f:
                f.write(dump(yaml_data, default_flow_style=False))


def get_conf_from_network():
    for org in ORGS:
        # copy msp
        call('sudo cp -R ' + os.path.join(SUBSTRA_NETWORK_PATH, 'data/orgs/' + org + '/user') +
             ' ./substrapp/conf/' + org, shell=True)

        # copy ca-cert.pem
        call('sudo cp ' + os.path.join(SUBSTRA_NETWORK_PATH, 'data/orgs/' + org + '/ca-cert.pem') +
             ' ./substrapp/conf/' + org, shell=True)

        # copy tls cli-client
        call('sudo cp -R ' + os.path.join(SUBSTRA_NETWORK_PATH, 'data/orgs/' + org + '/tls') +
             ' ./substrapp/conf/' + org, shell=True)

        # modify rights
        call('sudo chown -R ' + current_user + ':' + current_user + ' ./substrapp/conf/' + org, shell=True)


if __name__ == "__main__":
    get_conf_from_network()
    create_core_peer_config()