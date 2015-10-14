import os

import mock
import six
import testtools
from kolla.cmd import build


class TestKollaWorker(testtools.TestCase):
    def setUp(self):
        super(TestKollaWorker, self).setUp()
        config = {
            'namespace': 'kolla-test',
            'base': 'ubuntu',
            'base_tag': 'latest',
            'install_type': 'source',
            'tag': 'letest',
            'include_header': '',
            'include_footer': '',
            'regex': ''

        }
        self.kolla = build.KollaWorker(config)

    @mock.patch('datetime.datetime')
    def test_setup_working_dir(self, datetime_mock):
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

    @mock.patch('os.walk')
    def test_set_time(self, os_walk):
        self.kolla.working_dir = '/tmp'
        self.all_file_list = None

        os_walk.return_value = [('docker/ironic',
                                 ['ironic-base',
                                  'ironic-discoverd'],
                                 []),
                                ('docker/ironic/ironic-base',
                                 [],
                                 ['Dockerfile.j2', 'Dockerfile'])]

        def list_all_file():
            ret = []
            for root, dirs, files in os_walk.return_value:
                for file_ in files:
                    ret.append(os.path.join(root, file_))
                for dir_ in dirs:
                    ret.append(os.path.join(root, dir_))
            return ret

        def create_utime():
            self.all_file_list = list_all_file()

            def utime_side_effect(path, times):
                self.assertEqual((0, 0), times)
                self.assertIn(path, self.all_file_list)
                self.all_file_list.pop(self.all_file_list.index(path))

            return utime_side_effect

        with mock.patch('os.utime', new_callable=create_utime):
            self.kolla.set_time()
            self.assertEqual(0, len(self.all_file_list))

    @mock.patch('shutil.rmtree')
    def test_cleanup(self, rmtree):
        self.kolla.temp_dir = mock.MagicMock()
        self.kolla.cleanup()
        rmtree.assert_called_once_with(self.kolla.temp_dir)

    def test_fileter_images(self):
        self.iamges = []
        self.regex = []

    def test_build_image_list(self):
        self.docker_build_paths = ['a', 'b']




