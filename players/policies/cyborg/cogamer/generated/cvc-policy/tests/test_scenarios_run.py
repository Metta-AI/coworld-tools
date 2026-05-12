"""Tests for Run — typed view over a run folder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cvc_policy.scenarios._run import Run


def _write_run(path: Path, events: list[dict], result: dict | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "events.json").write_text(json.dumps(events))
    (path / "result.json").write_text(json.dumps(result or {"run_id": path.name}))


def test_run_loads_events_and_result(tmp_path: Path) -> None:
    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action", "payload": {"role": "miner"}},
        {"step": 1, "agent": 0, "stream": "py", "type": "action", "payload": {"role": "miner"}},
    ]
    _write_run(tmp_path, events, {"run_id": "x", "status": "passed"})
    run = Run(tmp_path)
    assert len(run.events) == 2
    assert run.result["status"] == "passed"
    assert run.run_dir == tmp_path


def test_events_of_type(tmp_path: Path) -> None:
    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action", "payload": {}},
        {"step": 1, "agent": 0, "stream": "py", "type": "target", "payload": {}},
        {"step": 2, "agent": 0, "stream": "py", "type": "action", "payload": {}},
    ]
    _write_run(tmp_path, events)
    run = Run(tmp_path)
    assert len(run.events_of_type("action")) == 2
    assert len(run.events_of_type("target")) == 1
    assert run.events_of_type("missing") == []


def test_events_for_agent(tmp_path: Path) -> None:
    events = [
        {"step": 0, "agent": 0, "stream": "py", "type": "action", "payload": {}},
        {"step": 0, "agent": 1, "stream": "py", "type": "action", "payload": {}},
        {"step": 1, "agent": None, "stream": "py", "type": "note", "payload": {}},
    ]
    _write_run(tmp_path, events)
    run = Run(tmp_path)
    assert len(run.events_for_agent(0)) == 1
    assert len(run.events_for_agent(1)) == 1
    assert run.events_for_agent(99) == []


def test_first_target_for_agent(tmp_path: Path) -> None:
    events = [
        {"step": 3, "agent": 0, "stream": "py", "type": "action", "payload": {}},
        {
            "step": 5,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        },
        {
            "step": 6,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "oxygen_extractor", "pos": [2, 2]},
        },
    ]
    _write_run(tmp_path, events)
    run = Run(tmp_path)
    first = run.first_target_for_agent(0)
    assert first is not None
    assert first["payload"]["kind"] == "carbon_extractor"
    assert run.first_target_for_agent(99) is None


def test_mining_trips_segments_by_target(tmp_path: Path) -> None:
    # Trip 1: target (4,4), 4 mine bumps; trip 2: target (2,2), 2 bumps.
    events = [
        {
            "step": 1,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "carbon_extractor", "pos": [4, 4]},
        },
        {
            "step": 2,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_carbon"},
        },
        {
            "step": 3,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_carbon"},
        },
        {
            "step": 4,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_carbon"},
        },
        {
            "step": 5,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_carbon"},
        },
        {
            "step": 6,
            "agent": 0,
            "stream": "py",
            "type": "target",
            "payload": {"kind": "oxygen_extractor", "pos": [2, 2]},
        },
        {
            "step": 7,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_oxygen"},
        },
        {
            "step": 8,
            "agent": 0,
            "stream": "py",
            "type": "action",
            "payload": {"role": "miner", "summary": "mine_oxygen"},
        },
    ]
    _write_run(tmp_path, events)
    run = Run(tmp_path)
    trips = run.mining_trips(0)
    assert len(trips) == 2
    assert trips[0].target_pos == (4, 4)
    assert trips[0].bump_count == 4
    assert trips[0].start_step == 1
    assert trips[0].end_step == 5
    assert trips[1].target_pos == (2, 2)
    assert trips[1].bump_count == 2


def test_missing_events_json_raises(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text("{}")
    with pytest.raises(FileNotFoundError):
        Run(tmp_path)
