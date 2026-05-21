"""Phase 3 tests: full binary replay parser + per-slot join/leave wiring.

Phase 3 of among_them_summarizer adds:
- `parse_bitreplay(bytes) -> BitReplay` with all four record types
  (joins, leaves, inputs, hashes) and strict format/version checks.
- `tick_from_ms(ms)` helper.
- Per-slot `in_game_name`, `joined_tick`, `left_tick`, `color_index`,
  `color_name` derived from join records + config.slots[i].color
  (with positional `PLAYER_COLOR_NAMES` fallback).
- `AmongThemStats.total_ticks` populated from the last hash record.
- `events.parquet` gains `join` and `leave` keys; the `game_result`
  row's `ts` becomes `last_tick` and its payload's `total_ticks`
  populates.
- Disconnect classification: leave ≥ 5 s before the last hash tick
  is recorded as a disconnect.
- The `token` string from join records is parsed (the format
  requires it) and immediately dropped — `join` event payloads
  expose only `token_present: bool`.
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


# ---------- tick_from_ms ----------


@pytest.mark.parametrize(
    "ms,expected",
    [
        (0, 0),
        (41, 0),  # 41*24/1000 = 0.984 → 0
        (42, 1),  # 42*24/1000 = 1.008 → 1
        (1000, 24),  # exactly one second
        (1041, 24),  # 1041*24/1000 = 24.984 → 24
        (1042, 25),  # 1042*24/1000 = 25.008 → 25
        (10_000, 240),
    ],
)
def test_tick_from_ms(ms: int, expected: int) -> None:
    assert ats.tick_from_ms(ms) == expected


# ---------- parse_bitreplay (records) ----------


def test_parse_bitreplay_no_records() -> None:
    """Header-only bitreplay parses with empty record lists and last_tick=0."""
    blob = fixtures.make_replay_bytes()
    replay = ats.parse_bitreplay(blob)
    assert replay.joins == []
    assert replay.leaves == []
    assert replay.inputs == []
    assert replay.hashes == []
    assert replay.last_tick == 0


def test_parse_bitreplay_mixed_record_types() -> None:
    """All four record types parse correctly when interleaved in time."""
    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="alice", slot=0)
        + fixtures.make_record_join(time_ms=10, player=1, name="bob", slot=1)
        + fixtures.make_record_input(time_ms=50, player=0, keys=0x21)
        + fixtures.make_record_tick_hash(tick=1, hash_value=0xDEADBEEF)
        + fixtures.make_record_input(time_ms=100, player=1, keys=0x04)
        + fixtures.make_record_tick_hash(tick=2)
        + fixtures.make_record_leave(time_ms=200, player=1)
        + fixtures.make_record_tick_hash(tick=4)
    )
    blob = fixtures.make_replay_bytes(records=records)
    replay = ats.parse_bitreplay(blob)
    assert len(replay.joins) == 2
    assert replay.joins[0].name == "alice"
    assert replay.joins[1].slot == 1
    assert len(replay.inputs) == 2
    assert replay.inputs[0].keys == 0x21
    assert len(replay.hashes) == 3
    assert replay.hashes[0].hash == 0xDEADBEEF
    assert len(replay.leaves) == 1
    assert replay.leaves[0].player == 1
    assert replay.last_tick == 4


def test_parse_bitreplay_multibyte_utf8_names() -> None:
    name = "Παίκτης 🎲"  # Greek + emoji
    records = fixtures.make_record_join(time_ms=0, player=0, name=name, slot=0)
    blob = fixtures.make_replay_bytes(records=records)
    replay = ats.parse_bitreplay(blob)
    assert replay.joins[0].name == name


def test_parse_bitreplay_rejects_truncated_record() -> None:
    """A record header byte with no following payload triggers EOF."""
    # Record-type byte followed by only partial u32 time_ms.
    records = bytes([0x02]) + b"\x00\x00"
    blob = fixtures.make_replay_bytes(records=records)
    with pytest.raises(ValueError):
        ats.parse_bitreplay(blob)


def test_parse_bitreplay_rejects_unknown_record_type() -> None:
    records = bytes([0x99]) + b"\x00\x00\x00\x00"  # bogus record type
    blob = fixtures.make_replay_bytes(records=records)
    with pytest.raises(ValueError, match="record type"):
        ats.parse_bitreplay(blob)


def test_parse_bitreplay_token_not_in_join_object() -> None:
    """The `token` string is parsed (format requires it) but stored on
    the join as a separate field. The reporter never writes it to any
    output; the `token_present` boolean is what surfaces.
    """
    records = fixtures.make_record_join(
        time_ms=0, player=0, name="x", slot=0, token="secret-token-value"
    )
    blob = fixtures.make_replay_bytes(records=records)
    replay = ats.parse_bitreplay(blob)
    # The parser does read the token (format requires it).
    assert replay.joins[0].token_present is True


def test_parse_bitreplay_empty_token() -> None:
    records = fixtures.make_record_join(time_ms=0, player=0, name="x", slot=0, token="")
    replay = ats.parse_bitreplay(fixtures.make_replay_bytes(records=records))
    assert replay.joins[0].token_present is False


# ---------- last_tick from hashes ----------


def test_last_tick_from_hash_records() -> None:
    records = b""
    for t in (10, 20, 30):
        records += fixtures.make_record_tick_hash(tick=t)
    replay = ats.parse_bitreplay(fixtures.make_replay_bytes(records=records))
    assert replay.last_tick == 30


def test_last_tick_zero_when_no_hashes() -> None:
    replay = ats.parse_bitreplay(fixtures.make_replay_bytes())
    assert replay.last_tick == 0


# ---------- slot-stat wiring ----------


def _build_zip_with_replay(
    replay_bytes: bytes,
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bytes:
    return ats.build_zip_bytes(
        results=ats.AmongThemResults.model_validate(
            results or fixtures.make_results_crewmate_win()
        ),
        metadata=ats.EpisodeMetadata.model_validate(
            metadata or fixtures.make_metadata()
        ),
        replay_bytes=replay_bytes,
    )


def test_join_populates_in_game_name_and_joined_tick() -> None:
    replay_bytes = fixtures.make_typical_replay_bytes(slots=8, last_tick=1000)
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    for i, slot in enumerate(stats["slots"]):
        assert slot["in_game_name"] == f"in-game-{i}"
        assert slot["joined_tick"] == 0
        assert slot["left_tick"] is None


def test_total_ticks_populated() -> None:
    replay_bytes = fixtures.make_typical_replay_bytes(slots=8, last_tick=2400)
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    assert stats["total_ticks"] == 2400


def test_leave_far_before_end_is_a_disconnect() -> None:
    """A leave 10 s before the last tick → disconnect record."""
    # last_tick = 1000 ticks ≈ 41.7 s. Leave at 20 s ≈ 480 ticks.
    replay_bytes = fixtures.make_typical_replay_bytes(
        slots=8, last_tick=1000, leave_player=5, leave_time_ms=20_000
    )
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    # Slot 5 has its left_tick set.
    assert stats["slots"][5]["left_tick"] is not None
    # Other slots don't.
    for i, s in enumerate(stats["slots"]):
        if i == 5:
            continue
        assert s["left_tick"] is None, f"slot {i} should not have left_tick"
    # Disconnects list has one entry.
    assert len(stats["disconnects"]) == 1
    assert stats["disconnects"][0]["slot"] == 5


def test_leave_at_end_not_a_disconnect() -> None:
    """A leave within 5 s of the last tick is not classified as a disconnect."""
    last_tick = 1000
    last_ms = (last_tick * 1000) // 24
    # Leave 1 second before end (within the 5-second tolerance).
    leave_ms = last_ms - 1000
    replay_bytes = fixtures.make_typical_replay_bytes(
        slots=8, last_tick=last_tick, leave_player=5, leave_time_ms=leave_ms
    )
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    # left_tick is set (the leave happened) but it doesn't promote to a disconnect.
    assert stats["slots"][5]["left_tick"] is not None
    assert stats["disconnects"] == []


def test_color_assignment_falls_through_to_positional_palette() -> None:
    """When config has no per-slot color, every slot's color_index ==
    its slot number (mod 16) and color_name matches PLAYER_COLOR_NAMES."""
    replay_bytes = fixtures.make_typical_replay_bytes(slots=8, last_tick=100)
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    for i, s in enumerate(stats["slots"]):
        assert s["color_index"] == i
        assert s["color_name"] == ats.PLAYER_COLOR_NAMES[i]


def test_color_assignment_uses_config_slots_when_set() -> None:
    """When config.slots[i].color is set, that takes precedence over
    the positional fallback."""
    cfg = fixtures.make_game_config()
    # Slot 0 fixed to "blue" (index 6), slot 1 fixed to "yellow" (index 2).
    cfg["slots"] = [
        {"color": "blue"},
        {"color": "yellow"},
    ] + [{} for _ in range(6)]
    replay_bytes = fixtures.make_typical_replay_bytes(
        slots=8, last_tick=100, config=cfg
    )
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    assert stats["slots"][0]["color_name"] == "blue"
    assert stats["slots"][1]["color_name"] == "yellow"
    # Slots 2-7 fall through to positional palette.
    for i in range(2, 8):
        assert stats["slots"][i]["color_name"] == ats.PLAYER_COLOR_NAMES[i]


# ---------- events.parquet additions ----------


def test_events_parquet_includes_join_and_leave_keys() -> None:
    replay_bytes = fixtures.make_typical_replay_bytes(
        slots=8, last_tick=1000, leave_player=3, leave_time_ms=20_000
    )
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    keys = {r["key"] for r in rows}
    assert "join" in keys
    assert "leave" in keys
    join_rows = [r for r in rows if r["key"] == "join"]
    assert len(join_rows) == 8
    assert {r["player"] for r in join_rows} == set(range(8))


def test_event_join_payload_excludes_token() -> None:
    """The `join` event payload exposes `token_present: bool` only; the
    actual `token` string from the binary record is never serialized."""
    records = fixtures.make_record_join(
        time_ms=0, player=0, name="x", slot=0, token="super-secret"
    )
    blob = fixtures.make_replay_bytes(records=records)
    payload = ats.build_zip_bytes(
        results=ats.AmongThemResults.model_validate(
            fixtures.make_results_crewmate_win(slots=1)
        ),
        metadata=ats.EpisodeMetadata.model_validate(
            fixtures.make_metadata(slots=1, policy_names=[None])
        ),
        replay_bytes=blob,
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        parquet_bytes = zf.read("events.parquet")
        # Check the raw parquet bytes don't contain the token, anywhere.
        assert b"super-secret" not in parquet_bytes
        # And neither does the html or stats.
        for name in zf.namelist():
            assert b"super-secret" not in zf.read(name), name


def test_game_result_uses_last_tick() -> None:
    replay_bytes = fixtures.make_typical_replay_bytes(slots=8, last_tick=2400)
    payload = _build_zip_with_replay(replay_bytes)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    [gr] = [r for r in rows if r["key"] == "game_result"]
    assert gr["ts"] == 2400
    assert gr["value"]["total_ticks"] == 2400


def test_slot_join_order_populated_from_replay() -> None:
    """SlotStats.join_order is the connection-order index that joined
    into the slot (from the replay's ReplayJoinRecord.player field)."""
    # Build a replay where slots are assigned out-of-order: slot 3
    # joins first (player_index=0), slot 0 joins second (player_index=1),
    # slot 5 joins third (player_index=2).
    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="a", slot=3)
        + fixtures.make_record_join(time_ms=0, player=1, name="b", slot=0)
        + fixtures.make_record_join(time_ms=0, player=2, name="c", slot=5)
        + fixtures.make_record_tick_hash(tick=100)
    )
    replay_bytes = fixtures.make_replay_bytes(records=records)
    payload = ats.build_zip_bytes(
        results=ats.AmongThemResults.model_validate(
            fixtures.make_results_crewmate_win(slots=8)
        ),
        metadata=ats.EpisodeMetadata.model_validate(fixtures.make_metadata()),
        replay_bytes=replay_bytes,
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        stats = json.loads(zf.read("stats.json"))
    # Slot 3 joined at connection index 0; slot 0 at index 1; slot 5 at 2.
    assert stats["slots"][3]["join_order"] == 0
    assert stats["slots"][0]["join_order"] == 1
    assert stats["slots"][5]["join_order"] == 2
    # Slots that never received a join record have join_order=None.
    assert stats["slots"][1]["join_order"] is None
    assert stats["slots"][2]["join_order"] is None
    # The convenience top-level mapping carries the same values.
    assert stats["slot_to_join_order"] == [1, None, None, 0, None, 2, None, None]


def test_join_event_carries_player_index() -> None:
    """The `join` event in events.parquet exposes both `slot` and
    `player_index` so downstream ingesters can reconstruct the
    connection-order ↔ slot mapping from the parquet alone."""
    import pyarrow.parquet as pq

    records = (
        fixtures.make_record_join(time_ms=0, player=0, name="a", slot=3)
        + fixtures.make_record_join(time_ms=0, player=1, name="b", slot=0)
        + fixtures.make_record_tick_hash(tick=100)
    )
    replay_bytes = fixtures.make_replay_bytes(records=records)
    payload = ats.build_zip_bytes(
        results=ats.AmongThemResults.model_validate(
            fixtures.make_results_crewmate_win(slots=8)
        ),
        metadata=ats.EpisodeMetadata.model_validate(fixtures.make_metadata()),
        replay_bytes=replay_bytes,
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        table = pq.read_table(io.BytesIO(zf.read("events.parquet")))
    rows = [
        {"player": p, "value": json.loads(v)}
        for p, k, v in zip(
            table["player"].to_pylist(),
            table["key"].to_pylist(),
            table["value"].to_pylist(),
        )
        if k == "join"
    ]
    by_slot = {r["player"]: r["value"] for r in rows}
    assert by_slot[3]["player_index"] == 0
    assert by_slot[3]["slot"] == 3
    assert by_slot[0]["player_index"] == 1
    assert by_slot[0]["slot"] == 0


def test_disconnects_section_in_html_only_when_present() -> None:
    """The HTML's Disconnects section is rendered only when there's at
    least one mid-game leave. Slot identifiers appear in the disconnect
    list when present.
    """
    no_dc = fixtures.make_typical_replay_bytes(slots=8, last_tick=1000)
    payload_no = _build_zip_with_replay(no_dc)
    with zipfile.ZipFile(io.BytesIO(payload_no)) as zf:
        html_no = zf.read("summary.html").decode()
    assert "Disconnects" not in html_no

    with_dc = fixtures.make_typical_replay_bytes(
        slots=8, last_tick=1000, leave_player=4, leave_time_ms=10_000
    )
    payload_dc = _build_zip_with_replay(with_dc)
    with zipfile.ZipFile(io.BytesIO(payload_dc)) as zf:
        html_dc = zf.read("summary.html").decode()
    assert "Disconnects" in html_dc
