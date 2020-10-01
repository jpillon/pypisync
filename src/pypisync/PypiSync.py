#!/usr/bin/env python3
import os
import logging
import json
import pypi_simple
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
        return list(PypiConnector. get_project_info_generator(project_name, arch_exclude))

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
        except:
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

    def get_distribution_packages(self, packages, latest_only=False, progress=False):
        desc = "Building package list"
        if progress:
            iterator = tqdm(
                packages,
                desc=desc,
                unit=" packages",
                bar_format="{desc:<50}{percentage:3.0f} %|{bar}{r_bar:<50}"
            )
        else:
            iterator = packages
        for package in iterator:
            if progress:
                iterator.set_description("%s %s" % (desc, package))
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
                    yield project_
            if progress:
                iterator.set_description(desc)

    def build_packages_list(self, packages_list, latest_only=False, progress=False):
        packages = {}
        for package in self.get_distribution_packages(packages_list, latest_only, progress=progress):
            if (package.project, package.version) not in packages:
                packages[(package.project, package.version)] = pypisync.PypiPackage(package.project, package.version)
                yield packages[(package.project, package.version)]
            packages[(package.project, package.version)].add_url(package.url)

    def _download(self, packages):
        packages = set(packages)
        packages = packages.difference(self._downloaded)
        if len(packages) == 0:
            return

        all_dependencies = set()
        iterator = tqdm(
            packages,
            desc="Downloading",
            unit=" packages",
            bar_format="{desc:<50}{percentage:3.0f} %|{bar}{r_bar:<50}"
        )
        for package in iterator:
            iterator.set_description("%s %s" % (package.name, package.version), refresh=True)
            self.logger.debug("Downloading %s %s", package.name, package.version)
            self._downloaded.add(package)
            package.download(self._destination_folder, self._simple_layout)
            self._dependencies[package] = set(self.build_packages_list(package.dependencies(self._environment), True))
            all_dependencies.update(self._dependencies[package])
            iterator.set_description("", refresh=True)

        self._download(all_dependencies)

    def _generate_simple_index(self):
        simple_root = os.path.join(self._destination_folder, "simple")
        data = {}
        for package in sorted(self._downloaded):
            package_name = pypi_simple.normalize(package.name)

            if package_name not in data:
                data[package_name] = {
                    "package_root": os.path.join(simple_root, package_name),
                    "links": [],
                    "basenames": [],
                    "file_hashes": []
                }

            for filename, file_hash in sorted(zip(package.files, package.hashes)):
                link = os.path.relpath(filename, data[package_name]["package_root"])
                basename = os.path.basename(filename)
                data[package_name]["links"].append(link)
                data[package_name]["basenames"].append(basename)
                data[package_name]["file_hashes"].append(file_hash)

        for package_name in data:
            os.makedirs(data[package_name]["package_root"], exist_ok=True)
            with open(os.path.join(data[package_name]["package_root"], "index.html"), "wt") as index_html:
                # TODO: Proper template
                index_html.write("""<!DOCTYPE html>
<html>
  <head>
    <title>Links for {package_name}</title>
  </head>
  <body>
    <h1>Links for {package_name}</h1>
""".format(package_name=package_name))

                for link, basename, file_hash in zip(
                        data[package_name]["links"],
                        data[package_name]["basenames"],
                        data[package_name]["file_hashes"]
                ):
                    index_html.write(
                        '    <a href="{link}#sha256={hash}">{basename}</a><br/>\n'.format(
                            link=link,
                            basename=basename,
                            hash=file_hash
                        )
                    )

                index_html.write("""  </body>
</html>
""")

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
        self._download(self.build_packages_list(this_package_list, progress=True))

        if self._simple_layout:
            self._generate_simple_index()

        # Generate dependencies tree. TODO: add a command line switch for this
        with open('./graph.dot', 'w') as out:
            for line in ('digraph G {',):
                out.write('{}\n'.format(line))
            for p in self._dependencies:
                out.write('{} [label="{}"];\n'.format(hash(p), p))
            for p in self._dependencies:
                for d in self._dependencies[p]:
                    out.write('{} -> {};\n'.format(hash(p), hash(d)))
            out.write('}\n')
