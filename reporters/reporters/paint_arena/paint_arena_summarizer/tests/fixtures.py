"""Synthetic PaintArena episode fixtures used across the test suite.

Each helper returns a deep-copyable dict; tests are free to mutate the result.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def make_manifest() -> dict[str, Any]:
    return deepcopy(
        {
            "game": {
                "name": "paintarena",
                "version": "0.1.5",
                "results_schema": {},
            },
            "variants": [
                {
                    "id": "default",
                    "name": "Default",
                    "game_config": {
                        "width": 12,
                        "height": 8,
                        "max_ticks": 100,
                        "tick_rate": 5,
                        "players": [
                            {"name": "Sweep Painter 1"},
                            {"name": "Sweep Painter 2"},
                        ],
                    },
                },
                {
                    "id": "small",
                    "name": "Small",
                    "game_config": {
                        "width": 4,
                        "height": 4,
                        "max_ticks": 20,
                        "tick_rate": 5,
                        "players": [{"name": "A"}, {"name": "B"}],
                    },
                },
            ],
        }
    )


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
