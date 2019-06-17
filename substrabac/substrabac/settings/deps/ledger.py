
import os
import base64
import asyncio
import glob
import json
import tempfile

from .org import ORG

from hfc.fabric import Client
from hfc.fabric.peer import Peer
from hfc.fabric.user import create_user
from hfc.fabric.orderer import Orderer
from hfc.util.keyvaluestore import FileKeyValueStore
from hfc.fabric.block_decoder import decode_fabric_MSP_config, decode_fabric_peers_info, decode_fabric_endpoints


LEDGER_CONFIG_FILE = os.environ.get('LEDGER_CONFIG_FILE', f'/substra/conf/{ORG}/substrabac/conf.json')
LEDGER = json.load(open(LEDGER_CONFIG_FILE, 'r'))

LEDGER_SYNC_ENABLED = True

PEER_PORT = LEDGER['peer']['port'][os.environ.get('SUBSTRABAC_PEER_PORT', 'external')]

LEDGER['requestor'] = create_user(
    name=LEDGER['client']['name'],
    org=LEDGER['client']['org'],
    state_store=FileKeyValueStore(LEDGER['client']['state_store']),
    msp_id=LEDGER['client']['msp_id'],
    key_path=glob.glob(LEDGER['client']['key_path'])[0],
    cert_path=LEDGER['client']['cert_path']
)


def get_hfc_client():

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    client = Client()
    client.new_channel(LEDGER['channel_name'])

    # Add peer from substrabac ledger config file
    peer = Peer(name=LEDGER['peer']['name'])
    peer.init_with_bundle({
        'url': f'{LEDGER["peer"]["host"]}:{PEER_PORT}',
        'grpcOptions': LEDGER['peer']['grpcOptions'],
        'tlsCACerts': {'path': LEDGER['peer']['tlsCACerts']},
        'clientKey': {'path': LEDGER['peer']['clientKey']},
        'clientCert': {'path': LEDGER['peer']['clientCert']},
    })
    client._peers[LEDGER['peer']['name']] = peer

    # Discover orderers and peers from channel discovery
    channel = client.get_channel(LEDGER['channel_name'])
    results = loop.run_until_complete(
        channel._discovery(
            LEDGER['requestor'],
            peer,
            config=True,
            local=False
        )
    )
    results = deserialize_discovery(results)

    update_client_with_discovery(client, results)

    return loop, client


LEDGER['hfc'] = get_hfc_client


def update_client_with_discovery(client, discovery_results):

    # Get all msp tls root cert files
    tls_root_certs = {}
    for mspid, msp_info in discovery_results['config']['msps'].items():
        tls_root_certs[mspid] = base64.decodebytes(
            msp_info['tls_root_certs'].pop().encode()
        )

    # Load one peer per msp for endorsing transaction
    for msp in discovery_results['members']:
        peer_info = msp[0]
        if peer_info['mspid'] != LEDGER['client']['msp_id']:
            peer = Peer(name=peer_info['mspid'])

            with tempfile.NamedTemporaryFile() as tls_root_cert:
                tls_root_cert.write(tls_root_certs[peer_info['mspid']])
                tls_root_cert.flush()

                peer.init_with_bundle({
                    'url': peer_info['endpoint'],
                    'grpcOptions': {
                        'grpc-max-send-message-length': 15,
                        'grpc.ssl_target_name_override': peer_info['endpoint'].split(':')[0]
                    },
                    'tlsCACerts': {'path': tls_root_cert.name},
                    'clientKey': {'path': LEDGER['peer']['clientKey']},  # use peer creds (mutual tls)
                    'clientCert': {'path': LEDGER['peer']['clientCert']},  # use peer creds (mutual tls)
                })

            client._peers[peer_info['mspid']] = peer

    # Load one orderer for broadcasting transaction
    orderer_mspid, orderer_info = list(discovery_results['config']['orderers'].items())[0]

    orderer = Orderer(name=orderer_mspid)

    with tempfile.NamedTemporaryFile() as tls_root_cert:
        tls_root_cert.write(tls_root_certs[orderer_mspid])
        tls_root_cert.flush()

        # Need loop
        orderer.init_with_bundle({
            'url': f"{orderer_info[0]['host']}:{orderer_info[0]['port']}",
            'grpcOptions': {
                'grpc-max-send-message-length': 15,
                'grpc.ssl_target_name_override': orderer_info[0]['host']
            },
            'tlsCACerts': {'path': tls_root_cert.name},
            'clientKey': {'path': LEDGER['peer']['clientKey']},  # use peer creds (mutual tls)
            'clientCert': {'path': LEDGER['peer']['clientCert']},  # use peer creds (mutual tls)
        })

    client._orderers[orderer_mspid] = orderer


def deserialize_discovery(response):
    results = {
        'config': None,
        'members': []
    }

    for res in response.results:
        if res.config_result:
            results['config'] = deserialize_config(res.config_result)

        if res.members:
            results['members'].extend(deserialize_members(res.members))

    return results


def deserialize_config(config_result):

    results = {'msps': {},
               'orderers': {}}

    for mspid in config_result.msps:
        results['msps'][mspid] = decode_fabric_MSP_config(
            config_result.msps[mspid].SerializeToString()
        )

    for mspid in config_result.orderers:
        results['orderers'][mspid] = decode_fabric_endpoints(
            config_result.orderers[mspid].endpoint
        )

    return results


def deserialize_members(members):
    peers = []

    for mspid in members.peers_by_org:
        peer = decode_fabric_peers_info(
            members.peers_by_org[mspid].peers
        )
        peers.append(peer)

    return peers