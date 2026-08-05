"""Opt-in reference simulators for offline testing and benchmarking.

Today: :mod:`.inertia` — an integer fixed-point, momentum-carrying 2D
movement engine (:class:`Engine`/:class:`Body`/:class:`InertiaParams`),
byte-faithful to the origin engine at the default parameters. Use it as a
physics oracle: drive a follower closed-loop through it in tests, benchmark
nav parameter variants, or regression-pin movement behavior — all without a
game server.

This subpackage is stdlib-only (the grid is duck-typed via
:class:`~.inertia.Walkability`; ``nav_mesh.NavGrid`` satisfies it) and is not
re-exported from ``players.player_sdk``. Origin: extracted from Ron
Dahlgren's (swgy) agent libraries (swgy-crewrift,
``swgy_tools.navbench.enginesim``).
"""

from .inertia import Body, Engine, InertiaParams, Walkability

__all__ = ["Body", "Engine", "InertiaParams", "Walkability"]
