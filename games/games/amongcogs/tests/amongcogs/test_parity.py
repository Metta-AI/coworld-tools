from __future__ import annotations

import json
import struct

import pytest

from amongcogs.parity import (
    build_parity_report,
    format_summary,
    summarize_amongcogs_audit,
    summarize_bitworld_run,
)


def _audit_payload() -> dict:
    coverage_keys = (
        "tasks_completed_rate",
        "kills_rate",
        "reports_rate",
        "ejections_rate",
        "meeting_calls_rate",
        "meeting_skips_rate",
        "emergency_meeting_calls_rate",
        "sabotages_rate",
        "repairs_rate",
        "vents_used_rate",
        "admin_checks_rate",
        "camera_checks_rate",
        "comms_checks_rate",
        "lights_sabotages_rate",
            "oxygen_sabotages_rate",
            "reactor_sabotages_rate",
            "meeting_talk_actions_rate",
            "ballot_talk_actions_rate",
            "winner_declared_rate",
        )
    return {
        "episodes": 8,
        "completion_rate": 1.0,
        "coverage": {key: 1.0 for key in coverage_keys},
        "winners": {"crew": 3, "impostor": 5},
        "actions": {"meeting_talk_actions": 12, "ballot_talk_actions": 6},
        "steps": {"mean": 240.0},
        "sps": {"mean": 395.0},
    }


def _write_replay(path) -> None:
    config = {
        "minPlayers": 5,
        "imposterCount": 1,
        "tasksPerPlayer": 4,
        "voteTimerTicks": 1440,
        "maxTicks": 0,
    }
    payload = bytearray()
    payload += b"BITWORLD"
    payload += struct.pack("<H", 2)
    _write_replay_string(payload, "among_them")
    _write_replay_string(payload, "1")
    payload += struct.pack("<Q", 0)
    _write_replay_string(payload, json.dumps(config))
    for bot_id in range(5):
        payload += bytes([3])
        payload += struct.pack("<I", 0)
        payload += bytes([bot_id])
        _write_replay_string(payload, f"bot{bot_id}")
    payload += bytes([2])
    payload += struct.pack("<I", 41)
    payload += bytes([0, 32])
    payload += bytes([1])
    payload += struct.pack("<IQ", 1, 123)
    path.write_bytes(payload)


def _write_replay_string(payload: bytearray, value: str) -> None:
    encoded = value.encode()
    payload += struct.pack("<H", len(encoded))
    payload += encoded


def test_parity_report_passes_with_bitworld_and_amongcogs_evidence(tmp_path) -> None:
    replay_path = tmp_path / "replay.bit"
    _write_replay(replay_path)

    bitworld = summarize_bitworld_run(tmp_path, replay_path)
    amongcogs = summarize_amongcogs_audit(_audit_payload())
    report = build_parity_report(bitworld, amongcogs)

    assert report.passed is True
    assert "passed=True" in format_summary(report)


def test_parity_report_fails_when_amongcogs_surface_is_missing(tmp_path) -> None:
    replay_path = tmp_path / "replay.bit"
    _write_replay(replay_path)
    payload = _audit_payload()
    payload["coverage"]["meeting_talk_actions_rate"] = 0.0

    report = build_parity_report(summarize_bitworld_run(tmp_path, replay_path), summarize_amongcogs_audit(payload))

    assert report.passed is False
    assert "amongcogs.coverage.meeting_talk_actions_rate" in format_summary(report)


def test_parity_audit_requires_structured_fields() -> None:
    payload = _audit_payload()
    del payload["coverage"]

    with pytest.raises(KeyError):
        summarize_amongcogs_audit(json.loads(json.dumps(payload)))
