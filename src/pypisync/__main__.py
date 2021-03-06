#!/usr/bin/env python3

import sys
import argparse
import pypisync
import logging


def create_parser():
    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--config", help="Path to the configuration file", default="./pypisync.conf")
    parser.add_argument("-d", "--debug", help="Activate debug", action="store_true", default=False)
    parser.add_argument("-g", "--gen_graph", help="Generate a dependency graph", action="store_true", default=False)
    parser.add_argument(
        "-s",
        "--simple_layout",
        help="Save the downloaded files with the simple compatible layout",
        action="store_true",
        default=False
    )

    return parser


def main():
    opts = create_parser().parse_args(sys.argv[1:])
    if opts.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    sys.exit(pypisync.main(opts.config, opts.simple_layout, opts.gen_graph))


if __name__ == "__main__":
    main()
