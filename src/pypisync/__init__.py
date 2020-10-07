#!/usr/bin/env python3


__version__ = "1.0.0"

from .PypiSync import PypiSync
from .PypiPackage import PypiPackage
from .XmlRPC import ServerProxy
from .SimpleIndexGenerator import SimpleIndexGenerator

USER_AGENT = f"pypisync {__version__}"


def main(config_file, simple_layout, gen_graph):
    syncer = PypiSync(config_file, simple_layout, gen_graph)
    return syncer.run()
