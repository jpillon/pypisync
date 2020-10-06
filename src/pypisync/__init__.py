#!/usr/bin/env python3


__version__ = "1.0.0"

from .PypiSync import PypiSync
from .PypiPackage import PypiPackage
from .XmlRPC import ServerProxy
from .SimpleIndexGenerator import SimpleIndexGenerator


def main(config_file, simple_layout, no_cache, gen_graph):
    syncer = PypiSync(config_file, simple_layout, no_cache, gen_graph)
    return syncer.run()
