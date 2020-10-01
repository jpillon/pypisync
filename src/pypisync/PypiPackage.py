#!/usr/bin/env python3
import itertools
import logging
import re
import urllib.parse
import os
import subprocess
import pkginfo
import packaging.requirements
from multiprocessing import Pool


class Hashable:
    @property
    def _hash_value(self):
        raise NotImplementedError

    def __str__(self):
        return str(self._hash_value)

    def __repr__(self):
        return repr(self._hash_value)

    def __hash__(self):
        return hash(self._hash_value)

    def __lt__(self, other):
        return self._hash_value < other._hash_value

    def __le__(self, other):
        return self._hash_value <= other._hash_value

    def __gt__(self, other):
        return self._hash_value > other._hash_value

    def __ge__(self, other):
        return self._hash_value >= other._hash_value

    def __eq__(self, other):
        return isinstance(other, type(self)) and self._hash_value == other._hash_value


class PypiPackage(Hashable):
    logger = logging.getLogger(__name__)
    """
    Defines a package with its version
    """
    def __init__(self, name, version):
        self._name = name
        self._version = version
        self._urls = set()
        self._local_files = []
        self._hashes = []

    @property
    def _hash_value(self):
        return self._name, self._version

    @property
    def name(self):
        return self._name

    @property
    def version(self):
        return self._version

    def add_url(self, url):
        self._urls.add(url)

    @property
    def urls(self):
        return sorted(self._urls)

    @property
    def files(self):
        return self._local_files

    @property
    def hashes(self):
        return self._hashes

    @staticmethod
    def _find_suitable_value(variable, marker):
        operators = [
            r"\>=",
            r"\<=",
            r"\>",
            r"\<",
            "==",
            "!=",
            "in",
        ]
        variable_re_str = r".*%s *(?P<op>(%s)) *(?P<value>([^ ()]+)).*" % (variable, ")|(".join(operators))
        variable_re = re.compile(variable_re_str)
        match = variable_re.match(marker)
        value = match.group("value")
        for c in ['"', "'"]:
            while c in value:
                value = value.replace(c, "")
        op = match.group("op")
        matching_ops = [
            "==",
            ">=",
            "<=",
            "in"
        ]
        matching_value = None
        if op in matching_ops:
            matching_value = value
        elif op == ">":
            tokens = value.split(".")
            tokens[-1] = str(int(tokens[-1])+1)
            matching_value = ".".join(tokens)
        elif op == "<":
            tokens = value.split(".")
            tokens[-1] = str(int(tokens[-1])-1)
            matching_value = ".".join(tokens)
        elif op == "!=":
            matching_value = "%s.9999" % value

        return matching_value

    @staticmethod
    def evaluate_env_marker(marker, environment):
        if environment is None:
            return True
        variables = sorted(environment.keys())

        evaluate_variables = {}

        for variable in variables:
            # get the markers elements
            if variable in marker:
                evaluate_variables[variable] = environment[variable]

        if len(evaluate_variables) > 0:
            # OK, need some work here
            # If there are some None values, we need to replace it with a matching value in the evaluation context
            for variable in evaluate_variables:
                if evaluate_variables[variable] is None:
                    evaluate_variables[variable] = [PypiPackage._find_suitable_value(variable, marker)]
                elif len(evaluate_variables[variable]) == 0:
                    # Add at least an impossible value here...
                    evaluate_variables[variable] = ["____impossible_value____"]
            # Evaluate with cross multiplication
            tmp = []
            for variable in sorted(evaluate_variables.keys()):
                tmp.append(evaluate_variables[variable])
            for values in itertools.product(*tmp):
                # build a context
                context = {}
                for i, variable in enumerate(sorted(evaluate_variables.keys())):
                    context[variable] = values[i]
                result = eval(marker, {}, context)
                if not result:
                    return result
        return True

    @staticmethod
    def _parse_requirement(requirement):
        tokens = [x.strip() for x in requirement.split(";")]
        version = tokens[0]
        env_marker = None
        if len(tokens) > 1:
            env_marker = tokens[1]
        return version, env_marker

    @staticmethod
    # @pypisync.memoize()
    def _read_dependencies_from_file(filename, environment):
        """
        Read the dependencies in the local file
        :return: same format as in the "packages" config file parameter
        """
        result = {}
        metadata = pkginfo.get_metadata(filename)

        if metadata is not None:
            for require in metadata.requires_dist:
                version, env_marker = PypiPackage._parse_requirement(require)
                version = packaging.requirements.Requirement(version)
                if env_marker is not None:
                    if not PypiPackage.evaluate_env_marker(env_marker, environment):
                        continue
                if version.name not in result:
                    result[version.name] = []
                specifier = str(version.specifier).strip()
                if specifier == "":
                    specifier = "latest"
                if specifier not in result[version.name]:
                    result[version.name].append(specifier)
        return result

    def dependencies(self, environment):
        """
        Read the dependencies in the local files
        :return: same format as in the "packages" config file parameter
        """
        result = {}
        for filename in self._local_files:
            result.update(
                self._read_dependencies_from_file(filename, environment)
            )
        return result

    def _download_url(self, url_filename):
        url, filename = url_filename
        self.logger.debug("Filename: %s", filename)
        self.logger.debug("URL: %s", url)
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        # TODO: Pure python ?
        # subprocess.check_call(
        #     [
        #         "curl",
        #         "-L",
        #         "-o",
        #         filename,
        #         "-O",
        #         "-C", "-",
        #         url
        #     ],
        #     stderr=subprocess.PIPE
        # )

        subprocess.check_call(
            [
                "wget",
                "-c",
                url,
                "-O",
                filename
            ],
            stderr=subprocess.PIPE
        )
        # wget.download(url, filename)
        # response = requests.get(url, allow_redirects=True)
        # checksum = hashlib.sha256()
        # with open(filename, "wb") as f:
        #     while True:
        #         chunk = response.content
        #         if not chunk:
        #             break
        #         checksum.update(chunk)
        #         f.write(chunk)
        # file_basename, file_hash = self._get_hash_from_url(url)
        # existing_hash = checksum.hexdigest()
        # if existing_hash != file_hash:
        #     if retry:
        #         self.logger.warning("Hash mismatch for %s, retrying", file_basename)
        #         os.unlink(filename)
        #     else:
        #         self.logger.error("Hash mismatch for %s, giving up...", file_basename)

    @staticmethod
    def _get_hash_from_url(url):
        file_hash = urllib.parse.urlparse(url).fragment.split("=")[1]
        filename = os.path.basename(urllib.parse.urlparse(url).path)
        return filename, file_hash

    @classmethod
    def _create_filename(cls, url, destination_folder, simple_layout):
        """
        Create the filename from the url
        """
        # TODO: Do we really trust this ?
        file_basename, file_hash = cls._get_hash_from_url(url)
        if simple_layout:
            path = [
                destination_folder,
                "packages",
                file_hash[:2],
                file_hash[2:4],
                file_hash[4:],
                file_basename
            ]
            filename = os.path.join(*path)
        else:
            filename = os.path.join(destination_folder, file_basename)
        return filename, file_hash

    def download(self, destination_folder, simple_layout):
        if not os.path.exists(destination_folder):
            os.mkdir(destination_folder)
        self.logger.debug("Downloading %s %s", self._name, self._version)

        for url in self.urls:
            filename, file_hash = self._create_filename(url, destination_folder, simple_layout)
            self._local_files.append(filename)
            self._hashes.append(file_hash)

        # for x in zip(self.urls, self._local_files):
        #     self._download_url(x)
        pool = Pool(min(len(self.urls), 8))
        pool.map(self._download_url, zip(self.urls, self._local_files))
