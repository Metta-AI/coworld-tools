"""Tests for the shared event-log Parquet schema and writer."""

from __future__ import annotations

import io

import pyarrow as pa
import pyarrow.parquet as pq

from reporter_sdk import EVENT_LOG_SCHEMA, write_events_parquet


def test_schema_column_names_and_types() -> None:
    assert EVENT_LOG_SCHEMA.names == ["ts", "player", "key", "value"]
    assert EVENT_LOG_SCHEMA.field("ts").type == pa.int64()
    assert EVENT_LOG_SCHEMA.field("player").type == pa.int64()
    assert EVENT_LOG_SCHEMA.field("key").type == pa.string()
    assert EVENT_LOG_SCHEMA.field("value").type == pa.string()


def test_write_events_parquet_round_trip() -> None:
    rows = [
        {"ts": 1, "player": 0, "key": "input", "value": '{"btn":"up"}'},
        {"ts": 2, "player": -1, "key": "proximity", "value": '{"slot_a":0,"slot_b":1}'},
    ]
    blob = write_events_parquet(rows)
    table = pq.read_table(io.BytesIO(blob))
    assert table.schema.names == ["ts", "player", "key", "value"]
    assert table.to_pylist() == rows


def test_write_events_parquet_empty_list_produces_zero_row_table() -> None:
    blob = write_events_parquet([])
    table = pq.read_table(io.BytesIO(blob))
    assert table.num_rows == 0
    assert table.schema.names == ["ts", "player", "key", "value"]


def test_write_events_parquet_byte_identical_on_rerun() -> None:
    rows = [
        {"ts": 1, "player": 0, "key": "input", "value": "{}"},
        {"ts": 2, "player": 1, "key": "input", "value": "{}"},
    ]
    assert write_events_parquet(rows) == write_events_parquet(rows)
