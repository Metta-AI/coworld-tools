from __future__ import annotations

import sys

from cogames.cli.base import console
from cogames.cli.mission import list_variants, print_variant_graph
from mettagrid.cogame.game import get_game
from mettagrid.policy.loader import discover_and_register_policies

from werecog.cogame import register_game

_GAME_SWITCHING_COMMANDS = {"describe", "games", "mission", "missions", "play"}


def _patch_args(args: list[str]) -> list[str]:
    if not args:
        return args

    patched = list(args)
    command = patched[0]
    if command in _GAME_SWITCHING_COMMANDS and "--game" not in patched:
        patched[1:1] = ["--game", "werecog"]
    if command == "play" and not any(arg in {"-m", "--mission"} for arg in patched):
        patched[1:1] = ["--mission", "werecog"]
    return patched


def main() -> None:
    register_game()
    discover_and_register_policies("werecog")

    args = sys.argv[1:]
    if args[:1] == ["variants"]:
        if "--dependencies" in args:
            print_variant_graph(get_game("werecog"), console)
        else:
            list_variants("werecog")
        return

    from cogames.main import app

    app(args=_patch_args(args), prog_name="werecog")
