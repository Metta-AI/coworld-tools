"""Standalone Overcogged package."""

from __future__ import annotations

__all__ = ["OvercookedCoGame", "play"]


def __getattr__(name: str) -> object:
    if name == "OvercookedCoGame":
        from overcogged.game.game import OvercookedCoGame

        return OvercookedCoGame
    if name == "play":
        from overcogged.recipe import play

        return play
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
