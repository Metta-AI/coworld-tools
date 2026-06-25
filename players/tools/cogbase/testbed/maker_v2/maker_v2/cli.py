"""CLI scaffold for ``maker_v2``.

This is intentionally a stub. The argument surface is sketched so callers can
see the intended shape, but no generation behavior is implemented yet. The
command always exits with a clear "not yet implemented" message.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


_NOT_IMPLEMENTED_MESSAGE = (
    "maker_v2 is a fresh scaffold and does not yet implement agent "
    "generation. See docs/designs/maker_v2_design.md for the intended "
    "direction. While maker_v2 is being built, the deprecated maker_v1 "
    "toolkit (testbed/maker_v1/) is still runnable for short-term "
    "continuity."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maker_v2",
        description=(
            "Canonical Cogbase agent-making toolkit (scaffold). Consumes a "
            "guide_v1 bundle and is intended to produce a runnable baseline "
            "agent. No generation is implemented yet."
        ),
    )
    parser.add_argument(
        "guide_dir",
        type=Path,
        help="Path to a guide_v1 output bundle (must contain guide_contract.json).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write generated artifacts. Defaults to ./output/<guide-dir-name>.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    print(_NOT_IMPLEMENTED_MESSAGE, file=sys.stderr)
    return 2
