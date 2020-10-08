import unittest
import os
import shutil
import tempfile
import ddt
import json
import itertools
import pypisync
import subprocess
import threading
import virtualenv
import time
import copy
import packaging.version
import packaging.specifiers


class HTTPServerTest(unittest.TestCase):
    """
    Test case that creates a random temporary directory and serves its content with a http server
    """
    def __init__(self, methodName='runTest'):
        super().__init__(methodName=methodName)
        self.temp_data_dir = None
        self._server_thread = None
        self._server_process = None
        self.server_url = None

    def _run_http_server(self):
        self._server_process = subprocess.Popen(
            [
                "python3",
                "-m",
                "http.server",
                "-d", self.temp_data_dir,
                "1357"
            ]
        )

    def setUp(self) -> None:
        """
        """
        super().setUp()
        # Create a random temporary directory
        self.server_url = "http://localhost:1357"
        self.temp_data_dir = tempfile.mkdtemp(suffix="pypisync_tests_data_dir")
        self._server_thread = threading.Thread(target=self._run_http_server)
        self._server_thread.start()
        time.sleep(0.5)

    def tearDown(self) -> None:
        """
        """
        super().tearDown()
        if self._server_thread is not None:
            self._server_process.kill()
            self._server_process.wait()
            self._server_thread.join()
        self._server_thread = None
        self._server_process = None
        self.server_url = None

        # Cleanup the temporary directory
        if os.path.exists(self.temp_data_dir):
            shutil.rmtree(self.temp_data_dir)


