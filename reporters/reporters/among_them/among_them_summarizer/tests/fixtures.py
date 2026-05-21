"""Synthetic Among Them episode fixtures used across the test suite.

Phase 2 fixtures cover the aggregates path: results JSON shapes for the
three verdicts (imposter / crewmate / draw), metadata, and a minimal
valid `.bitreplay` header (magic + version + game-name + version +
timestamp + configJson). Phase 3 will extend `make_replay_bytes` to
also emit join / leave / input / hash records.

Each helper returns a deep-copyable / mutable value; tests are free to
mutate the result.
"""

from __future__ import annotations

import json
import struct
from copy import deepcopy
from typing import Any


# ---------- binary replay header synthesis ----------


def _u16_str(s: str) -> bytes:
    """Encode a length-prefixed UTF-8 string in the bitreplay format
    (u16 little-endian length + bytes)."""
    raw = s.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def make_replay_bytes(
    *,
    config: dict[str, Any] | None = None,
    game_name: str = "among_them",
    game_version: str = "1",
    format_version: int = 3,
    timestamp_ms: int = 0,
    magic: bytes = b"BITWORLD",
) -> bytes:
    """Build a minimal-but-valid bitreplay header (no records).

    Layout per `among_them/replays.nim:148-161` and
    `among_them/sim.nim:9-18`:

        magic (8B) | format_version (u16) | game_name (str) |
        game_version (str) | timestamp_ms (u64) | config_json (str)

    Tests can override any field to exercise the parser's rejection
    paths (magic mismatch, version mismatch, etc.).
    """
    cfg = config if config is not None else make_game_config()
    payload = bytearray(magic)
    payload += struct.pack("<H", format_version)
    payload += _u16_str(game_name)
    payload += _u16_str(game_version)
    payload += struct.pack("<Q", timestamp_ms)
    payload += _u16_str(json.dumps(cfg))
    return bytes(payload)


def make_game_config(**overrides: Any) -> dict[str, Any]:
    """Default config matching the manifest's `default` variant."""
    base = {
        "seed": 679961,
        "minPlayers": 8,
        "imposterCount": 2,
        "autoImposterCount": False,
        "tasksPerPlayer": 8,
        "killCooldownTicks": 900,
        "voteTimerTicks": 6000,
        "maxTicks": 10000,
        "mapPath": "map.json",
    }
    base.update(overrides)
    return base


# ---------- results JSON helpers ----------


def _zeros(n: int) -> list[int]:
    return [0] * n


def make_results(
    *,
    slots: int = 8,
    imposter_slots: tuple[int, ...] | None = None,
    winner_side: str = "Crewmate",
    tasks_per_player: int = 8,
    extra_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a results JSON for a normal episode.

    `winner_side`: "Crewmate" | "Imposter" | "Draw".

    For "Crewmate": every crewmate has `win=True`, every imposter
    `win=False`, every crewmate finished `tasks_per_player` tasks
    (i.e. crew-by-tasks win — the reporter cannot distinguish that
    from crew-by-ejection, per design Friction §1).

    For "Imposter": every imposter `win=True`, every crewmate `win=False`,
    crewmate tasks vary so some look "killed" via likely_dead inference.

    For "Draw": every `win=False`.
    """
    if imposter_slots is None:
        # Default: first two slots when there's room, else first slot only.
        imposter_slots = (0, 1) if slots >= 4 else (0,)
    if any(s < 0 or s >= slots for s in imposter_slots):
        raise ValueError("imposter_slots out of range")
    imposter = [1 if i in imposter_slots else 0 for i in range(slots)]
    crew = [1 - x for x in imposter]
    if winner_side == "Crewmate":
        win = [bool(crew[i]) for i in range(slots)]
        tasks = [tasks_per_player if crew[i] else 0 for i in range(slots)]
        kills = [1 if imposter[i] else 0 for i in range(slots)]
    elif winner_side == "Imposter":
        win = [bool(imposter[i]) for i in range(slots)]
        # Crew did some, but not all, tasks before getting killed.
        tasks = [tasks_per_player // 2 if crew[i] else 0 for i in range(slots)]
        kills = [3 if imposter[i] else 0 for i in range(slots)]
    elif winner_side == "Draw":
        win = [False] * slots
        tasks = [tasks_per_player - 1 if crew[i] else 0 for i in range(slots)]
        kills = [1 if imposter[i] else 0 for i in range(slots)]
    else:
        raise ValueError(f"unknown winner_side: {winner_side!r}")

    out: dict[str, Any] = {
        "names": [f"player-{i}" for i in range(slots)],
        "scores": [
            float(0) for _ in range(slots)
        ],  # tournament reward; not load-bearing here
        "win": win,
        "tasks": tasks,
        "kills": kills,
        "imposter": imposter,
        "crew": crew,
        "vote_players": _zeros(slots),
        "vote_skip": _zeros(slots),
        "vote_timeout": _zeros(slots),
    }
    if extra_overrides:
        out.update(extra_overrides)
    return out


def make_results_imposter_win(slots: int = 8) -> dict[str, Any]:
    return make_results(slots=slots, winner_side="Imposter")


def make_results_crewmate_win(slots: int = 8) -> dict[str, Any]:
    return make_results(slots=slots, winner_side="Crewmate")


def make_results_draw(slots: int = 8) -> dict[str, Any]:
    return make_results(slots=slots, winner_side="Draw")


def make_results_meetings(
    *,
    slots: int = 8,
    per_slot_votes: list[tuple[int, int, int]],
) -> dict[str, Any]:
    """Build a results JSON with known per-slot vote tallies.

    `per_slot_votes[i] = (vote_players, vote_skip, vote_timeout)`. Used
    for testing `estimate_meetings`.
    """
    if len(per_slot_votes) != slots:
        raise ValueError("per_slot_votes length must match slots")
    res = make_results(slots=slots, winner_side="Crewmate")
    res["vote_players"] = [vp for vp, _, _ in per_slot_votes]
    res["vote_skip"] = [vs for _, vs, _ in per_slot_votes]
    res["vote_timeout"] = [vt for _, _, vt in per_slot_votes]
    return res


# ---------- episode metadata ----------


def make_metadata(
    *,
    slots: int = 8,
    variant_id: str = "default",
    episode_id: str = "ep_abc123",
    policy_names: list[str | None] | None = None,
    duration_seconds: float = 412.5,
) -> dict[str, Any]:
    if policy_names is None:
        policy_names = [f"policy-v{i}" for i in range(slots)]
    if len(policy_names) != slots:
        raise ValueError("policy_names length must match slots")
    return deepcopy(
        {
            "episode_id": episode_id,
            "variant_id": variant_id,
            "started_at": "2026-05-18T10:23:45Z",
            "ended_at": "2026-05-18T10:30:38Z",
            "duration_seconds": duration_seconds,
            "players": [
                {
                    "slot": i,
                    "policy_version_id": f"polver_{i}" if policy_names[i] else None,
                    "policy_name": policy_names[i],
                }
                for i in range(slots)
            ],
            "league_id": None,
            "division_id": None,
            "round_id": None,
            "pool_id": None,
            "tags": {},
        }
    )
