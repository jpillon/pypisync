#!/usr/bin/env python3
import itertools
import logging
import re
import urllib.parse
import os
import subprocess
import pkginfo
import packaging.requirements
import pypisync


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
        if not isinstance(other, Hashable):
            return NotImplemented
        return self._hash_value < other._hash_value

    def __le__(self, other):
        if not isinstance(other, Hashable):
            return NotImplemented
        return self._hash_value <= other._hash_value

    def __gt__(self, other):
        if not isinstance(other, Hashable):
            return NotImplemented
        return self._hash_value > other._hash_value

    def __ge__(self, other):
        if not isinstance(other, Hashable):
            return NotImplemented
        return self._hash_value >= other._hash_value

    def __eq__(self, other):
        if not isinstance(other, Hashable):
            return NotImplemented
        return isinstance(other, type(self)) and self._hash_value == other._hash_value


class PypiPackage(Hashable):
    logger = logging.getLogger(__name__)
    """
    Defines a package with its version
    """
    def __init__(self, name, version, url=None, destination_folder=None, simple=None, environment=None):
        self._name = name
        self._version = version
        self._url = url
        self._local_file = None
        self._file_hash = None
        self._destination_folder = destination_folder
        self._simple = simple
        self._environment = environment
        if self._url is not None and self._destination_folder is not None:
            self._local_file, self._file_hash = self._create_filename(self.url, self._destination_folder, self._simple)
        self._dependencies = None

    @property
    def _hash_value(self):
        value = (self._name,)
        if self._version is not None:
            value = value + (self._version,)
        if self._url is not None:
            value = value + (self.file_basename,)
        if len(value) == 1:
            value = value[0]
        return value

    @property
    def name(self):
        return self._name

    @property
    def version(self):
        return self._version

    @property
    def url(self):
        return self._url

    @property
    def local_file(self):
        return self._local_file

    @property
    def file_hash(self):
        return self._file_hash

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

    def dependencies(self):
        """
        Read the dependencies in the local file
        :return: same format as in the "packages" config file parameter
        """
        if self._dependencies is None:
            self._dependencies = {}
            metadata = pkginfo.get_metadata(self._local_file)

            if metadata is not None:
                for require in metadata.requires_dist:
                    version, env_marker = PypiPackage._parse_requirement(require)
                    version = packaging.requirements.Requirement(version)
                    if env_marker is not None:
                        if not PypiPackage.evaluate_env_marker(env_marker, self._environment):
                            continue
                    if version.name not in self._dependencies:
                        self._dependencies[version.name] = set()
                    specifier = str(version.specifier).strip()
                    if specifier == "":
                        specifier = "latest"
                    if specifier not in self._dependencies[version.name]:
                        self._dependencies[version.name].add(specifier)
        return self._dependencies

    def _download_url(self, url, filename):
        self.logger.debug("Filename: %s", filename)
        self.logger.debug("URL: %s", url)
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        # TODO: Pure python ?
        subprocess.check_call(
            [
                "wget",
                "-U", pypisync.USER_AGENT,
                "-c",
                url,
                "-O",
                filename
            ],
            stderr=subprocess.PIPE
        )

    @staticmethod
    def _get_hash_from_url(url):
        file_hash = urllib.parse.urlparse(url).fragment.split("=")[1]
        filename = os.path.basename(urllib.parse.urlparse(url).path)
        return filename, file_hash

    @property
    def file_basename(self):
        filename, _ = self._get_hash_from_url(self.url)
        return os.path.basename(filename)

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

    def download(self):
        self._download_url(self.url, self.local_file)
