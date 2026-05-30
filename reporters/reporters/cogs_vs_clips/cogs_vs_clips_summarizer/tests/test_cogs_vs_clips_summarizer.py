from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import cogs_vs_clips_fixtures as fixtures
import cogs_vs_clips_summarizer as cvc


_EXPECTED_ENTRIES = {
    "manifest.json",
    "summary.md",
    "behavior_summary.json",
    "trace.jsonl",
    "events.parquet",
}


def _models() -> tuple[
    cvc.CogsVsClipsResults,
    cvc.EpisodeMetadata,
    cvc.CogsVsClipsReplay,
]:
    return (
        cvc.CogsVsClipsResults.model_validate(fixtures.make_results()),
        cvc.EpisodeMetadata.model_validate(fixtures.make_metadata()),
        cvc.CogsVsClipsReplay.model_validate(fixtures.make_replay()),
    )


def _extract(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def _build_zip() -> bytes:
    results, metadata, replay = _models()
    return cvc.build_zip_bytes(results, metadata, replay)


def test_build_trace_records_decodes_compact_replay_sequences() -> None:
    results, metadata, replay = _models()
    records = cvc.build_trace_records(results, metadata, replay)

    assert len(records) == 8
    alpha = [record for record in records if record.agent_id == 0]
    assert [record.location for record in alpha] == [
        [1, 1],
        [2, 1],
        [2, 1],
        [2, 2],
    ]
    assert [record.action_name for record in alpha] == [
        "noop",
        "move_east",
        "move_east",
        "move_south",
    ]
    assert alpha[2].inventory == {"ore": 1.0, "heart": 1.0}
    assert alpha[-1].total_reward == 1.5

    beta = [record for record in records if record.agent_id == 1]
    assert {tuple(record.location or []) for record in beta} == {(6, 5)}
    assert {record.policy_name for record in beta} == {"beta:v2"}
    assert {record.inventory["gear"] for record in beta} == {2.0}


def test_build_zip_declares_report_targets() -> None:
    files = _extract(_build_zip())
    assert set(files) == _EXPECTED_ENTRIES

    manifest = json.loads(files["manifest.json"])
    assert manifest == {
        "reporter_id": "cogs-vs-clips-summarizer",
        "render": "summary.md",
        "event_log": "events.parquet",
        "trace": "trace.jsonl",
    }
    assert "alpha:v1" in files["summary.md"].decode("utf-8")


def test_behavior_summary_aggregates_agent_movement_and_actions() -> None:
    summary = json.loads(_extract(_build_zip())["behavior_summary.json"])

    assert summary["episode_id"] == "ep_cvc_001"
    assert summary["mission"] == "machina_1"
    assert summary["scores"] == [1.5, 0.25]
    assert summary["game_stats"] == {"clips/aligned.junction.held": 2.0}

    alpha = summary["agents"][0]
    assert alpha["agent_id"] == 0
    assert alpha["movement_steps"] == 2
    assert alpha["max_idle_streak"] == 1
    assert alpha["visited_tiles"] == 3
    assert alpha["action_counts"] == {
        "move_east": 2,
        "move_south": 1,
        "noop": 1,
    }
    assert alpha["final_inventory"] == {"heart": 1.0, "ore": 1.0}


def test_trace_jsonl_is_machine_readable() -> None:
    trace_lines = _extract(_build_zip())["trace.jsonl"].decode("utf-8").splitlines()
    assert len(trace_lines) == 8
    first = json.loads(trace_lines[0])
    assert first["agent_id"] == 0
    assert first["tick"] == 0
    assert first["location"] == [1, 1]
    assert first["action_name"] == "noop"


def test_event_log_parquet_is_readable() -> None:
    files = _extract(_build_zip())
    table = pq.read_table(io.BytesIO(files["events.parquet"]))
    rows = table.to_pylist()
    assert len(rows) == 8
    assert rows[0]["key"] == "agent_state"
    assert rows[0]["player"] == 0
    assert json.loads(rows[0]["value"])["policy_name"] == "alpha:v1"


def test_zip_is_byte_identical_on_rerun() -> None:
    assert _build_zip() == _build_zip()


def test_run_reads_bundle_and_writes_report_zip(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.zip"
    report_path = tmp_path / "report.zip"
    bundle_path.write_bytes(fixtures.make_bundle_zip())

    cvc.run(
        cvc.ReporterInputs(
            episode_bundle_uri=bundle_path.as_uri(),
            report_uri=report_path.as_uri(),
        )
    )

    files = _extract(report_path.read_bytes())
    assert set(files) == _EXPECTED_ENTRIES


def test_failed_bundle_raises(tmp_path: Path) -> None:
    bundle_path = tmp_path / "bundle.zip"
    report_path = tmp_path / "report.zip"
    bundle_path.write_bytes(fixtures.make_bundle_zip(status="failed"))

    with pytest.raises(RuntimeError, match="failed"):
        cvc.run(
            cvc.ReporterInputs(
                episode_bundle_uri=bundle_path.as_uri(),
                report_uri=report_path.as_uri(),
            )
        )
