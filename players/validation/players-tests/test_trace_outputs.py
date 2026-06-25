from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from players.player_sdk import EventEmitter, ListTraceSink, TraceEvent, TraceOutputs, parse_trace_output_specs
from players.player_sdk.trace_outputs import _trace_record


def test_parse_trace_output_specs_supports_formats_and_destinations() -> None:
    specs = parse_trace_output_specs("jsonl@stderr,json@artifact:events.json,csv@file:/tmp/events.csv")

    assert [(spec.format, spec.destination, spec.target) for spec in specs] == [
        ("jsonl", "stderr", None),
        ("json", "artifact", "events.json"),
        ("csv", "file", "/tmp/events.csv"),
    ]


def test_trace_record_omits_step_when_tick_only() -> None:
    assert _trace_record(TraceEvent(tick=2, name="domain.phase_change", data={"to": "Playing"})) == {
        "kind": "trace",
        "tick": 2,
        "event": "domain.phase_change",
        "name": "domain.phase_change",
        "data": {"to": "Playing"},
    }


def test_trace_outputs_default_jsonl_to_stderr_filters_events() -> None:
    stream = io.StringIO()
    outputs = TraceOutputs.from_env(
        prefix="TEST",
        event_filter=lambda event: event.name.startswith("domain."),
        env={},
        stderr=stream,
    )
    outputs.trace_sink.record(TraceEvent(tick=1, name="perception", data={}))
    outputs.trace_sink.record(TraceEvent(tick=2, name="domain.phase_change", data={"to": "Playing"}))
    outputs.close()

    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert records == [
        {
            "kind": "trace",
            "tick": 2,
            "event": "domain.phase_change",
            "name": "domain.phase_change",
            "data": {"to": "Playing"},
        }
    ]


def test_trace_outputs_write_json_and_csv_files(tmp_path) -> None:
    json_path = tmp_path / "telemetry.json"
    csv_path = tmp_path / "telemetry.csv"
    specs = parse_trace_output_specs(f"json@file:{json_path},csv@file:{csv_path}")

    with TraceOutputs.from_specs(specs, metrics_enabled=True) as outputs:
        outputs.trace_sink.record(TraceEvent(tick=3, name="domain.vote_cast", data={"target": "red"}))
        outputs.metrics_sink.counter("domain.vote_cast", tags={"target": "red"})

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert [record["kind"] for record in payload["records"]] == ["trace", "metric"]

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows[0]["kind"] == "trace"
    assert rows[0]["tick"] == "3"
    assert rows[0]["name"] == "domain.vote_cast"
    assert json.loads(rows[0]["data_json"]) == {"target": "red"}
    assert rows[1]["kind"] == "metric"
    assert rows[1]["metric_kind"] == "counter"
    assert json.loads(rows[1]["tags_json"]) == {"target": "red"}


def test_trace_outputs_write_step_to_jsonl_and_csv_files(tmp_path) -> None:
    jsonl_path = tmp_path / "telemetry.jsonl"
    csv_path = tmp_path / "telemetry.csv"
    specs = parse_trace_output_specs(f"jsonl@file:{jsonl_path},csv@file:{csv_path}")

    with TraceOutputs.from_specs(specs) as outputs:
        outputs.trace_sink.record(TraceEvent(tick=0, step="propose", name="domain.turn_phase", data={"actor": "red"}))

    jsonl_records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert jsonl_records == [
        {
            "kind": "trace",
            "tick": 0,
            "step": "propose",
            "event": "domain.turn_phase",
            "name": "domain.turn_phase",
            "data": {"actor": "red"},
        }
    ]

    with csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == ["kind", "tick", "step", "name", "metric_kind", "value", "data_json", "tags_json"]
        rows = list(reader)
    assert rows[0]["tick"] == "0"
    assert rows[0]["step"] == "propose"
    assert rows[0]["name"] == "domain.turn_phase"
    assert json.loads(rows[0]["data_json"]) == {"actor": "red"}


def test_event_emitter_records_optional_step_labels() -> None:
    no_step_sink = ListTraceSink()
    EventEmitter(no_step_sink, tick=7).event("meeting_opened")

    assert no_step_sink.events[0].name == "domain.meeting_opened"
    assert no_step_sink.events[0].step is None

    step_sink = ListTraceSink()
    emitter = EventEmitter(step_sink, tick=8, step="propose")
    emitter.event("turn_phase")
    emitter.event("turn_phase", step="resolve")

    assert [(event.name, event.tick, event.step) for event in step_sink.events] == [
        ("domain.turn_phase", 8, "propose"),
        ("domain.turn_phase", 8, "resolve"),
    ]


def test_trace_outputs_bundle_artifact_zip_to_file_url(tmp_path) -> None:
    artifact_path = tmp_path / "policy_artifact_0.zip"
    specs = parse_trace_output_specs("jsonl@artifact:traces/events.jsonl,csv@artifact")

    with TraceOutputs.from_specs(
        specs,
        metrics_enabled=True,
        artifact_upload_url=f"file://{artifact_path}",
    ) as outputs:
        outputs.trace_sink.record(TraceEvent(tick=5, name="domain.kill_attempted", data={"target": "blue"}))
        outputs.metrics_sink.gauge("domain.kill_ready", 1, tags={"mode": "hunt"})

    with zipfile.ZipFile(artifact_path) as archive:
        names = set(archive.namelist())
        assert names == {"manifest.json", "telemetry.csv", "traces/events.jsonl"}
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["producer"] == "players.player_sdk.TraceOutputs"
        jsonl_record = json.loads(archive.read("traces/events.jsonl").decode("utf-8").splitlines()[0])
        assert jsonl_record["event"] == "domain.kill_attempted"


def test_trace_outputs_artifact_requires_upload_url() -> None:
    specs = parse_trace_output_specs("jsonl@artifact")

    with pytest.raises(ValueError, match="artifact trace output requires"):
        TraceOutputs.from_specs(specs)


def test_trace_outputs_rejects_invalid_artifact_members(tmp_path) -> None:
    with pytest.raises(ValueError, match="invalid artifact member path"):
        TraceOutputs.from_specs(
            parse_trace_output_specs("jsonl@artifact:../events.jsonl"),
            artifact_upload_url=f"file://{tmp_path / 'artifact.zip'}",
        )

    with pytest.raises(ValueError, match="duplicate artifact member path"):
        TraceOutputs.from_specs(
            parse_trace_output_specs("jsonl@artifact:events.jsonl,csv@artifact:events.jsonl"),
            artifact_upload_url=f"file://{tmp_path / 'artifact.zip'}",
        )


def test_trace_outputs_parquet_file_when_pyarrow_available(tmp_path) -> None:
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    path = tmp_path / "telemetry.parquet"
    specs = parse_trace_output_specs(f"parquet@file:{path}")

    with TraceOutputs.from_specs(specs) as outputs:
        outputs.trace_sink.record(TraceEvent(tick=8, name="domain.viewer_frame", data={"mode": "search"}))

    rows = pq.read_table(path).to_pylist()
    assert rows[0]["kind"] == "trace"
    assert rows[0]["tick"] == 8
    assert rows[0]["name"] == "domain.viewer_frame"
