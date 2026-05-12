"""Tests for scenario assertion helpers."""

from __future__ import annotations

import json
from pathlib import Path

from cvc_policy.scenarios._run import Run
from cvc_policy.scenarios.assertions import (
    AssertResult,
    after_heavy_trip_switches_target,
    cap_discovered_by,
    has_action_event_per_agent,
    known_entities_at_least,
    mining_trips_efficient,
    no_crash,
    no_target_at,
)


def test_unused_assertion_helpers_are_gone() -> None:
    """map_coverage_at_least and extractors_known_at_least were dead
    weight backed by misleading fields; removed so they can't lock
    the events.json schema."""
    import cvc_policy.scenarios.assertions as mod

    assert not hasattr(mod, "map_coverage_at_least")
    assert not hasattr(mod, "extractors_known_at_least")


def _make_run(tmp: Path, events: list[dict], result: dict | None = None) -> Run:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "events.json").write_text(json.dumps(events))
    (tmp / "result.json").write_text(json.dumps(result or {}))
    return Run(tmp)


def test_assert_result_fields() -> None:
    r = AssertResult(name="x", passed=True, message="ok")
    assert r.passed
    assert r.failed_at_step is None


def test_no_crash_passes_when_no_error_event(tmp_path: Path) -> None:
    run = _make_run(
        tmp_path,
        [{"step": 0, "agent": 0, "stream": "py", "type": "action", "payload": {}}],
    )
    r = no_crash()(run)
    assert r.passed


def test_no_crash_fails_on_error_event(tmp_path: Path) -> None:
    run = _make_run(
        tmp_path,
        [{"step": 5, "agent": 0, "stream": "py", "type": "error", "payload": {"where": "x"}}],
    )
    r = no_crash()(run)
    assert not r.passed
    assert r.failed_at_step == 5


def test_has_action_event_per_agent_passes(tmp_path: Path) -> None:
    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action", "payload": {}},
        {"step": 0, "agent": 1, "stream": "py", "type": "action", "payload": {}},
    ]
    run = _make_run(tmp_path, events)
    r = has_action_event_per_agent(2)(run)
    assert r.passed


def test_has_action_event_per_agent_fails_when_missing(tmp_path: Path) -> None:
    events = [{"step": 0, "agent": 0, "stream": "py", "type": "action", "payload": {}}]
    run = _make_run(tmp_path, events)
    r = has_action_event_per_agent(2)(run)
    assert not r.passed
    assert "agent 1" in r.message


def test_cap_discovered_by_passes(tmp_path: Path) -> None:
    events = [
        {
            "step": 12,
            "agent": 0,
            "stream": "py",
            "type": "cap_discovered",
            "payload": {"gear_sig": ["miner"], "cap": 40},
        }
    ]
    run = _make_run(tmp_path, events)
    r = cap_discovered_by(agent=0, gear_sig=("miner",), expected_cap=40, by_step=55)(run)
    assert r.passed


def test_cap_discovered_by_fails_when_too_late(tmp_path: Path) -> None:
    events = [
        {
            "step": 99,
            "agent": 0,
            "stream": "py",
            "type": "cap_discovered",
            "payload": {"gear_sig": ["miner"], "cap": 40},
        }
    ]
    run = _make_run(tmp_path, events)
    r = cap_discovered_by(agent=0, gear_sig=("miner",), expected_cap=40, by_step=55)(run)
    assert not r.passed


def test_cap_discovered_by_fails_when_missing(tmp_path: Path) -> None:
    run = _make_run(tmp_path, [])
    r = cap_discovered_by(agent=0, gear_sig=("miner",), expected_cap=40, by_step=55)(run)
    assert not r.passed


def test_no_target_at_passes(tmp_path: Path) -> None:
    events = [
        {
            "step": 1,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        }
    ]
    run = _make_run(tmp_path, events)
    r = no_target_at((9, 9))(run)
    assert r.passed


def test_no_target_at_fails(tmp_path: Path) -> None:
    events = [
        {
            "step": 3,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [9, 9]},
        }
    ]
    run = _make_run(tmp_path, events)
    r = no_target_at((9, 9))(run)
    assert not r.passed
    assert r.failed_at_step == 3


def test_mining_trips_efficient_passes(tmp_path: Path) -> None:
    # cap=40, extract_amount=10 → 4 bumps expected per post-discovery trip.
    events = [
        {
            "step": 1,
            "agent": 0,
            "stream": "py",
            "type": "cap_discovered",
            "payload": {"gear_sig": ["miner"], "cap": 40},
        },
        {
            "step": 2,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        },
        *[
            {
                "step": 3 + i,
                "agent": 0,
                "stream": "py",
                "type": "action",
                "payload": {"role": "miner", "summary": "mine_carbon"},
            }
            for i in range(4)
        ],
    ]
    run = _make_run(tmp_path, events)
    r = mining_trips_efficient(agent=0, max_bumps_per_trip=4)(run)
    assert r.passed


