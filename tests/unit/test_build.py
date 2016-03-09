# Copyright 2016 Kuo-tung Kao
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
from oslo_config import cfg
from requests import exceptions as requests_exp
import testtools

from kolla.cmd import build
from kolla.common.config import _BASE_OPTS
from kolla.common.config import _CLI_OPTS
from kolla.common.config import _PROFILE_OPTS


class TestKollaWorker(testtools.TestCase):
    def setUp(self):
        super(TestKollaWorker, self).setUp()
        self.conf = cfg.CONF

        self.conf.register_opts(_CLI_OPTS)
        self.conf.register_opts(_BASE_OPTS)
        self.conf.register_opts(_PROFILE_OPTS)

        self.kolla = build.KollaWorker(self.conf)

    @mock.patch('kolla.cmd.build.KollaWorker.copy_apt_files')
    @mock.patch('datetime.datetime')
    def test_setup_working_dir(self, datetime_mock, copy_apt_files):
        prefix = 'kolla-'
        ts = '2015-10-19_22-22-22_'

        def create_copytree():
            def copytree(src, dst):
                self.assertIn(prefix + ts, dst)

            return copytree

        with mock.patch('shutil.copytree', new_callable=create_copytree):
            local_time_mock = mock.MagicMock()
            local_time_mock.strftime.return_value = ts
            datetime_mock.fromtimestamp.return_value = local_time_mock
            self.kolla.setup_working_dir()

    @mock.patch('shutil.rmtree')
    def test_cleanup(self, rmtree):
        self.kolla.temp_dir = mock.MagicMock()
        self.kolla.cleanup()
        rmtree.assert_called_once_with(self.kolla.temp_dir)

    def test_fileter_images(self):
        self.iamges = []
        self.regex = []

    def test_build_image_list(self):
        self.kolla.docker_build_paths = ['glance-api', 'glance-base', 'base']
        expepcted_value = [
            {'name': 'glance-api', 'path': 'glance-api',
             'fullname': 'kollaglue/centos-binary-glance-api:2.0.0',
             'parent_name': 'kollaglue/centos-binary-glance-base:2.0.0'},
            {'name': 'glance-base', 'path': 'glance-base',
             'fullname': 'kollaglue/centos-binary-glance-base:2.0.0',
             'parent_name': 'kollaglue/centos-binary-openstack-base:2.0.0'},
            {'name': 'base', 'path': 'base',
             'fullname': 'kollaglue/centos-binary-base:2.0.0',
             'parent_name': 'centos:latest', 'parent': None}
        ]
        self.kolla.base = 'centos'
        self.kolla.install_type = 'binary'
        self.kolla.namespace = 'kollaglue'
        self.kolla.image_prefix = (self.kolla.base + '-' +
                                   self.kolla.install_type + '-')

        content_map = {
            'glance-api/Dockerfile': 'FROM kollaglue/centos-binary'
                                     '-glance-base:2.0.0\n\n',
            'glance-base/Dockerfile': 'FROM kollaglue/centos-binary'
                                      '-openstack-base:2.0.0\n\n',
            'base/Dockerfile': 'FROM centos:latest\n\n',
        }

        def mock_open(content_map):
            open_mock = mock.MagicMock()

            def custom_open(name, mode='r'):
                file_mock = mock.MagicMock()
                file_mock.__enter__.return_value = file_mock

                def custom_read():
                    return content_map[name]

                file_mock.read.side_effect = custom_read

                return file_mock

            open_mock.side_effect = custom_open
            return open_mock

        with mock.patch('kolla.cmd.build.open', mock_open(content_map)):
            self.kolla.build_image_list()

        for index, image in enumerate(self.kolla.images):
            self.assertEqual('unprocessed', image['status'])
            self.assertEqual([], image['children'])
            for key in expepcted_value[index]:
                self.assertEqual(expepcted_value[index][key], image[key])

    def test_find_parents(self):

        base_image = {
            'fullname': 'kollaglue/centos-binary-base:latest',
            'parent_name': 'centos',
            'children': [],
            'parent': None,
        }
        openstack_base_image = {
            'fullname': 'kollaglue/centos-binary-openstack-base:latest',
            'parent_name': 'kollaglue/centos-binary-base:latest',
            'children': [],
        }
        cinder_api_image = {
            'fullname': 'kollaglue/centos-binary-cinder-api:latest',
            'parent_name': 'kollaglue/centos-binary-openstack-base:latest',
            'children': [],
        }
        images = [base_image, openstack_base_image, cinder_api_image]

        exepected_base_image = base_image.copy()
        exepected_base_image.update({
            'children': [openstack_base_image],
            'parent': None,
        })
        exepected_openstack_base_image = openstack_base_image.copy()
        exepected_openstack_base_image.update({
            'children': [cinder_api_image],
            'parent': base_image,
        })
        exepected_cinder_api_image = cinder_api_image.copy()
        exepected_cinder_api_image.update({
            'children': [],
            'parent': openstack_base_image,
        })

        expected_images = [exepected_base_image,
                           exepected_openstack_base_image,
                           exepected_cinder_api_image]

        self.kolla.images = images

        self.kolla.find_parents()

        self.assertEqual(expected_images, self.kolla.images)

    @mock.patch('kolla.cmd.build.KollaWorker.build_image_list')
    @mock.patch('kolla.cmd.build.KollaWorker.find_parents')
    @mock.patch('kolla.cmd.build.KollaWorker.filter_images')
    def test_build_queue(self, *args):
        base_image = {
            'name': 'base',
            'fullname': 'kollaglue/centos-binary-base:latest',
            'parent_name': 'centos',
            'parent': None,
        }
        openstack_base_image = {
            'name': 'openstack-base',
            'fullname': 'kollaglue/centos-binary-openstack-base:latest',
            'parent_name': 'kollaglue/centos-binary-base:latest',
            'parent': base_image,
        }
        data_image = {
            'name': 'data',
            'fullname': 'kollaglue/centos-binary-data:latest',
            'parent_name': 'centos',
            'parent': None,
        }
        self.kolla.images = [base_image, openstack_base_image, data_image]
        queue = self.kolla.build_queue()

        for name in ['base', 'data']:
            self.assertEqual(name, queue.get().get('name'))

    @mock.patch('kolla.cmd.build.shutil.copyfile')
    def test_copy_apt_files(self, copyfile):
        self.kolla.conf.apt_sources_list = 'kolla_source'
        self.kolla.conf.apt_preferences = 'kolla_preference'
        self.kolla.working_dir = '/tmp'

        self.kolla.copy_apt_files()
        expected_result = [mock.call('kolla_source', '/tmp/base/sources.list'),
                           mock.call('kolla_preference',
                                     '/tmp/base/apt_preferences')]

        self.assertEqual(expected_result, copyfile.call_args_list)

    def test_bild_rpm_setup(self):
        rpm_setup_config = ['a.rpm', 'http://abc/main.repo', 'main.repo']
        rpm_setup = self.kolla.build_rpm_setup(rpm_setup_config)
        expected_result = [
            'RUN yum -y install a.rpm',
            'RUN curl http://abc/main.repo -o /etc/yum.repos.d/main.repo',
            'COPY main.repo /etc/yum.repos.d/'
        ]
        self.assertEqual(expected_result, rpm_setup)

    def test_bild_rpm_setup_failed(self):
        rpm_setup_config = ['a.c']
        self.assertRaises(build.KollaRpmSetupUnknownConfig,
                          self.kolla.build_rpm_setup,
                          rpm_setup_config)

    @mock.patch('kolla.cmd.build.os.utime')
    @mock.patch('kolla.cmd.build.os.walk')
    def test_set_time(self, os_walk, utime):
        os_walk.return_value = [
            ('/dir-a', ['d1a'], ['f1a', 'f1b']),
            ('/dir-b', ['d2a', 'd2b'], ['f2a']),
        ]
        self.kolla.working_dir = '/kolla'

        self.kolla.set_time()
        expected_result = [
            mock.call('/dir-a/f1a', (0, 0)),
            mock.call('/dir-a/f1b', (0, 0)),
            mock.call('/dir-a/d1a', (0, 0)),
            mock.call('/dir-b/f2a', (0, 0)),
            mock.call('/dir-b/d2a', (0, 0)),
            mock.call('/dir-b/d2b', (0, 0)),
        ]
        self.assertEqual(expected_result, utime.call_args_list)

    @mock.patch('kolla.cmd.build.jinja2')
    def test_create_dockerfiles(self, j2):
        def get_template(name):
            import jinja2
            env = jinja2.Environment()
            template = '''{{ base_distro }}:{{ base_distro_tag }}
{{ maintainer }}
{{ kolla_version }}
{{ include_header }}
{{ base_distro }}
{{ install_type }}
{{ install_metatype }}
{{ image_prefix }}
{{ install_type }}
{{ namespace }}
{{ tag }}
{{ kolla_version }}'''
            return env.from_string(template)

        env = mock.MagicMock()
        j2.Environment.return_value = env
        env.get_template = get_template
        self.kolla.docker_build_paths = [
            '/tmp/kolla/a',
            '/tmp/kolla/b',

        ]
        m = mock.MagicMock()
        with mock.patch('kolla.cmd.build.open', m):
            self.kolla.create_dockerfiles()

        expected_string = '''centos:latest
Kolla Project (https://launchpad.net/kolla)
2.0.0

centos
binary
rdo
centos-binary-
binary
kollaglue
2.0.0
2.0.0'''

        self.assertEqual([mock.call('/tmp/kolla/a/Dockerfile', 'w'),
                          mock.call('/tmp/kolla/b/Dockerfile', 'w')],
                         m.call_args_list)

        self.assertEqual([mock.call(expected_string),
                          mock.call(expected_string)],
                         m().__enter__.return_value.write.call_args_list)

        self.assertEqual([mock.call('/tmp/kolla/a'),
                          mock.call('/tmp/kolla/b')],
                         j2.FileSystemLoader.call_args_list)

    @mock.patch('kolla.cmd.build.os.walk')
    def test_find_dockerfiles(self, os_walk):
        os_walk.return_value = [
            ('/opt/a', ['d1'], ['f1', 'Dockerfile.j2']),
            ('/opt/b', ['d2', 'd3'], ['f2', 'Dockerfile.j2']),
            ('/opt/c', [], ['f2', 'f3']),
            ('/opt/d', [], []),
        ]

        self.kolla.working_dir = '/opt'
        self.kolla.find_dockerfiles()
        expected_result = [
            '/opt/a',
            '/opt/b',
        ]
        self.assertEqual(expected_result, self.kolla.docker_build_paths)


