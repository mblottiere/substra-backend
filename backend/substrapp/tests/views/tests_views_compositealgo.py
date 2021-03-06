import copy
import os
import shutil
import logging
import json

import mock

from django.urls import reverse
from django.test import override_settings

from rest_framework import status
from rest_framework.test import APITestCase


from substrapp.serializers import LedgerCompositeAlgoSerializer

from substrapp.ledger.exceptions import LedgerError

from ..common import get_sample_composite_algo, AuthenticatedClient, encode_filter
from ..assets import objective, datamanager, compositealgo, algo, model

MEDIA_ROOT = "/tmp/unittests_views/"


# APITestCase
@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class CompositeAlgoViewTests(APITestCase):
    client_class = AuthenticatedClient

    def setUp(self):
        if not os.path.exists(MEDIA_ROOT):
            os.makedirs(MEDIA_ROOT)

        self.compositealgo, self.algo_filename = get_sample_composite_algo()

        self.extra = {
            'HTTP_SUBSTRA_CHANNEL_NAME': 'mychannel',
            'HTTP_ACCEPT': 'application/json;version=0.0'
        }
        self.logger = logging.getLogger('django.request')
        self.previous_level = self.logger.getEffectiveLevel()
        self.logger.setLevel(logging.ERROR)

    def tearDown(self):
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

        self.logger.setLevel(self.previous_level)

    def test_composite_algo_list_empty(self):
        url = reverse('substrapp:composite_algo-list')
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger:
            mquery_ledger.return_value = []

            response = self.client.get(url, **self.extra)
            r = response.json()
            self.assertEqual(r, [])

    def test_composite_algo_list_success(self):
        url = reverse('substrapp:composite_algo-list')
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger:
            mquery_ledger.return_value = compositealgo

            response = self.client.get(url, **self.extra)
            r = response.json()
            self.assertEqual(r, compositealgo)

    def test_composite_algo_list_filter_fail(self):
        url = reverse('substrapp:composite_algo-list')
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger:
            mquery_ledger.return_value = compositealgo

            search_params = '?search=algERRORo'
            response = self.client.get(url + search_params, **self.extra)
            r = response.json()

            self.assertIn('Malformed search filters', r['message'])

    def test_composite_algo_list_filter_name(self):
        url = reverse('substrapp:composite_algo-list')
        name_to_filter = encode_filter(compositealgo[0]['name'])

        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger:
            mquery_ledger.return_value = compositealgo

            search_params = f'?search=composite_algo%253Aname%253A{name_to_filter}'
            response = self.client.get(url + search_params, **self.extra)
            r = response.json()

            self.assertEqual(len(r), 1)

    def test_composite_algo_list_filter_dual(self):
        url = reverse('substrapp:composite_algo-list')
        name_to_filter = encode_filter(compositealgo[0]['name'])
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger:
            mquery_ledger.return_value = compositealgo

            search_params = f'?search=composite_algo%253Aname%253A{name_to_filter}'
            search_params += f'%2Ccomposite_algo%253Aowner%253A{encode_filter(compositealgo[0]["owner"])}'
            response = self.client.get(url + search_params, **self.extra)
            r = response.json()

            self.assertEqual(len(r), 1)

    def test_composite_algo_list_filter_algo(self):
        url = reverse('substrapp:composite_algo-list')
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger:
            mquery_ledger.return_value = compositealgo

            search_params = f'?search=algo%253Akey%253A{algo[0]["key"]}'
            response = self.client.get(url + search_params, **self.extra)
            r = response.json()

            self.assertEqual(len(r), 0)

    def test_composite_algo_list_filter_datamanager_fail(self):
        url = reverse('substrapp:composite_algo-list')
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger, \
                mock.patch('substrapp.views.filters_utils.query_ledger') as mquery_ledger2:
            mquery_ledger.return_value = compositealgo
            mquery_ledger2.return_value = datamanager

            search_params = '?search=dataset%253Aname%253ASimplified%2520ISIC%25202018'
            response = self.client.get(url + search_params, **self.extra)
            r = response.json()

            self.assertIn('Malformed search filters', r['message'])

    def test_composite_algo_list_filter_objective_fail(self):
        url = reverse('substrapp:composite_algo-list')
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger, \
                mock.patch('substrapp.views.filters_utils.query_ledger') as mquery_ledger2:
            mquery_ledger.return_value = compositealgo
            mquery_ledger2.return_value = objective

            search_params = '?search=objective%253Aname%253ASkin%2520Lesion%2520Classification%2520Objective'
            response = self.client.get(url + search_params, **self.extra)
            r = response.json()

            self.assertIn('Malformed search filters', r['message'])

    def test_composite_algo_list_filter_model(self):
        url = reverse('substrapp:composite_algo-list')
        done_model = [
            m for m in model if 'composite_traintuple' in m and m['composite_traintuple']['status'] == 'done'
        ][0]

        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger, \
                mock.patch('substrapp.views.filters_utils.query_ledger') as mquery_ledger2:
            mquery_ledger.return_value = compositealgo
            mquery_ledger2.return_value = model

            key = done_model['composite_traintuple']['out_trunk_model']['out_model']['key']
            search_params = f'?search=model%253Akey%253A{key}'
            response = self.client.get(url + search_params, **self.extra)
            r = response.json()

            self.assertEqual(len(r), 1)

    def test_composite_algo_retrieve(self):
        dir_path = os.path.dirname(os.path.realpath(__file__))
        url = reverse('substrapp:composite_algo-list')
        composite_algo_response = copy.deepcopy(compositealgo[0])
        with mock.patch('substrapp.views.compositealgo.get_object_from_ledger') as mget_object_from_ledger, \
                mock.patch('substrapp.views.compositealgo.get_remote_asset') as get_remote_asset:

            with open(os.path.join(dir_path,
                                   '../../../../fixtures/chunantes/algos/algo4/description.md'), 'rb') as f:
                content = f.read()
            mget_object_from_ledger.return_value = composite_algo_response
            get_remote_asset.return_value = content

            response = self.client.get(f'{url}{compositealgo[0]["key"]}/', **self.extra)
            r = response.json()

            self.assertEqual(r, composite_algo_response)

    def test_composite_algo_retrieve_fail(self):

        url = reverse('substrapp:composite_algo-list')

        # Key < 32 chars
        search_params = '12312323/'
        response = self.client.get(url + search_params, **self.extra)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Key not hexa
        search_params = 'X' * 32 + '/'
        response = self.client.get(url + search_params, **self.extra)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        with mock.patch('substrapp.views.compositealgo.get_object_from_ledger') as mget_object_from_ledger:
            mget_object_from_ledger.side_effect = LedgerError('TEST')
            response = self.client.get(f'{url}{objective[0]["key"]}/', **self.extra)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_composite_algo_create(self):
        url = reverse('substrapp:composite_algo-list')

        dir_path = os.path.dirname(os.path.realpath(__file__))

        composite_algo_path = os.path.join(dir_path, '../../../../fixtures/chunantes/algos/algo3/algo.tar.gz')
        description_path = os.path.join(dir_path, '../../../../fixtures/chunantes/algos/algo3/description.md')

        data = {
            'json': json.dumps({
                'name': 'Composite Algo',
                'objective_key': objective[0]['key'],
                'permissions': {
                    'public': True,
                    'authorized_ids': [],
                },
            }),
            'file': open(composite_algo_path, 'rb'),
            'description': open(description_path, 'rb'),
        }

        with mock.patch.object(LedgerCompositeAlgoSerializer, 'create') as mcreate:

            mcreate.return_value = {}

            response = self.client.post(url, data=data, format='multipart', **self.extra)

        self.assertIsNotNone(response.data['key'])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data['description'].close()
        data['file'].close()

    def test_composite_algo_list_storage_addresses_update(self):
        url = reverse('substrapp:composite_algo-list')
        with mock.patch('substrapp.views.compositealgo.query_ledger') as mquery_ledger, \
                mock.patch('substrapp.views.objective.get_remote_asset') as mget_remote_asset:

            # mock content
            mget_remote_asset.return_value = b'dummy binary content'
            ledger_composite_algos = copy.deepcopy(compositealgo)
            for ledger_composite_algo in ledger_composite_algos:
                for field in ('description', 'content'):
                    ledger_composite_algo[field]['storage_address'] = \
                        ledger_composite_algo[field]['storage_address'].replace('http://testserver',
                                                                                'http://remotetestserver')
            mquery_ledger.return_value = ledger_composite_algos

            # actual test
            res = self.client.get(url, **self.extra)
            res_composite_algos = res.data
            self.assertEqual(len(res_composite_algos), len(compositealgo))
            for i, res_composite_algo in enumerate(res_composite_algos):
                for field in ('description', 'content'):
                    self.assertEqual(res_composite_algo[field]['storage_address'],
                                     compositealgo[i][field]['storage_address'])

    def test_composite_algo_retrieve_storage_addresses_update_with_cache(self):
        url = reverse('substrapp:composite_algo-detail', args=[compositealgo[0]['key']])
        with mock.patch('substrapp.views.compositealgo.get_object_from_ledger') as mquery_ledger, \
                mock.patch('substrapp.views.compositealgo.node_has_process_permission',
                           return_value=True), \
                mock.patch('substrapp.views.compositealgo.get_remote_asset') as mget_remote_asset:

            # mock content
            mget_remote_asset.return_value = b'dummy binary content'
            ledger_composite_algo = copy.deepcopy(compositealgo[0])
            for field in ('description', 'content'):
                ledger_composite_algo[field]['storage_address'] = \
                    ledger_composite_algo[field]['storage_address'].replace('http://testserver',
                                                                            'http://remotetestserver')
            mquery_ledger.return_value = ledger_composite_algo

            # actual test
            res = self.client.get(url, **self.extra)
            for field in ('description', 'content'):
                self.assertEqual(res.data[field]['storage_address'],
                                 compositealgo[0][field]['storage_address'])

    def test_composite_algo_retrieve_storage_addresses_update_without_cache(self):
        url = reverse('substrapp:composite_algo-detail', args=[compositealgo[0]['key']])
        with mock.patch('substrapp.views.compositealgo.get_object_from_ledger') as mquery_ledger, \
                mock.patch('substrapp.views.compositealgo.node_has_process_permission',
                           return_value=False), \
                mock.patch('substrapp.views.compositealgo.get_remote_asset') as mget_remote_asset:

            # mock content
            mget_remote_asset.return_value = b'dummy binary content'
            ledger_composite_algo = copy.deepcopy(compositealgo[0])
            for field in ('description', 'content'):
                ledger_composite_algo[field]['storage_address'] = \
                    ledger_composite_algo[field]['storage_address'].replace('http://testserver',
                                                                            'http://remotetestserver')
            mquery_ledger.return_value = ledger_composite_algo

            # actual test
            res = self.client.get(url, **self.extra)
            for field in ('description', 'content'):
                self.assertEqual(res.data[field]['storage_address'],
                                 compositealgo[0][field]['storage_address'])