@ddt.ddt
class PypiUnitTests(unittest.TestCase):
    """
    Perform some unit tests
    """

    # An environment configuration that shall accept everything
    accept_all_environment = {
        "os_name": None,
        "sys_platform": None,
        "platform_machine": None,
        "platform_python_implementation": None,
        "platform_release": None,
        "platform_system": None,
        "platform_version": None,
        "python_version": None,
        "python_full_version": None,
        "implementation_name": None,
        "implementation_version": None,
        "extra": None
    }

    no_extra_environment = copy.deepcopy(accept_all_environment)
    no_extra_environment["extra"] = []

    some_extra_environment = copy.deepcopy(accept_all_environment)
    some_extra_environment["extra"] = ["test", "security"]

    python2_environment = copy.deepcopy(accept_all_environment)
    python2_environment["python_version"] = ["2", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7"]

    # data for evaluate_env_marker
    env_marker_data = [
        (accept_all_environment, 'extra in "any_value"', True),
        (accept_all_environment, 'extra == "any_value"', True),
        (accept_all_environment, 'extra != "any_value"', True),
        (accept_all_environment, 'os_name == "any_value"', True),
        (accept_all_environment, 'sys_platform == "any_value"', True),
        (accept_all_environment, 'platform_machine == "any_value"', True),
        (accept_all_environment, 'platform_python_implementation == "any_value"', True),
        (accept_all_environment, 'platform_release == "any_value"', True),
        (accept_all_environment, 'platform_system == "any_value"', True),
        (accept_all_environment, 'platform_version == "any_value"', True),
        (accept_all_environment, 'python_full_version == "any_value"', True),
        (accept_all_environment, 'python_full_version == "any_value"', True),
        (accept_all_environment, 'implementation_name == "any_value"', True),
        (accept_all_environment, 'implementation_version == "any_value"', True),
        (accept_all_environment, 'extra == "any_value"', True),
        (accept_all_environment, 'platform_version>"1"', True),
        (accept_all_environment, 'platform_version<"1"', True),
        (accept_all_environment, 'platform_version >= "1"', True),
        (accept_all_environment, 'platform_version <= "1"', True),
        (accept_all_environment, 'platform_version == "1"', True),
        (accept_all_environment, 'platform_version != "1"', True),
        (accept_all_environment, 'python_version in "2.6 2.7 3.2 3.3"', True),
        (accept_all_environment, 'os_name in "a b c d"', True),
        (accept_all_environment, 'python_version == "2.6" or python_version == "2.7" or python_version == "3.2"', True),
        (accept_all_environment, "python_version < '2.7'", True),
        (accept_all_environment, 'python_version < "2.7"', True),
        (accept_all_environment, 'python_version == "2.7"', True),
        (accept_all_environment, "python_version >= '2.7'", True),
        (accept_all_environment, 'python_version <= "2.7"', True),
        (accept_all_environment, 'python_version < "2.7"', True),
        (accept_all_environment, "python_version == '2.7'", True),
        (accept_all_environment, 'python_version == "2.7"', True),
        (accept_all_environment, 'python_version > "2.7"', True),
        (accept_all_environment, '(python_version == "2.7") and extra == \'secure\'', True),
        (accept_all_environment, '(python_version == "2.7") and extra == \'test\'', True),
        (accept_all_environment, '(python_version == "2.7") and extra == \'test\'', True),
        (accept_all_environment, '(python_version == "2.7") and extra == \'testing\'', True),
        (accept_all_environment, 'python_version >= "2.7" and python_version < "2.8"', True),
        (
            accept_all_environment,
            'python_version >= "2.7" and python_version < "2.8" or python_version >= "3.4" and python_version < "3.5"',
            True
        ),
        (accept_all_environment, 'python_version > "2.7" and python_version < "2.8"', True),
        (accept_all_environment, 'python_version == "2.7" or python_version == "3.3"', True),
        (accept_all_environment, "python_version < '3'", True),
        (accept_all_environment, "python_version >= '3'", True),
        (accept_all_environment, "python_version < '3'", True),
        (accept_all_environment, 'python_version < "3"', True),
        (accept_all_environment, 'python_version > "3"', True),
        (accept_all_environment, 'python_version < "3.0"', True),
        (accept_all_environment, 'python_version >= "3.0"', True),
        (no_extra_environment, 'extra == "test"', False),
        (no_extra_environment, '(python_version < "3.0") and extra == "test"', False),
        (no_extra_environment, 'extra == "security"', False),
        (no_extra_environment, '(python_version < "3.0") and extra == "security"', False),
        (some_extra_environment, 'extra == "test"', True),
        (some_extra_environment, '(python_version < "3.0") and extra == "test"', True),
        (some_extra_environment, 'extra == "tests"', False),
        (some_extra_environment, '(python_version < "3.0") and extra == "tests"', False),
        (some_extra_environment, 'extra == "security"', True),
        (some_extra_environment, '(python_version < "3.0") and extra == "security"', True),
        (some_extra_environment, '(python_version < "3.0")', True),
        (python2_environment, '(python_version < "3.0")', True),
        (python2_environment, '(python_version <= "3.0")', True),
        (python2_environment, '(python_version >= "3.0")', False),
        (python2_environment, '(python_version <= "1")', False),
        (python2_environment, '(python_version > "2")', True),
        (python2_environment, '(python_version == "2.7")', True),
        (python2_environment, '(python_version > "2.1")', True),
        (python2_environment, '(python_version > "2.6.8")', True),
        (python2_environment, '(python_version > "2.7")', False),

    ]

    @ddt.idata(env_marker_data)
    def test_env_marker(self, data):
        environment, marker, expect = data
        self.assertEqual(
            pypisync.PypiPackage.evaluate_env_marker(marker, environment),
            expect
        )


@ddt.ddt
class PypiSyncTests(HTTPServerTest):
    """
    Performs some integration tests
    """

    # Packages that will be tested
    packages_to_test = [
        ("pyyaml", "latest"),
        ("pyyaml", "5.1.1"),
        ("pyyaml", "latest>5.0.0"),
        ("pyyaml", ">=5.2.0"),
        ("awscli", "latest"),
        ("django", "2 latest<3"),
        ("djangorestframework", "latest"),
    ]

    # alternatively activate the "simple" layout
    simple_values = [
        True,
        False,
    ]

    default_config = {
        "endpoint": None,
        "destination_folder": None,
        "arch_exclude": None,
        "environment": {
            "os_name": None,
            "sys_platform": None,
            "platform_machine": None,
            "platform_python_implementation": None,
            "platform_release": None,
            "platform_system": None,
            "platform_version": None,
            "python_version": None,
            "python_full_version": None,
            "implementation_name": None,
            "implementation_version": None,
            "extra": []  # Don't download "extras" by default
        },
        "packages_re": {
        },
        "packages": {
        }
    }

    def __init__(self, methodName='runTest'):
        super().__init__(methodName=methodName)
        self.current_config = None
        self.current_config_file = None
        self.venv_dir = None

    def generate_config_file(self):
        with open(self.current_config_file, "wt") as config_file:
            json.dump(self.current_config, config_file)

    def check_install_package(self, package, simple):
        pip_args = ["--no-cache-dir"]
        if simple:
            pip_args.append("-i")
            pip_args.append("%s/simple" % self.server_url)
        else:
            pip_args.append("--no-index")
            pip_args.append("-f")
            pip_args.append(self.temp_data_dir)

        # create the virtualenv
        self.venv_dir = tempfile.mkdtemp(suffix="pypisync_tests_venv")
        virtualenv.cli_run([self.venv_dir])

        # install the package
        version = ""
        try:
            version = "==%s" % packaging.version.Version(package[1])
        except packaging.version.InvalidVersion:
            try:
                version = "%s" % packaging.specifiers.SpecifierSet(package[1])
            except packaging.specifiers.InvalidSpecifier:
                pass

        package_name = "%s%s" % (package[0], version)

        self.assertEqual(
            subprocess.check_call(
                [
                    "pip",
                    "install",
                    package_name,
                    "--prefix",
                    self.venv_dir
                ] + pip_args
            ),
            0
        )

        # cleanup the venv
        shutil.rmtree(self.venv_dir, ignore_errors=True)

    def setUp(self) -> None:
        """
        """
        super().setUp()
        # Create the default configuration
        self.current_config_file = tempfile.mktemp(suffix="pypisync_tests_config_file")
        self.current_config = copy.deepcopy(self.default_config)
        self.current_config["destination_folder"] = self.temp_data_dir
        self.generate_config_file()

    def tearDown(self) -> None:
        """
        """
        super().tearDown()
        if os.path.exists(self.current_config_file):
            os.unlink(self.current_config_file)
        if self.venv_dir is not None:
            shutil.rmtree(self.venv_dir, ignore_errors=True)
        self.venv_dir = None

    @ddt.idata(itertools.product(simple_values, packages_to_test))
    def test_sync_and_install(self, data):
        """
        Download a given package and check if it is installable
        """
        simple, package = data
        # Update the configuration with the given package
        self.current_config["packages"][package[0]] = [package[1]]
        if "pip" not in self.current_config["packages"]:
            self.current_config["packages"]["pip"] = ["latest"]
        self.generate_config_file()

        self.assertEqual(
            pypisync.main(
                self.current_config_file, simple, False
            )
            , 0
        )

        self.check_install_package(package, simple)

    def test_re(self):
        """
        Download a given package and check if it is installable
        """
        # Update the configuration with the given package
        self.current_config["packages_re"]["pyyaml"] = ["latest"]
        if "pip" not in self.current_config["packages"]:
            self.current_config["packages"]["pip"] = ["latest"]
        self.generate_config_file()

        self.assertEqual(
            pypisync.main(
                self.current_config_file, False, False
            ),
            0
        )

        self.check_install_package(("pyyaml", "latest"), False)
