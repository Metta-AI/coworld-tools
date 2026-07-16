"""distance.py — Canonical distance metrics + env-truth metric tags.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_distance.py``).

This module centralizes the distance helpers used across the original swgy
foundations. Keeping the metrics in one place avoids drift between
callers and makes mission-specific range assumptions explicit.

This module is the single source of truth. Two purposes:

* Provide the four metric callables in one place so callers can name
  the metric explicitly at the call site (``manhattan(a, b)``,
  ``euclidean(a, b)``) instead of hand-rolling ``abs(a[0]-b[0]) +
  abs(a[1]-b[1])``.

* Document the mission metric for known game ranges as named
  constants, so callers can reference a shared source of truth.
"""

from __future__ import annotations

from math import sqrt

Coordinate = tuple[int, int]


# ---------------------------------------------------------------------
# Metric callables
# ---------------------------------------------------------------------

def manhattan(a: Coordinate, b: Coordinate) -> int:
    """L1 grid distance — axis-aligned step count on a 4-connected grid.

    Use for: 4-connected BFS heuristics, navigation cost estimates,
    most "how far is this cell" comparisons in scripted policies.
    """
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def chebyshev(a: Coordinate, b: Coordinate) -> int:
    """L∞ grid distance — step count on an 8-connected grid; equivalently
    "are these cells within N king-moves of each other."

    NOT for bump-target arrival on a 4-connected env (bumps fire only
    from orthogonal neighbors — Manhattan=1 — and diagonals at Cheb=1 /
    Manhattan=2 cannot bump on the same tick; use :func:`manhattan`
    instead). NOT for lane / territory / AOE radii when the game
    defines those as Euclidean disks (use :func:`euclidean_sq`).
    Legitimate uses are narrow: observation-window bounding boxes
    (the env's 13x13 obs is enclosed by Cheb<=6) and policy-side
    territorial coverage footprints that are intentionally square.
    """
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def euclidean_sq(a: Coordinate, b: Coordinate) -> int:
    """Squared Euclidean distance. Integer-valued, so range comparisons
    can be done as ``euclidean_sq(a, b) <= R * R`` without float jitter.

    Prefer this over ``euclidean`` for in-range gates — it avoids both
    the sqrt cost and the chance of off-by-epsilon edge cases when R
    happens to be exactly the boundary.
    """
    dr = a[0] - b[0]
    dc = a[1] - b[1]
    return dr * dr + dc * dc


def euclidean(a: Coordinate, b: Coordinate) -> float:
    """L2 distance as a float. Use only when you need the actual length
    (e.g., direction unit vectors). For "is X within R cells" gates,
    prefer ``euclidean_sq(a, b) <= R*R``.
    """
    return sqrt(euclidean_sq(a, b))


# ---------------------------------------------------------------------
# Env-truth metric annotations (worked example)
# ---------------------------------------------------------------------
#
# Pattern: when a game rule has a specific metric, record it as a named
# constant so call sites reference a shared source of truth instead of
# each guessing. The three constants below are the annotations for the
# origin game (Cogs vs Clips); replace or extend them for your game.

# The junction-alignment-closure gate uses Euclidean distance from a
# junction to the network's existing aligned cells.
JUNCTION_ALIGN_RANGE_METRIC = "euclidean"

# Source: env is 4-connected (move_north/south/east/west only — no
# diagonal moves), so a bump fires only when the agent is at one of
# the 4 orthogonal neighbors of the target cell, i.e., Manhattan == 1.
# Diagonals (Cheb=1, Manhattan=2) cannot fire a bump on the same tick;
# they need one more step first. Treating Cheb<=1 as "adjacent enough
# to bump" advances arrival predicates a tick early.
BUMP_TARGET_RANGE_METRIC = "manhattan"

# Source: foundation stack (BFS, A* heuristics) — 4-connected grid.
NAV_HEURISTIC_METRIC = "manhattan"
