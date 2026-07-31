"""Tests for the MettaScope replay decoder."""

from __future__ import annotations

import json
import zlib

from episode_analysis.mettascope import (
    agent_objects,
    is_delta,
    load_replay,
    materialize,
    max_steps_of,
    to_event_rows,
    value_at,
)


def _replay() -> dict:
    return {
        "version": 4,
        "action_names": ["noop", "move_north"],
        "item_names": [],
        "type_names": ["agent", "wall"],
        "map_size": [6, 4],
        "num_agents": 2,
        "max_steps": 5,
        "objects": [
            {
                "id": 1,
                "type_name": "agent",
                "agent_id": 0,
                # delta-encoded: moves at steps 2 and 4
                "location": [[0, [1, 1]], [2, [2, 1]], [4, [3, 1]]],
                "total_reward": [[0, 0.0], [3, 1.5]],
                "alive": True,
            },
            {
                "id": 2,
                "type_name": "agent",
                "agent_id": 1,
                "location": [5, 3],  # constant location (plain value)
                "total_reward": 0.0,
                "alive": [[0, True], [4, False]],
            },
            {"id": 3, "type_name": "wall", "location": [0, 0]},
        ],
        "infos": {},
    }


def test_load_replay_sniffs_zlib_and_plain():
    raw = json.dumps(_replay()).encode()
    assert load_replay(raw)["version"] == 4
    assert load_replay(zlib.compress(raw))["version"] == 4


def test_is_delta_and_value_at():
    field = [[0, 10], [3, 20], [7, 30]]
    assert is_delta(field)
    assert not is_delta(42)
    assert not is_delta([1, 2])
    assert value_at(field, 0) == 10
    assert value_at(field, 2) == 10
    assert value_at(field, 3) == 20
    assert value_at(field, 100) == 30
    assert value_at("constant", 5) == "constant"


def test_materialize_expands_full_series():
    field = [[1, "a"], [3, "b"]]
    assert materialize(field, 4) == [None, "a", "a", "b", "b"]
    assert materialize("x", 2) == ["x", "x", "x"]


def test_value_predicate_disambiguates_list_values():
    # A constant whose VALUE is a list of [int, x] pairs looks like a delta
    # series; a predicate that rejects the inner values keeps it whole.
    inventory = [[0, 2], [1, 5]]  # item 0 x2, item 1 x5 — NOT a time series
    looks_like = materialize(inventory, 1)
    assert looks_like == [2, 5]  # misread without a predicate
    kept = materialize(inventory, 1, value_predicate=lambda v: isinstance(v, list))
    assert kept == [inventory, inventory]


def test_max_steps_of_both_dialects():
    assert max_steps_of({"max_steps": 7}) == 7
    assert max_steps_of({"infos": {"attributes": {"steps": 9}}}) == 9


def test_agent_objects_sorted_and_typed():
    agents = agent_objects(_replay())
    assert [a for a, _ in agents] == [0, 1]


def test_to_event_rows_canonical_shape():
    rows = to_event_rows(_replay(), location_order="xy")
    # One episode row.
    episode = [r for r in rows if r["key"] == "episode"]
    assert len(episode) == 1 and episode[0]["player"] == -1
    assert json.loads(episode[0]["value"]) == {"max_steps": 5, "num_agents": 2}
    # Agent 0: three position changes at ts 0/2/4.
    pos0 = [r for r in rows if r["key"] == "position" and r["player"] == 0]
    assert [r["ts"] for r in pos0] == [0, 2, 4]
    assert json.loads(pos0[1]["value"]) == {"x": 2, "y": 1}
    # Agent 1: one position (constant), one death at ts 4.
    pos1 = [r for r in rows if r["key"] == "position" and r["player"] == 1]
    assert len(pos1) == 1 and json.loads(pos1[0]["value"]) == {"x": 5, "y": 3}
    deaths = [r for r in rows if r["key"] == "death"]
    assert [(r["ts"], r["player"]) for r in deaths] == [(4, 1)]
    # Agent 0: one reward change carrying delta + total.
    rewards = [r for r in rows if r["key"] == "reward"]
    assert len(rewards) == 1
    assert json.loads(rewards[0]["value"]) == {"delta": 1.5, "total": 1.5}
    # Rows sorted by (ts, player, key); values are JSON strings.
    assert rows == sorted(rows, key=lambda r: (r["ts"], r["player"], r["key"]))
    assert all(isinstance(r["value"], str) for r in rows)


def test_to_event_rows_rc_order():
    rows = to_event_rows(_replay(), location_order="rc")
    pos0 = [r for r in rows if r["key"] == "position" and r["player"] == 0]
    assert json.loads(pos0[0]["value"]) == {"x": 1, "y": 1}
    assert json.loads(pos0[1]["value"]) == {"x": 1, "y": 2}  # loc [2,1] -> row 2
