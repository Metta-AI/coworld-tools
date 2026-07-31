"""Tests for the canonical event-log container (synthetic-row fixtures,
same style as the origin swgy-tools tests)."""

from __future__ import annotations

import json

from episode_analysis.eventlog import EventLog


def _row(ts: int, player: int, key: str, value) -> dict:
    return {"ts": ts, "player": player, "key": key, "value": json.dumps(value)}


ROWS = [
    _row(0, -1, "episode", {"max_steps": 10, "num_agents": 2}),
    _row(0, 0, "position", {"x": 1, "y": 1}),
    _row(0, 1, "position", {"x": 5, "y": 3}),
    _row(2, 0, "position", {"x": 2, "y": 1}),
    _row(3, 0, "reward", {"delta": 1.5, "total": 1.5}),
    _row(4, 1, "death", {}),
    _row(5, -1, "meeting", {"start": 5, "end": 7}),
    _row(8, 0, "reward", {"delta": 0.5, "total": 2.0}),
]


def test_from_rows_decodes_and_sorts():
    log = EventLog.from_rows(list(reversed(ROWS)))
    assert len(log) == len(ROWS)
    assert log.players == [0, 1]
    assert "position" in log.keys and "meeting" in log.keys
    assert log.max_ts == 8
    first = next(iter(log))
    assert first.key == "episode" and first.value["max_steps"] == 10


def test_filter_by_key_and_player():
    log = EventLog.from_rows(ROWS)
    assert len(log.filter(key="position")) == 3
    assert len(log.filter(key="position", player=0)) == 2
    assert log.filter(key="death")[0].player == 1
    assert log.filter(key="nope") == []


def test_positions_accessor():
    log = EventLog.from_rows(ROWS)
    pts = log.positions()
    assert (0, 0, 1.0, 1.0) in pts and (2, 0, 2.0, 1.0) in pts
    assert [p for p in log.positions(player=1)] == [(0, 1, 5.0, 3.0)]


def test_numeric_series_with_field():
    log = EventLog.from_rows(ROWS)
    series = log.numeric_series("reward", player=0, field="total")
    assert series == [(3, 1.5), (8, 2.0)]
    assert log.numeric_series("reward", player=0, field="missing") == []


def test_spans_accessor():
    log = EventLog.from_rows(ROWS)
    assert log.spans("meeting") == [(5, 7)]
    assert log.spans("death") == [(4, 4)]  # point event falls back to (ts, ts)


def test_parquet_round_trip():
    import pyarrow as pa
    import pyarrow.parquet as pq
    import io

    schema = pa.schema(
        [
            pa.field("ts", pa.int64()),
            pa.field("player", pa.int64()),
            pa.field("key", pa.string()),
            pa.field("value", pa.string()),
        ]
    )
    table = pa.table(
        {
            "ts": [r["ts"] for r in ROWS],
            "player": [r["player"] for r in ROWS],
            "key": [r["key"] for r in ROWS],
            "value": [r["value"] for r in ROWS],
        },
        schema=schema,
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    log = EventLog.from_parquet(buf.getvalue())
    assert len(log) == len(ROWS)
    # to_rows re-encodes values as JSON strings matching the input shape.
    back = log.to_rows()
    assert {r["key"] for r in back} == {r["key"] for r in ROWS}
    assert all(isinstance(r["value"], str) for r in back)


def test_non_json_values_pass_through():
    log = EventLog.from_rows([{"ts": 0, "player": 0, "key": "note", "value": "plain-text"}])
    assert log.filter(key="note")[0].value == "plain-text"
