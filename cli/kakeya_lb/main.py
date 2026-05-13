"""``kakeya-lb`` entrypoint dispatcher."""

from __future__ import annotations

import argparse
import sys

from cli.kakeya_lb.commands import init, schema_check, validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kakeya-lb",
        description=(
            "Local helper for Wang Hong leaderboard participants. "
            "Scaffold a harness, validate it, and check outputs against "
            "the official schemas."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init.add_subparser(subparsers)
    validate.add_subparser(subparsers)
    schema_check.add_subparser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
