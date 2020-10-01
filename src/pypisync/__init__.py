#!/usr/bin/env python3


__version__ = "1.0.0"

from .memoize import memoize
from .PypiSync import PypiSync
from .PypiPackage import PypiPackage
from .XmlRPC import ServerProxy


def main(config_file, simple_layout, no_cache):
    try:
        syncer = PypiSync(config_file, simple_layout, no_cache)
        return syncer.run()
    finally:
        memoize.save()