def test_mining_trips_efficient_fails_on_wasted_bumps(tmp_path: Path) -> None:
    events = [
        {
            "step": 1,
            "agent": 0,
            "stream": "py",
            "type": "cap_discovered",
            "payload": {"gear_sig": ["miner"], "cap": 40},
        },
        {
            "step": 2,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        },
        *[
            {
                "step": 3 + i,
                "agent": 0,
                "stream": "py",
                "type": "action",
                "payload": {"role": "miner", "summary": "mine_carbon"},
            }
            for i in range(6)  # 2 bumps wasted
        ],
    ]
    run = _make_run(tmp_path, events)
    r = mining_trips_efficient(agent=0, max_bumps_per_trip=4)(run)
    assert not r.passed


def test_after_heavy_trip_switches_target_passes(tmp_path: Path) -> None:
    events = [
        {
            "step": 1,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        },
        *[
            {
                "step": 2 + i,
                "agent": 0,
                "stream": "py",
                "type": "action",
                "payload": {"role": "miner", "summary": "mine_carbon"},
            }
            for i in range(30)
        ],
        {
            "step": 40,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "oxygen_extractor", "pos": [9, 9]},
        },
        {
            "step": 41,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_oxygen"},
        },
    ]
    run = _make_run(tmp_path, events)
    r = after_heavy_trip_switches_target(agent=0, heavy_threshold=25)(run)
    assert r.passed


def test_after_heavy_trip_switches_target_fails(tmp_path: Path) -> None:
    events = [
        {
            "step": 1,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        },
        *[
            {
                "step": 2 + i,
                "agent": 0,
                "stream": "py",
                "type": "action",
                "payload": {"role": "miner", "summary": "mine_carbon"},
            }
            for i in range(30)
        ],
        # non-extractor target to close the trip, then return to same spot
        {
            "step": 40,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "hub", "pos": [0, 0]},
        },
        {
            "step": 50,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        },
        {
            "step": 51,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_carbon"},
        },
    ]
    run = _make_run(tmp_path, events)
    r = after_heavy_trip_switches_target(agent=0, heavy_threshold=25)(run)
    assert not r.passed


# --- Extra coverage paths -------------------------------------------


def test_cap_discovered_by_no_matching_events(tmp_path: Path) -> None:
    run = _make_run(tmp_path, [])
    r = cap_discovered_by(agent=0, gear_sig=("miner",), expected_cap=4, by_step=100)(run)
    assert not r.passed
    assert "no cap_discovered" in r.message


def test_cap_discovered_by_wrong_agent_or_sig(tmp_path: Path) -> None:
    events = [
        {"step": 5, "agent": 1, "stream": "py", "type": "cap_discovered",
         "payload": {"gear_sig": ["miner"], "cap": 4}},
        {"step": 6, "agent": 0, "stream": "py", "type": "cap_discovered",
         "payload": {"gear_sig": ["scout"], "cap": 4}},
    ]
    run = _make_run(tmp_path, events)
    r = cap_discovered_by(agent=0, gear_sig=("miner",), expected_cap=4, by_step=100)(run)
    assert not r.passed


def test_cap_discovered_by_cap_mismatch(tmp_path: Path) -> None:
    events = [
        {"step": 5, "agent": 0, "stream": "py", "type": "cap_discovered",
         "payload": {"gear_sig": ["miner"], "cap": 7}},
    ]
    run = _make_run(tmp_path, events)
    r = cap_discovered_by(agent=0, gear_sig=("miner",), expected_cap=4, by_step=100)(run)
    assert not r.passed
    assert "cap mismatch" in r.message


def test_mining_trips_efficient_no_discovery(tmp_path: Path) -> None:
    run = _make_run(tmp_path, [])
    r = mining_trips_efficient(agent=0, max_bumps_per_trip=3)(run)
    assert not r.passed
    assert "no cap_discovered" in r.message


def test_mining_trips_efficient_no_post_trips(tmp_path: Path) -> None:
    events = [
        {"step": 100, "agent": 0, "stream": "py", "type": "cap_discovered",
         "payload": {"gear_sig": ["miner"], "cap": 4}},
    ]
    run = _make_run(tmp_path, events)
    r = mining_trips_efficient(agent=0, max_bumps_per_trip=3)(run)
    assert not r.passed
    assert "no mining trips" in r.message


def test_known_entities_at_least_none(tmp_path: Path) -> None:
    run = _make_run(tmp_path, [])
    r = known_entities_at_least(agent=0, minimum=1)(run)
    assert not r.passed
    assert "no world_model_summary" in r.message


def test_known_entities_at_least_passes(tmp_path: Path) -> None:
    events = [
        {"step": 10, "agent": 0, "stream": "py", "type": "world_model_summary",
         "payload": {"known_entities": 5}},
    ]
    run = _make_run(tmp_path, events)
    r = known_entities_at_least(agent=0, minimum=3)(run)
    assert r.passed


def test_known_entities_at_least_fails(tmp_path: Path) -> None:
    events = [
        {"step": 10, "agent": 0, "stream": "py", "type": "world_model_summary",
         "payload": {"known_entities": 2}},
    ]
    run = _make_run(tmp_path, events)
    r = known_entities_at_least(agent=0, minimum=5)(run)
    assert not r.passed
