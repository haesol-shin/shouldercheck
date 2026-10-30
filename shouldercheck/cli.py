"""Command line entry point for `shck`."""

import argparse

from shouldercheck import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shck", description=__doc__)
    parser.add_argument("--version", action="version", version=f"shck {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
