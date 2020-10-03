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
            headers=[("User-Agent", f"pypisync {pypisync.__version__}")]
        )

    @staticmethod
    @pypisync.memoize(True)
    def get_projects_names():
        return PypiConnector._xmlrpc_client.list_packages()

    @staticmethod
    @pypisync.memoize(True)
    def get_project_info(project_name, arch_exclude):
        return list(PypiConnector.get_project_info_generator(project_name, arch_exclude))

    @staticmethod
    def get_project_info_generator(project_name, arch_exclude):
        url = "%s%s/json" % (PypiConnector._xmlrpc_endpoint, project_name)
        response = requests.get(url, allow_redirects=True)
        if int(response.status_code) != 200:
            return
        content = response.content
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

    def __init__(self, config_file, simple_layout, no_cache):
        self.logger.debug("Loading configuration: %s", config_file)
        with open(config_file, 'rt') as fp:
            data = json.load(fp)
        self._connector = PypiConnector(data["endpoint"])

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
        self._dependencies = {}
        pypisync.memoize.filename = ".%s" % __name__
        self._simple_layout = simple_layout
        if not no_cache:
            pypisync.memoize.load()

    @staticmethod
    @pypisync.memoize()
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

        PypiSync.logger.debug("%s, %s => %s", wanted, current, result)
        return result

    def _latest_version(self, package, arch_exclude, n=1):
        all_versions = []
        for project in self._connector.get_project_info(package, arch_exclude):
            try:
                all_versions.append(packaging.version.Version(project.version))
            except packaging.version.InvalidVersion:
                # Ignore them...
                pass

        all_versions = sorted(set(all_versions))
        if not all_versions:
            return None
        while len(all_versions) < n:
            n -= 1
        return ">=%s" % all_versions[-n]

    @staticmethod
    @pypisync.memoize()
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
        for package in packages:
            wanted_versions = packages[package]

            for wanted_version in wanted_versions:
                if wanted_version == "latest":
                    wanted_version = "1 latest"
                if "latest" in wanted_version:
                    latest_only = True
                if wanted_version.endswith("latest"):
                    wanted_version = self._latest_version(
                        package,
                        self._arch_exclude,
                        int(wanted_version.replace("latest", ""))
                    )
                if wanted_version is None:
                    continue
                matched = []
                if latest_only:
                    while "latest" in wanted_version:
                        wanted_version = wanted_version.replace("latest", "")
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
                if package not in self._dependencies:
                    self._dependencies[package] = set()

        # retrieve the dependencies
        for result in results:
            package, dependencies = result.result()
            self._dependencies[package].update(set(self.packages(dependencies, True)))
            all_dependencies.update(self._dependencies[package])
            self._downloaded.add(package)

        if all_dependencies:
            self._download(all_dependencies)

    def run(self):
        self._downloaded = set()
        this_package_list = {}
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
        # TODO: add a command line switch for this
        # TODO: This is buggy as if A and B depends on C, it will only appear for the first downloaded one.
        # simplify = {}
        # for package in self._dependencies:
        #     simplified = pypisync.PypiPackage(package.name, package.version, None)
        #     if simplified not in simplify:
        #         simplify[simplified] = set()
        #     for dep in self._dependencies[package]:
        #         simplify[simplified].add(pypisync.PypiPackage(dep.name, dep.version, None))
        #
        # with open('./graph.dot', 'w') as out:
        #     for line in ('digraph G {',):
        #         out.write('{}\n'.format(line))
        #     for p in simplify:
        #         out.write('{} [label="{}"];\n'.format(hash(p), p))
        #     for p in simplify:
        #         for d in simplify[p]:
        #             out.write('{} -> {};\n'.format(hash(p), hash(d)))
        #     out.write('}\n')