class TestFunction(testtools.TestCase):
    def setUp(self):
        super(TestFunction, self).setUp()
        self.conf = cfg.ConfigOpts()
        self.conf.register_opts(_BASE_OPTS)
        self.conf.register_opts(_CLI_OPTS)
        self.conf.register_opts(_PROFILE_OPTS)
        self.kolla = build.KollaWorker(self.conf)


class TestWorkerThread(testtools.TestCase):
    def setUp(self):
        super(TestWorkerThread, self).setUp()
        self.queue = mock.MagicMock()

        self.conf = cfg.CONF

        self.conf.register_opts(_CLI_OPTS)
        self.conf.register_opts(_BASE_OPTS)
        self.conf.register_opts(_PROFILE_OPTS)

    @mock.patch("kolla.cmd.build.docker")
    def test_end_task(self, docker):
        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)

        image = {
            'name': 'base',
            'children': [
                {'name': 'child1'},
                {'name': 'child2'},
                {'name': 'child3'}
            ],
        }
        worker_thread.end_task(image)
        queue.task_done.assert_called_once_with()
        self.assertEqual([mock.call(i) for i in image['children']],
                         queue.put.call_args_list)

    @mock.patch("kolla.cmd.build.docker")
    def test_builder_unmatched(self, docker):
        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        image = {'status': 'unmatched', 'name': 'base'}
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)
        worker_thread.builder(image)
        self.assertEqual('unmatched', image['status'])

    @mock.patch("kolla.cmd.build.docker")
    def test_builder_parent_error(self, docker):
        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)

        image = {'status': 'unprocessed', 'name': 'base',
                 'parent': {'status': 'error'}}
        worker_thread.builder(image)
        self.assertEqual('parent_error', image['status'])

        image = {'status': 'unprocessed', 'name': 'base',
                 'parent': {'status': 'parent_error'}}
        worker_thread.builder(image)
        self.assertEqual('parent_error', image['status'])

        image = {'status': 'unprocessed', 'name': 'base',
                 'parent': {'status': 'connection_error'}}
        worker_thread.builder(image)
        self.assertEqual('parent_error', image['status'])

    @mock.patch("kolla.cmd.build.WorkerThread.process_source")
    @mock.patch("kolla.cmd.build.docker")
    def test_builder_source_error(self, docker, process_soruce):
        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)

        image = {'status': 'unprocessed', 'name': 'base',
                 'source': {'source': ''}, 'parent': None}

        def process_soruce_mock(image, source):
            image['status'] = 'error'

        process_soruce.side_effect = process_soruce_mock

        worker_thread.builder(image)
        self.assertEqual('error', image['status'])

    def init_process_reource(self, requests):
        image = {'path': '/a', 'name': 'horizon'}
        source = {'type': 'url', 'name': 'horizon', 'source': 'horizon_source'}

        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)

        return image, source, worker_thread

    @mock.patch("kolla.cmd.build.os.utime")
    @mock.patch("kolla.cmd.build.tarfile")
    @mock.patch("kolla.cmd.build.shutil")
    @mock.patch("kolla.cmd.build.git")
    @mock.patch("kolla.cmd.build.requests")
    def test_process_source_url(self, requests, git, shutil, tarfile, utime):
        image, source, worker_thread = self.init_process_reource(requests)
        open_mock = mock.MagicMock()

        response = mock.MagicMock()
        response.status_code = 200
        response.content = "abc"
        requests.get.return_value = response

        with mock.patch('kolla.cmd.build.open', open_mock):
            dest_archive = worker_thread.process_source(image, source)
        self.assertEqual(dest_archive, '/a/horizon-archive')
        open_mock().__enter__.return_value. \
            write.assert_called_once_with(response.content)
        utime.assert_called_once_with(dest_archive, (0, 0))

    @mock.patch("kolla.cmd.build.os.utime")
    @mock.patch("kolla.cmd.build.tarfile")
    @mock.patch("kolla.cmd.build.shutil")
    @mock.patch("kolla.cmd.build.git")
    @mock.patch("kolla.cmd.build.requests")
    def test_process_source_url_invalid_code(self, requests, git, shutil,
                                             tarfile, utime):
        image, source, worker_thread = self.init_process_reource(requests)

        response = mock.MagicMock()
        response.status_code = 500
        requests.get.return_value = response

        worker_thread.process_source(image, source)
        self.assertEqual('error', image['status'])

    @mock.patch("kolla.cmd.build.os.utime")
    @mock.patch("kolla.cmd.build.tarfile")
    @mock.patch("kolla.cmd.build.shutil")
    @mock.patch("kolla.cmd.build.git")
    @mock.patch("kolla.cmd.build.requests")
    def test_process_source_url_timeout(self, requests, git,
                                        shutil, tarfile, utime):
        image, source, worker_thread = self.init_process_reource(requests)

        requests.get.side_effect = requests_exp.Timeout('timeout')

        worker_thread.process_source(image, source)
        self.assertEqual('error', image['status'])

    @mock.patch("kolla.cmd.build.os.utime")
    @mock.patch("kolla.cmd.build.tarfile")
    @mock.patch("kolla.cmd.build.shutil")
    @mock.patch("kolla.cmd.build.git")
    def test_process_source_git(self, git, shutil, tarfile, utime):
        image = {'path': '/a', 'name': 'horizon'}
        source = {'type': 'url', 'name': 'horizon', 'source': 'horizon_source',
                  'reference': 'master'}

        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)

        source['type'] = 'git'

        dest_archive = worker_thread.process_source(image, source)
        expected_git_args_list = [mock.call(),
                                  mock.call('/a/horizon-archive-master')]
        self.assertEqual(expected_git_args_list, git.Git.call_args_list)
        git.Git().checkout.assert_called_once_with('master')

        tarfile.open.assert_called_once_with(dest_archive, 'w')
        tarfile.open().__enter__.return_value.add.assert_called_once_with(
            '/a/horizon-archive-master', arcname='horizon-archive-master')
        utime.assert_called_once_with('/a/horizon-archive', (0, 0))

    @mock.patch("kolla.cmd.build.os.utime")
    @mock.patch("kolla.cmd.build.tarfile")
    @mock.patch("kolla.cmd.build.shutil")
    @mock.patch("kolla.cmd.build.git")
    def test_process_source_git_error(self, git, shutil, tarfile, utime):
        image = {'path': '/a', 'name': 'horizon'}
        source = {'type': 'url', 'name': 'horizon', 'source': 'horizon_source',
                  'reference': 'master'}

        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)

        source['type'] = 'git'
        git.Git.side_effect = Exception("git error")

        worker_thread.process_source(image, source)
        self.assertEqual(image['status'], 'error')

    @mock.patch('kolla.cmd.build.docker_client')
    @mock.patch("kolla.cmd.build.os")
    def test_update_buildargs(self, os_mock, dc):
        queue = mock.MagicMock()
        push_queue = mock.MagicMock()
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)
        buildargs = worker_thread.update_buildargs()
        self.assertEqual(None, buildargs)

        env = {
            'HTTP_PROXY': 'http://proxy:3128',
            'http_proxy': 'http://proxy:3128',
            'HTTPS_PROXY': 'http://proxy:3128',
            'https_proxy': 'http://proxy:3128',
        }

        os_mock.environ = env

        worker_thread = build.WorkerThread(queue, push_queue, self.conf)
        buildargs = worker_thread.update_buildargs()
        self.assertEqual({
            'HTTP_PROXY': 'http://proxy:3128',
            'http_proxy': 'http://proxy:3128',
            'HTTPS_PROXY': 'http://proxy:3128',
            'https_proxy': 'http://proxy:3128',
        }, buildargs)

        self.conf.build_args = {
            'HTTP_PROXY': 'http://proxy',
            'http_proxy': 'http://proxy',
        }
        worker_thread = build.WorkerThread(queue, push_queue, self.conf)
        buildargs = worker_thread.update_buildargs()
        self.assertEqual({
            'HTTP_PROXY': 'http://proxy',
            'http_proxy': 'http://proxy',
            'HTTPS_PROXY': 'http://proxy:3128',
            'https_proxy': 'http://proxy:3128',
        }, buildargs)


