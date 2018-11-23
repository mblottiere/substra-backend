import os
import shutil
import tempfile

import mock
import time

from django.test import override_settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.test import APITestCase

from substrapp.utils import compute_hash, get_computed_hash, get_remote_file, untar_algo, get_hash, create_directory
from substrapp.job_utils import RessourceManager, monitoring_job, compute_docker
from substrapp.tasks import build_traintuple_folders, get_algo, get_model, get_challenge, put_opener, put_model, put_algo, put_metric, put_data

from .common import get_sample_challenge, get_sample_dataset, get_sample_data, get_sample_script

import tarfile
from threading import Thread
from .tests_misc import Stats
import docker
MEDIA_ROOT = tempfile.mkdtemp()


# APITestCase
@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TasksTests(APITestCase):

    def setUp(self):
        if not os.path.exists(MEDIA_ROOT):
            os.makedirs(MEDIA_ROOT)

        self.challenge_description, self.challenge_description_filename, \
            self.challenge_metrics, self.challenge_metrics_filename = get_sample_challenge()
        self.script, self.script_filename = get_sample_script()
        self.data_file, self.data_file_filename = get_sample_data()
        self.data_description, self.data_description_filename, self.data_data_opener, self.data_opener_filename = get_sample_dataset()

        self.RessourceManager = RessourceManager()

    def tearDown(self):
        try:
            shutil.rmtree(MEDIA_ROOT)
        except FileNotFoundError:
            pass

    def test_create_directory(self):
        directory = './test/'
        create_directory(directory)
        self.assertTrue(os.path.exists(directory))
        shutil.rmtree(directory)

    def test_get_computed_hash(self):
        with mock.patch('substrapp.utils.requests.get') as mocked_function:
            mocked_function.return_value = HttpResponse(str(self.script.read()))
            _, pkhash = get_computed_hash('test')
            self.assertEqual(pkhash, 'da920c804c4724f1ce7bd0484edcf4aafa209d5bd54e2e89972c087a487cbe02')

        with mock.patch('substrapp.utils.requests.get') as mocked_function:
            response = HttpResponse()
            response.status_code = status.HTTP_400_BAD_REQUEST
            mocked_function.return_value = response
            self.assertRaises(Exception, get_computed_hash, ('test', ))

    def test_get_remote_file(self):
        obj = {'storageAddress': 'test',
               'hash': 'da920c804c4724f1ce7bd0484edcf4aafa209d5bd54e2e89972c087a487cbe02'}

        with mock.patch('substrapp.utils.get_computed_hash') as mocked_function:
            content = str(self.script.read())
            pkhash = compute_hash(content)
            mocked_function.return_value = content, pkhash
            content_remote, pkhash_remote = get_remote_file(obj)
            self.assertEqual(pkhash_remote, 'da920c804c4724f1ce7bd0484edcf4aafa209d5bd54e2e89972c087a487cbe02')
            self.assertEqual(content_remote, content)

        with mock.patch('substrapp.utils.get_computed_hash') as mocked_function:
            content = str(self.script.read()) + ' FAIL'
            pkhash = compute_hash(content)
            mocked_function.return_value = content, pkhash
            self.assertRaises(Exception, get_remote_file, (obj, ))

    def test_Ressource_Manager(self):

        self.assertIn('M', self.RessourceManager.memory_limit_mb())

        cpu_set = self.RessourceManager.acquire_cpu_set()
        self.assertIn(cpu_set, self.RessourceManager._RessourceManager__used_cpu_sets)
        self.RessourceManager.return_cpu_set(cpu_set)
        self.assertNotIn(cpu_set, self.RessourceManager._RessourceManager__used_cpu_sets)

        gpu_set = self.RessourceManager.acquire_gpu_set()
        if gpu_set != 'no_gpu':
            self.assertIn(gpu_set, self.RessourceManager._RessourceManager__used_gpu_sets)
        self.RessourceManager.return_gpu_set(gpu_set)
        self.assertNotIn(gpu_set, self.RessourceManager._RessourceManager__used_gpu_sets)

    def test_monitoring_job(self):

        class FakeContainer(object):
            """docstring for FakeContainer"""
            def __init__(self):
                self.c_stats = Stats.get_stats()

            def stats(self, decode, stream):
                return self.c_stats

        class FakeClient(object):
            """docstring for FakeClient"""
            def __init__(self):
                self.containers = {'job': FakeContainer()}

        monitoring = Thread(target=monitoring_job, args=(FakeClient(), {'name': 'job'}))
        monitoring.start()
        time.sleep(0.1)
        monitoring.do_run = False
        monitoring.join()

        self.assertNotEqual(monitoring._stats['memory']['max'], 0)
        self.assertNotEqual(monitoring._stats['cpu']['max'], 0)
        self.assertNotEqual(monitoring._stats['netio']['rx'], 0)

    def test_put_algo(self):

        file = open(os.path.join(MEDIA_ROOT, 'sample_metrics.py'), 'w')
        file.write('Hello World')
        file.close()
        self.assertTrue(os.path.exists(os.path.join(MEDIA_ROOT, 'sample_metrics.py')))

        tf = tarfile.open(os.path.join(MEDIA_ROOT, 'sample.tar.gz'), mode='w:gz')
        tf.add(os.path.join(MEDIA_ROOT, 'sample_metrics.py'), arcname='sample_metrics.py')
        tf.close()
        self.assertTrue(os.path.exists(os.path.join(MEDIA_ROOT, 'sample.tar.gz')))

        with mock.patch('substrapp.tasks.get_hash') as mocked_function:
            with open(os.path.join(MEDIA_ROOT, 'sample.tar.gz'), 'rb') as content:
                pkhash = get_hash(os.path.join(MEDIA_ROOT, 'sample.tar.gz'))
                mocked_function.return_value = pkhash
                put_algo({'key': 'testkey', 'algo': 'testalgo'}, os.path.join(MEDIA_ROOT, 'traintuple/testkey/'), content.read())

        metric_path = os.path.join(MEDIA_ROOT, 'traintuple/testkey/sample_metrics.py')
        self.assertTrue(os.path.exists(metric_path))

    def test_put_metric(self):

        filepath = os.path.join(MEDIA_ROOT, 'sample_metrics.py')

        class FakeMetrics(object):
            def __init__(self):
                self.path = filepath

        class FakeChallenge(object):
            def __init__(self):
                self.metrics = FakeMetrics()

        file = open(filepath, 'w')
        file.write('Hello World')
        file.close()
        self.assertTrue(os.path.exists(filepath))

        create_directory(os.path.join(MEDIA_ROOT, 'metrics/'))
        put_metric(MEDIA_ROOT, FakeChallenge())
        self.assertTrue(os.path.exists(os.path.join(MEDIA_ROOT, 'metrics/metrics.py')))

    def test_put_opener(self):

        filepath = os.path.join(MEDIA_ROOT, 'opener.py')

        class FakeOpener(object):
            def __init__(self):
                self.path = filepath

        class FakeDataset(object):
            def __init__(self):
                self.data_opener = FakeOpener()

        file = open(filepath, 'w')
        file.write('Hello World')
        file.close()
        self.assertTrue(os.path.exists(filepath))

        openerHash = get_hash(filepath)
        data_type = 'trainData'
        traintuple = {data_type: {'openerHash': openerHash}}

        create_directory(os.path.join(MEDIA_ROOT, 'opener'))
        with mock.patch('substrapp.models.Dataset.objects.get') as mocked_get_method:
            mocked_get_method.return_value = FakeDataset()
            with self.assertRaises(Exception):
                put_opener({data_type: {'openerHash': 'HASH'}}, MEDIA_ROOT, data_type)

            put_opener(traintuple, MEDIA_ROOT, data_type)

        self.assertTrue(os.path.exists(os.path.join(MEDIA_ROOT, 'opener/opener.py')))

    def test_put_data(self):
        pass

    def test_put_model(self):

        class FakePath(object):
            def __init__(self):
                self.path = os.path.join(MEDIA_ROOT, 'model/model2')

        class FakeModel(object):
            def __init__(self):
                self.file = FakePath()

        model_content = b'MODEL 1 2 3'
        model_hash = compute_hash(model_content)
        model_type = 'startModel'
        traintuple = {model_type: {'hash': model_hash}}
        create_directory(os.path.join(MEDIA_ROOT, 'model/'))
        put_model(traintuple, MEDIA_ROOT, model_content, model_type)

        self.assertTrue(os.path.exists(os.path.join(MEDIA_ROOT, 'model/model')))
        os.rename(os.path.join(MEDIA_ROOT, 'model/model'), os.path.join(MEDIA_ROOT, 'model/model2'))
        with mock.patch('substrapp.models.Model.objects.get') as mocked_get_method:
            mocked_get_method.return_value = FakeModel()
            put_model(traintuple, MEDIA_ROOT, model_content, model_type)

        self.assertTrue(os.path.exists(os.path.join(MEDIA_ROOT, 'model/model')))

        with mock.patch('substrapp.models.Model.objects.get') as mocked_get_method:
            mocked_get_method.return_value = FakeModel()
            with self.assertRaises(Exception):
                put_model({'startModel': {'hash': 'hash'}}, MEDIA_ROOT, model_content, model_type)

    def test_get_model(self):
        model_content = b'MODEL 1 2 3'
        model_hash = compute_hash(model_content)
        model_type = 'startModel'
        traintuple = {model_type: {'hash': model_hash}}
        with mock.patch('substrapp.tasks.get_remote_file') as mocked_get_function:
            mocked_get_function.return_value = model_content, model_hash
            model_content, model_hash = get_model(traintuple, model_type)

        self.assertIsNotNone(model_content)
        self.assertIsNotNone(model_hash)

    def test_get_algo(self):
        algo_content, algo_hash = 'content', 'hash'
        traintuple = {'algo': 'myalgo'}
        with mock.patch('substrapp.tasks.get_remote_file') as mocked_get_function:
            mocked_get_function.return_value = algo_content, algo_hash
            self.assertEqual((algo_content, algo_hash), get_algo(traintuple))

    def test_get_challenge(self):
        pass

    def test_compute_docker(self):
        cpu_set, gpu_set = None, None
        client = docker.from_env()

        dockerfile_path = os.path.join(MEDIA_ROOT, 'Dockerfile')
        file = open(dockerfile_path, 'w')
        file.write('FROM library/hello-world')
        file.close()
        result = compute_docker(client, self.RessourceManager,
                                MEDIA_ROOT, 'test_compute_docker',
                                'test_compute_docker_name', None, None, cpu_set, gpu_set)
        self.RessourceManager.return_cpu_set(cpu_set)
        self.RessourceManager.return_gpu_set(gpu_set)
        self.assertIn('CPU', result)
        self.assertIn('GPU', result)
        self.assertIn('Mem', result)
        self.assertIn('GPU Mem', result)

    def test_build_traintuple_folders(self):
        with mock.patch('substrapp.tasks.getattr') as mocked_function:
            mocked_function.return_value = MEDIA_ROOT
            key = 'test1234'
            traintuple_directory = build_traintuple_folders({'key': key})
            self.assertTrue(os.path.exists(traintuple_directory))
            self.assertEqual(os.path.join(MEDIA_ROOT, 'traintuple/%s' % key), traintuple_directory)

            for root, dirs, files in os.walk(traintuple_directory):
                nb_subfolders = len(dirs)

            self.assertTrue(5, nb_subfolders)
