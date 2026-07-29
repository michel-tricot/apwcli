"""apwcli entry point."""

import argparse
import sys
from collections.abc import Sequence

from apwlib import greet

from apwcli import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apwcli", description="Command-line interface for apwlib."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    greet_parser = subparsers.add_parser("greet", help="Print a greeting.")
    greet_parser.add_argument("name", help="Name to greet.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "greet":
        try:
            print(greet(args.name))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