class TestPushThread(testtools.TestCase):
    @mock.patch('six.moves.queue.Queue')
    @mock.patch('threading.Thread')
    def setUp(self, Thread, Queue):
        super(TestPushThread, self).setUp()

        self.conf = cfg.CONF
        self.conf.register_opts(_CLI_OPTS)
        self.conf.register_opts(_BASE_OPTS)
        self.conf.register_opts(_PROFILE_OPTS)

        queue = mock.MagicMock()
        self.push_thread = build.PushThread(self.conf, queue)

    @mock.patch('kolla.cmd.build.docker.utils.kwargs_from_env')
    @mock.patch('kolla.cmd.build.docker.Client')
    def test_push_images_failed(self, docker_client, kwargs_from_env):
        kwargs_from_env.return_value = {}

        def push_image(*args, **kwargs):
            yield "{u'status': u'The push refers to a repository " \
                  "[docker.io/library/ubuntu] (len: 1)'}"
            yield "{u'status': u'Image already exists', u'progressDetail':" \
                  " {}, u'id': u'e9ae3c220b23'}"
            yield "{u'errorDetail': {u'message': u'unauthorized:" \
                  "access to the requested resource is not authorized'}," \
                  "u'error': u'unauthorized: access to the requested resource" \
                  "is not authorized'}"

        dc = mock.MagicMock()
        docker_client.return_value = dc
        dc.push_image = push_image

        image = {'fullname': 'base1', 'logs': ''}
        self.push_thread.push_image(image)

        image = {'fullname': 'base2', 'logs': ''}
        self.push_thread.push_image(image)

        image = {'fullname': 'base3', 'logs': ''}
        self.push_thread.push_image(image)
        self.assertEqual('error', image['status'])
