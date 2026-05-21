"""Synthetic PaintArena episode fixtures used across the test suite.

Each helper returns a deep-copyable dict; tests are free to mutate the result.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _empty_owners(width: int, height: int) -> list[int]:
    return [-1] * (width * height)


def _set_owner(owners: list[int], x: int, y: int, slot: int, width: int) -> list[int]:
    owners = list(owners)
    owners[y * width + x] = slot
    return owners


def _frame(tick: int, positions: list[list[int]], owners: list[int]) -> dict[str, Any]:
    """A frame shape mirroring what the PaintArena game server writes
    (see paintarena/game/server.py::_snapshot). The reporter only reads
    `tick`, `positions`, and `tile_owners`; the extra keys are present so
    fixtures resemble real replays."""
    return {
        "type": "state",
        "tick": tick,
        "positions": [list(p) for p in positions],
        "tile_owners": list(owners),
        "scores": [0, 0],
        "player_names": ["Sweep Painter 1", "Sweep Painter 2"],
        "width": 12,
        "height": 8,
        "max_ticks": 100,
        "started": True,
        "paused": False,
        "tick_rate": 5,
        "done": False,
    }


def _build_scripted_frames(width: int = 12, height: int = 8) -> list[dict[str, Any]]:
    """Hand-scripted sequence designed to produce a clear back-and-forth at
    tile (5, 3) and a stretch of proximity events as the two agents converge.

    Tick layout:
      0..4   — both agents in opposite corners, no proximity.
      5..18  — both agents walk toward (5, 3) along their own paths,
                painting their trail; no contact yet.
      19..28 — agents oscillate around (5, 3): slot 0 paints, slot 1 takes
                it, slot 0 takes it back, slot 1 takes it back. Three
                painted->painted flips within an 8-tick span.
      29..34 — agents separate again; proximity events end.

    Positions are clamped to the grid (matching the real game's `_step`).
    """
    frames: list[dict[str, Any]] = []
    owners = _empty_owners(width, height)

    # Tick 0: starting corners, no painting yet.
    pos = [[0, 0], [width - 1, height - 1]]
    owners = _set_owner(owners, 0, 0, 0, width)
    owners = _set_owner(owners, width - 1, height - 1, 1, width)
    frames.append(_frame(1, pos, owners))

    # Ticks 2..18: walk toward (5, 3). Slot 0 moves right along y=0 then
    # down to (5, 3); slot 1 moves left along y=7 then up to (5, 4).
    slot0_path = [(x, 0) for x in range(1, 6)] + [(5, 1), (5, 2), (5, 3)]
    slot1_path = [(x, height - 1) for x in range(width - 2, 4, -1)] + [
        (5, 6),
        (5, 5),
        (5, 4),
    ]
    # Pad shorter path with stationary entries so both lists have the same
    # length (no agent should idle alone for ticks).
    path_len = max(len(slot0_path), len(slot1_path))
    while len(slot0_path) < path_len:
        slot0_path.append(slot0_path[-1])
    while len(slot1_path) < path_len:
        slot1_path.append(slot1_path[-1])

    tick = 1
    for s0, s1 in zip(slot0_path, slot1_path):
        tick += 1
        pos = [list(s0), list(s1)]
        owners = _set_owner(owners, s0[0], s0[1], 0, width)
        owners = _set_owner(owners, s1[0], s1[1], 1, width)
        frames.append(_frame(tick, pos, owners))

    # Now slot 0 is at (5, 3) and slot 1 is at (5, 4): Chebyshev distance 1.
    # Oscillate ownership of (5, 3):
    #   tick T+1: slot 1 steps onto (5, 3); slot 0 retreats to (5, 2). flip 1.
    #   tick T+2: slot 0 steps back onto (5, 3); slot 1 retreats to (5, 4). flip 2.
    #   tick T+3: slot 1 steps onto (5, 3); slot 0 retreats to (5, 2). flip 3.
    #   tick T+4: slot 0 steps back; slot 1 retreats. flip 4.
    oscillation = [
        ([5, 2], [5, 3]),
        ([5, 3], [5, 4]),
        ([5, 2], [5, 3]),
        ([5, 3], [5, 4]),
    ]
    for s0, s1 in oscillation:
        tick += 1
        pos = [s0, s1]
        owners = _set_owner(owners, s0[0], s0[1], 0, width)
        owners = _set_owner(owners, s1[0], s1[1], 1, width)
        frames.append(_frame(tick, pos, owners))

    # Separate again so proximity events stop.
    separation = [
        ([4, 2], [6, 4]),
        ([3, 2], [7, 4]),
        ([2, 2], [8, 4]),
        ([1, 2], [9, 4]),
    ]
    for s0, s1 in separation:
        tick += 1
        pos = [s0, s1]
        owners = _set_owner(owners, s0[0], s0[1], 0, width)
        owners = _set_owner(owners, s1[0], s1[1], 1, width)
        frames.append(_frame(tick, pos, owners))

    return frames


def make_replay(width: int = 12, height: int = 8) -> dict[str, Any]:
    """Synthetic PaintArena replay payload with a scripted frame sequence.

    Shape mirrors what the PaintArena game server writes
    (packages/coworld/.../paintarena/game/server.py::_replay_payload):
    `{config, player_names, frames, results}`. The reporter reads
    `config.{width,height}` and walks `frames` for proximity and
    back-and-forth highlights. The scripted sequence guarantees both a
    contested tile (5, 3) and a stretch of proximity events, so tests can
    assert specific counts.
    """
    return deepcopy(
        {
            "config": {
                "width": width,
                "height": height,
                "max_ticks": 100,
                "tick_rate": 5,
                "players": [
                    {"name": "Sweep Painter 1"},
                    {"name": "Sweep Painter 2"},
                ],
            },
            "player_names": ["Sweep Painter 1", "Sweep Painter 2"],
            "frames": _build_scripted_frames(width=width, height=height),
            "results": {},
        }
    )


def make_replay_no_frames(width: int = 12, height: int = 8) -> dict[str, Any]:
    """Replay with no frames — exercises the degenerate path where the
    reporter still has to produce a valid (but empty-content) parquet and an
    HTML page with no highlights."""
    payload = make_replay(width=width, height=height)
    payload["frames"] = []
    return payload


def make_metadata(variant_id: str = "default") -> dict[str, Any]:
    return deepcopy(
        {
            "episode_id": "ep_abc123",
            "variant_id": variant_id,
            "started_at": "2026-05-18T10:23:45Z",
            "ended_at": "2026-05-18T10:24:05Z",
            "duration_seconds": 19.4,
            "players": [
                {"slot": 0, "policy_version_id": "polver_1", "policy_name": "champion-v3"},
                {"slot": 1, "policy_version_id": "polver_2", "policy_name": "starter"},
            ],
            "league_id": None,
            "division_id": None,
            "round_id": None,
            "pool_id": None,
            "tags": {},
        }
    )


def make_results(painted: list[int], ticks: int = 100) -> dict[str, Any]:
    return {
        "scores": [float(x) for x in painted],
        "painted_tiles": list(painted),
        "ticks": ticks,
    }


def make_results_happy() -> dict[str, Any]:
    """Slot 0: 47 tiles, slot 1: 38 tiles on a 12x8 grid (96 total, 11 unpainted)."""
    return make_results([47, 38], ticks=100)


def make_results_zero_paint() -> dict[str, Any]:
    return make_results([0, 0], ticks=0)


def make_results_tie() -> dict[str, Any]:
    return make_results([42, 42], ticks=100)


def make_results_missing_field() -> dict[str, Any]:
    """Results JSON missing the required 'ticks' field."""
    return {
        "scores": [47.0, 38.0],
        "painted_tiles": [47, 38],
    }
