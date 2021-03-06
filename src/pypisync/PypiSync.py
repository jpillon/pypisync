#!/usr/bin/env python3
import os
import logging
import json
import pypi_simple
import concurrent.futures
import packaging.version
import packaging.specifiers
import re
import requests
from tqdm import tqdm

import pypisync


class LightPackage:
    def __init__(self, project, version, filename, url, yanked):
        self.project = project
        self.version = version
        self.filename = filename
        self.url = url
        self.yanked = yanked


class PypiConnector:
    _xmlrpc_client = None
    _simple_client = None
    _endpoint_base = None
    _xmlrpc_endpoint = None
    _simple_endpoint = None
    _project_info_cache = {}

    def __init__(self, endpoint_base):
        self.initialize(endpoint_base)

    @classmethod
    def initialize(cls, endpoint_base):
        if endpoint_base is None:
            endpoint_base = "https://pypi.org/"
        while endpoint_base.endswith("/"):
            endpoint_base = endpoint_base[:-1]
        cls._endpoint = endpoint_base
        cls._xmlrpc_endpoint = "%s/pypi/" % cls._endpoint
        cls._simple_endpoint = "%s/simple/" % cls._endpoint
        # cls._simple_client = pypi_simple.PyPISimple(endpoint=cls._simple_endpoint)
        cls._xmlrpc_client = pypisync.ServerProxy(
            cls._xmlrpc_endpoint,
            headers=[("User-Agent", pypisync.USER_AGENT)]
        )

    @staticmethod
    def get_projects_names():
        return PypiConnector._xmlrpc_client.list_packages()

    @staticmethod
    def get_project_info(project_name, arch_exclude):
        if project_name not in PypiConnector._project_info_cache:
            PypiConnector._project_info_cache[project_name] = list(PypiConnector.get_project_info_generator(project_name, arch_exclude))
        return PypiConnector._project_info_cache[project_name]

    @staticmethod
    def get_project_info_generator(project_name, arch_exclude):
        url = "%s%s/json" % (PypiConnector._xmlrpc_endpoint, project_name)
        response = requests.get(url, allow_redirects=True)
        if int(response.status_code) != 200:
            return
        content = response.content.decode()
        data = json.loads(content)
        name = data["info"]["name"]
        for version in data["releases"]:
            for variant in data["releases"][version]:
                sha256 = variant["digests"]["sha256"]
                package = LightPackage(
                    name,
                    version,
                    variant["filename"],
                    "%s#sha256=%s" % (variant["url"], sha256),
                    variant["yanked"],
                )
                keep_it = True
                if arch_exclude:
                    arch = package.filename.replace("%s-%s" % (package.project, package.version), "")
                    for exclude in arch_exclude:
                        if exclude in arch:
                            keep_it = False

                if keep_it:
                    yield package


