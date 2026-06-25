"""Phase 4 tests: input-stream analytics.

Phase 4 of among_them_summarizer adds:
- `extract_input_presses(replay)` — walks input records in time order,
  detects edge (0→1) transitions per button per player, maps via the
  current player→slot table maintained across joins+leaves.
- `bucket_presses(presses, bucket_ticks)` — aggregates presses into
  per-(slot, bucket) buckets with per-button breakdown.
- Wiring: `SlotStats.input_press_total` and `input_press_per_kind` are
  populated; the `activity` block lands in `stats.json`.
- `events.parquet` gains the `input_press` and `activity_bucket` keys.
- The HTML scoreboard gets a basic activity column (phase 5 replaces it
  with a per-slot sparkline SVG).
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pyarrow.parquet as pq
import pytest

import among_them_summarizer as ats
import fixtures


def _read_parquet_rows(blob: bytes) -> list[dict[str, Any]]:
    table = pq.read_table(io.BytesIO(blob))
    rows: list[dict[str, Any]] = []
    for ts, player, key, value in zip(
        table["ts"].to_pylist(),
        table["player"].to_pylist(),
        table["key"].to_pylist(),
        table["value"].to_pylist(),
    ):
        rows.append(
            {"ts": ts, "player": player, "key": key, "value": json.loads(value)}
        )
    return rows


# ---------- extract_input_presses ----------


def _replay_from_records(records: bytes, *, last_tick: int = 100) -> ats.BitReplay:
    records += fixtures.make_record_tick_hash(tick=last_tick)
    blob = fixtures.make_replay_bytes(records=records)
    return ats.parse_bitreplay(blob)


def test_extract_presses_single_press_emits_one_event() -> None:
    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="a", slot=0)
        + fixtures.make_record_input(time_ms=100, player=0, keys=0x01)  # press 'up'
        + fixtures.make_record_input(time_ms=200, player=0, keys=0x00)  # release
    )
    replay = _replay_from_records(records)
    presses = ats.extract_input_presses(replay)
    assert len(presses) == 1
    assert presses[0].slot == 0
    assert presses[0].button == "up"
    assert presses[0].tick == ats.tick_from_ms(100)


def test_extract_presses_held_key_is_one_press() -> None:
    """The game writer only emits a record when the mask CHANGES (see
    server.nim's `currentMask != lastMasks[playerIndex]` guard). So
    'held for 30 ticks' produces one record with the press; the
    release is the next record."""
    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="a", slot=0)
        + fixtures.make_record_input(time_ms=0, player=0, keys=0x01)
        # No additional records for the 30 held ticks.
        + fixtures.make_record_input(time_ms=1250, player=0, keys=0x00)
    )
    replay = _replay_from_records(records)
    presses = ats.extract_input_presses(replay)
    assert len(presses) == 1


def test_extract_presses_release_and_repress_emits_two() -> None:
    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="a", slot=0)
        + fixtures.make_record_input(time_ms=0, player=0, keys=0x01)
        + fixtures.make_record_input(time_ms=100, player=0, keys=0x00)
        + fixtures.make_record_input(time_ms=200, player=0, keys=0x01)
    )
    presses = ats.extract_input_presses(_replay_from_records(records))
    assert len(presses) == 2
    assert all(p.button == "up" for p in presses)


def test_extract_presses_simultaneous_bits_emit_one_per_bit() -> None:
    """A single record with multiple newly-set edge bits emits one
    press per set bit, all at the same tick."""
    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="a", slot=0)
        + fixtures.make_record_input(time_ms=100, player=0, keys=0x21)  # up + attack
    )
    presses = ats.extract_input_presses(_replay_from_records(records))
    buttons = sorted(p.button for p in presses)
    assert buttons == ["attack", "up"]
    # Both at the same tick.
    assert presses[0].tick == presses[1].tick


def test_extract_presses_uses_slot_not_raw_player_index() -> None:
    """After a leave shifts sim.players, subsequent inputs still map
    to their correct slot."""
    # Player 0 joins at slot 0, player 1 joins at slot 1.
    # Player 0 leaves; player 1 is now at index 0.
    # Input arrives with player=0 → must resolve to slot 1.
    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="a", slot=0)
        + fixtures.make_record_join(time_ms=0, player=1, name="b", slot=1)
        + fixtures.make_record_leave(time_ms=500, player=0)
        + fixtures.make_record_input(time_ms=1000, player=0, keys=0x01)
    )
    presses = ats.extract_input_presses(_replay_from_records(records))
    assert len(presses) == 1
    assert presses[0].slot == 1


def test_extract_presses_empty_input_stream() -> None:
    records = fixtures.make_record_join(time_ms=0, player=0, name="a", slot=0)
    presses = ats.extract_input_presses(_replay_from_records(records))
    assert presses == []


@pytest.mark.parametrize(
    "bit,name",
    [
        (0x01, "up"),
        (0x02, "down"),
        (0x04, "left"),
        (0x08, "right"),
        (0x10, "select"),
        (0x20, "attack"),
        (0x40, "b"),
    ],
)
def test_extract_presses_all_seven_buttons(bit: int, name: str) -> None:
    records = fixtures.make_record_join(
        time_ms=0, player=0, name="a", slot=0
    ) + fixtures.make_record_input(time_ms=0, player=0, keys=bit)
    presses = ats.extract_input_presses(_replay_from_records(records))
    assert len(presses) == 1
    assert presses[0].button == name


# ---------- bucket_presses ----------


def test_bucket_presses_groups_by_slot_and_window() -> None:
    """Presses falling in the same bucket are aggregated; different
    buckets stay separate."""
    presses = [
        ats.InputPress(tick=0, slot=0, button="up"),
        ats.InputPress(tick=5, slot=0, button="up"),
        ats.InputPress(tick=250, slot=0, button="up"),  # next bucket (240+)
        ats.InputPress(tick=0, slot=1, button="attack"),  # different slot
    ]
    buckets = ats.bucket_presses(presses, bucket_ticks=240)
    by_key = {(b.slot, b.bucket_start_tick): b for b in buckets}
    assert by_key[(0, 0)].presses_total == 2
    assert by_key[(0, 0)].presses_by_button == {"up": 2}
    assert by_key[(0, 240)].presses_total == 1
    assert by_key[(1, 0)].presses_by_button == {"attack": 1}


def test_bucket_presses_empty_input_yields_no_buckets() -> None:
    assert ats.bucket_presses([], bucket_ticks=240) == []


def test_bucket_presses_total_equals_sum_per_button() -> None:
    presses = [
        ats.InputPress(tick=10, slot=0, button="up"),
        ats.InputPress(tick=20, slot=0, button="down"),
        ats.InputPress(tick=30, slot=0, button="up"),
    ]
    [b] = ats.bucket_presses(presses, bucket_ticks=240)
    assert b.presses_total == 3
    assert sum(b.presses_by_button.values()) == b.presses_total


# ---------- end-to-end wiring ----------


def _make_replay_with_inputs(*, slots: int = 8, last_tick: int = 1000) -> bytes:
    """Episode with each slot pressing a different button several times.

    Slot i presses button index (i % 7) — first press at ms 100*i,
    release at 100*i + 50. So each slot generates `i + 1` press events,
    giving differentiated input_press_total across slots.
    """
    button_bits = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40]
    records = b""
    for i in range(slots):
        records += fixtures.make_record_join(
            time_ms=0, player=i, name=f"in-game-{i}", slot=i
        )
    for i in range(slots):
        bit = button_bits[i % 7]
        # Each slot presses+releases (i + 1) times. Stagger time_ms so
        # records remain monotonically increasing.
        base = 100 + i * 1000
        for k in range(i + 1):
            t = base + 4 * k
            records += fixtures.make_record_input(time_ms=t, player=i, keys=bit)
            records += fixtures.make_record_input(time_ms=t + 2, player=i, keys=0x00)
    records += fixtures.make_record_tick_hash(tick=last_tick)
    return fixtures.make_replay_bytes(records=records)


def _build_zip(replay_bytes: bytes) -> bytes:
    return ats.build_zip_bytes(
        results=ats.AmongThemResults.model_validate(
            fixtures.make_results_crewmate_win()
        ),
        metadata=ats.EpisodeMetadata.model_validate(fixtures.make_metadata()),
        replay_bytes=replay_bytes,
    )


def test_stats_input_press_total_populated_per_slot() -> None:
    replay_bytes = _make_replay_with_inputs(slots=8)
    payload = _build_zip(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    # Slot i pressed (i+1) times.
    for i, s in enumerate(stats["slots"]):
        assert s["input_press_total"] == i + 1, f"slot {i}: {s['input_press_total']}"
        assert s["input_press_per_kind"] is not None
        assert sum(s["input_press_per_kind"].values()) == s["input_press_total"]


def test_stats_activity_block_populated() -> None:
    replay_bytes = _make_replay_with_inputs(slots=8)
    payload = _build_zip(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    activity = stats["activity"]
    assert activity["bucket_ticks"] == ats.ACTIVITY_BUCKET_TICKS
    assert activity["bucket_ticks"] == 240  # REPLAY_FPS * 10
    # Each slot that pressed at least once appears in buckets_per_slot.
    slots_with_buckets = {entry["slot"] for entry in activity["buckets_per_slot"]}
    assert slots_with_buckets == set(range(8))


def test_events_parquet_has_input_press_and_activity_bucket() -> None:
    replay_bytes = _make_replay_with_inputs(slots=8)
    payload = _build_zip(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    keys = {r["key"] for r in rows}
    assert "input_press" in keys
    assert "activity_bucket" in keys


def test_input_press_payload_shape() -> None:
    replay_bytes = _make_replay_with_inputs(slots=2)
    payload = _build_zip(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    input_rows = [r for r in rows if r["key"] == "input_press"]
    # Slot 0 had (0+1)=1 press, slot 1 had (1+1)=2 presses → 3 total.
    assert len(input_rows) == 3
    for r in input_rows:
        assert r["value"]["button"] in ats.BUTTON_NAMES
        assert r["player"] in (0, 1)


def test_activity_bucket_payload_shape() -> None:
    replay_bytes = _make_replay_with_inputs(slots=2)
    payload = _build_zip(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    [_first_bucket, *_] = [r for r in rows if r["key"] == "activity_bucket"]
    val = _first_bucket["value"]
    assert val["bucket_ticks"] == ats.ACTIVITY_BUCKET_TICKS
    assert "presses_total" in val
    assert isinstance(val["presses_by_button"], dict)
    assert sum(val["presses_by_button"].values()) == val["presses_total"]


def test_empty_input_stream_keeps_input_press_total_zero() -> None:
    """Replay with no input records → all slots have total 0, no
    `input_press` or `activity_bucket` rows in the parquet."""
    replay_bytes = fixtures.make_typical_replay_bytes(slots=8, last_tick=100)
    payload = _build_zip(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
        rows = _read_parquet_rows(zf.read("events.parquet"))
    for s in stats["slots"]:
        assert s["input_press_total"] == 0
        # input_press_per_kind exists as an empty dict (not None) once
        # phase 4 ships.
        assert s["input_press_per_kind"] == {}
    keys = {r["key"] for r in rows}
    assert "input_press" not in keys
    assert "activity_bucket" not in keys


def test_html_scoreboard_has_activity_column() -> None:
    replay_bytes = _make_replay_with_inputs(slots=8)
    payload = _build_zip(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        html = zf.read("summary.html").decode()
    # Activity column header is present.
    assert "Activity" in html