class PypiSync:
    logger = logging.getLogger(__name__)

    def __init__(self, config_file, simple_layout, gen_graph):
        self.logger.debug("Loading configuration: %s", config_file)
        with open(config_file, 'rt') as fp:
            data = json.load(fp)
        self._connector = PypiConnector(data["endpoint"])
        self._simplified_dependencies = {}
        self._in_packages_list = data["packages"]
        self._environment = None
        if "environment" in data:
            self._environment = data["environment"]
        self._destination_folder = os.path.abspath(data["destination_folder"])
        self._downloaded = set()
        self._arch_exclude = None
        if "arch_exclude" in data:
            self._arch_exclude = data["arch_exclude"]

        self._packages_re = None
        if "packages_re" in data and data["packages_re"]:
            self._packages_re = data["packages_re"]
        self._simple_layout = simple_layout
        self._gen_graph = gen_graph

    @staticmethod
    def _version_match(wanted, current):
        try:
            wanted = packaging.specifiers.SpecifierSet(wanted)
            current = packaging.version.Version(current)
            result = current in wanted
        except packaging.specifiers.InvalidSpecifier:
            wanted = packaging.version.Version(wanted)
            current = packaging.version.Version(current)
            result = current == wanted
        except packaging.version.InvalidVersion:
            # Bad version. don't download it
            result = False
        return result

    def _latest_version(self, package, arch_exclude, n=1, spec=None):
        all_versions_str = set()
        for project in self._connector.get_project_info(package, arch_exclude):
            if spec is not None:
                if not self._version_match(spec, project.version):
                    continue
            all_versions_str.add(project.version)

        all_versions = []
        for version_str in all_versions_str:
            try:
                all_versions.append(packaging.version.Version(version_str))
            except packaging.version.InvalidVersion:
                # Ignore them...
                pass

        all_versions = sorted(all_versions)
        if not all_versions:
            return None
        while len(all_versions) < n:
            n -= 1
        if spec is None:
            return ">=%s" % all_versions[-n]
        else:
            return ">=%s,%s" % (all_versions[-n], spec)

    @staticmethod
    def _keep_latest(packages):
        all_versions = []
        for project in packages:
            if not project.yanked:
                all_versions.append(packaging.version.Version(project.version))
        all_versions = sorted(set(all_versions))
        if all_versions:
            latest_version = all_versions[-1]
            for project in packages:
                if packaging.version.Version(project.version) == latest_version:
                    yield project

    def packages(self, packages, latest_only=False):
        ref_latest_re = re.compile("^(?P<n>[0-9]+)? *latest(?P<spec>.*)?$")
        for package in packages:
            wanted_versions = packages[package]

            for wanted_version in wanted_versions:
                if wanted_version == "latest":
                    wanted_version = "1 latest"
                ref_latest = ref_latest_re.fullmatch(wanted_version)
                if ref_latest:
                    n = 1
                    if ref_latest.group("n") is not None:
                        n = int(ref_latest.group("n"))
                    wanted_version = self._latest_version(
                        package,
                        self._arch_exclude,
                        n,
                        ref_latest.group("spec")
                    )
                if wanted_version is None:
                    continue
                matched = []
                for project in self._connector.get_project_info(package, self._arch_exclude):
                    if self._version_match(wanted_version, project.version):
                        matched.append(project)
                if latest_only:
                    matched = self._keep_latest(matched)

                for project_ in matched:
                    yield pypisync.PypiPackage(
                        project_.project,
                        project_.version,
                        project_.url,
                        self._destination_folder,
                        self._simple_layout,
                        self._environment
                    )

    @staticmethod
    def _download_package(package):
        PypiSync.logger.info(
            "Downloading %s %s %s",
            package.name,
            package.version,
            os.path.basename(package.file_basename)
        )
        package.download()
        return package, package.dependencies()

    def _download(self, packages):
        results = []
        all_dependencies = set()
        for package in packages:
            if package in self._downloaded:
                continue
            # submit packages for downloading
            with concurrent.futures.ProcessPoolExecutor() as executor:
                results.append(
                    executor.submit(
                        self._download_package,
                        package
                    )
                )

        # retrieve the dependencies
        for result in results:
            package, dependencies = result.result()
            packages_dependencies = set(self.packages(dependencies, True))
            all_dependencies.update(packages_dependencies)
            self._downloaded.add(package)

            simplified = pypisync.PypiPackage(pypi_simple.normalize(package.name), package.version)
            if simplified not in self._simplified_dependencies:
                self._simplified_dependencies[simplified] = set()
            for dependency in packages_dependencies:
                self._simplified_dependencies[simplified].add(
                    pypisync.PypiPackage(pypi_simple.normalize(dependency.name), dependency.version)
                )

        if all_dependencies:
            self._download(all_dependencies)

    def run(self):
        self._downloaded = set()
        this_package_list = {}
        self._simplified_dependencies = {}
        if self._packages_re is not None:
            # build a primary package list from the simple index
            self.logger.info("Getting the packages list (might take some time...)")
            for package in tqdm(self._connector.get_projects_names(), desc="Filtering", unit=" packages"):
                for packages_re_str in self._packages_re:
                    packages_re = re.compile(packages_re_str)
                    if packages_re.match(package):
                        if package not in this_package_list:
                            this_package_list[package] = []
                        this_package_list[package] += self._packages_re[packages_re_str]
        this_package_list.update(self._in_packages_list)
        self._download(self.packages(this_package_list))

        if self._simple_layout:
            generator = pypisync.SimpleIndexGenerator(os.path.join(self._destination_folder, "simple"))
            generator.generate(self._downloaded)

        # Generate dependencies tree.
        if self._gen_graph:
            self.logger.info("Generating dependency graph")
            with open('./graph.dot', 'w') as out:
                for line in ('digraph G {',):
                    out.write('{}\n'.format(line))
                for p in self._simplified_dependencies:
                    out.write('{} [label="{}"];\n'.format(hash(p), p))
                for p in self._simplified_dependencies:
                    for d in self._simplified_dependencies[p]:
                        out.write('{} -> {};\n'.format(hash(p), hash(d)))
                out.write('}\n')
        return 0
