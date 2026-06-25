"""Test suite for paint_arena_summarizer.

Covers pure-function zip construction (build_zip_bytes, build_stats), the
frame-derived parquet and highlight pipeline, the HTML renderer, and end-to-
end run() invocations against file:// URIs.

Output contract is the canonical Coworld reporter contract:
- The reporter reads a single COGAME_EPISODE_BUNDLE_URI (a zip with an inner
  manifest.json mapping tokens to file paths) and writes a single zip to
  COGAME_REPORT_URI.
- Top-level entries in the output zip: manifest.json, summary.html,
  stats.json, proximity.parquet.
- The in-zip manifest.json flags `render: "summary.html"` and
  `event_log: "proximity.parquet"`; both target paths exist in the zip.
- Every zip entry has a pinned mtime of (1980, 1, 1, 0, 0, 0) so identical
  inputs produce byte-identical zips. (The parquet's own determinism is
  bounded by the pinned pyarrow version in requirements.txt.)
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

import paint_arena_summarizer as par
from tests import fixtures


# ---------- helpers ----------


_RENDERABLE_EXTS = {".md", ".html"}
_PINNED_MTIME = (1980, 1, 1, 0, 0, 0)
_EXPECTED_ENTRIES = {
    "manifest.json",
    "summary.html",
    "stats.json",
    "proximity.parquet",
}


def _models(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> tuple[par.PaintArenaResults, par.EpisodeMetadata, par.PaintArenaReplay]:
    return (
        par.PaintArenaResults.model_validate(results or fixtures.make_results_happy()),
        par.EpisodeMetadata.model_validate(metadata or fixtures.make_metadata()),
        par.PaintArenaReplay.model_validate(replay or fixtures.make_replay()),
    )


def _build_zip(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> bytes:
    r, m, p = _models(results=results, metadata=metadata, replay=replay)
    return par.build_zip_bytes(results=r, metadata=m, replay=p)


def _extract(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


def _manifest_dict(payload: bytes) -> dict[str, Any]:
    files = _extract(payload)
    return json.loads(files["manifest.json"])


def _read_parquet(blob: bytes) -> list[dict[str, Any]]:
    """Decode a parquet blob into a list of row dicts."""
    table = pq.read_table(io.BytesIO(blob))
    return table.to_pylist()


# ---------- pure build_zip_bytes / build_stats ----------


def test_happy_path_zip_entries() -> None:
    payload = _build_zip()
    files = _extract(payload)
    assert set(files.keys()) == _EXPECTED_ENTRIES


def test_manifest_flags_summary_html_as_render() -> None:
    """The in-zip manifest.json flags `summary.html` as the render target."""
    payload = _build_zip()
    manifest = _manifest_dict(payload)
    assert manifest["render"] == "summary.html"
    assert manifest["reporter_id"] == "paint-arena-summarizer"


def test_manifest_flags_proximity_parquet_as_event_log() -> None:
    """The in-zip manifest.json flags `proximity.parquet` as the event log."""
    payload = _build_zip()
    manifest = _manifest_dict(payload)
    assert manifest["event_log"] == "proximity.parquet"


def test_manifest_targets_exist_in_zip_with_renderable_extension() -> None:
    """`render` resolves to an in-zip `.md`/`.html`; `event_log` resolves to
    an in-zip Parquet."""
    payload = _build_zip()
    files = _extract(payload)
    manifest = _manifest_dict(payload)
    assert manifest["render"] in files
    assert manifest["event_log"] in files
    assert Path(manifest["render"]).suffix.lower() in _RENDERABLE_EXTS
    # Sanity-check the event_log opens as a Parquet table.
    pq.read_table(io.BytesIO(files[manifest["event_log"]]))


def test_zip_entries_have_pinned_mtime() -> None:
    """All entries pin date_time to (1980,1,1,0,0,0) for byte-identical
    reruns (D12)."""
    payload = _build_zip()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            assert info.date_time == _PINNED_MTIME, (
                f"{info.filename} has date_time {info.date_time}, expected {_PINNED_MTIME}"
            )


def test_zip_is_well_formed() -> None:
    """Zip bytes are readable (no testzip error) — platform invalid_output check."""
    with zipfile.ZipFile(io.BytesIO(_build_zip())) as zf:
        assert zf.testzip() is None


def test_happy_path_stats_numbers() -> None:
    results, metadata, replay = _models()
    proximity_rows = par.build_proximity_rows(replay.frames, width=replay.config.width)
    tile_flips = par.extract_tile_flips(replay.frames, width=replay.config.width)
    highlights = par.detect_back_and_forth_highlights(tile_flips)
    stats = par.build_stats(
        results,
        metadata,
        replay.config,
        proximity_event_count=len(proximity_rows),
        highlights=highlights,
    )
    assert stats.episode_id == "ep_abc123"
    assert stats.variant_id == "default"
    assert stats.grid.width == 12
    assert stats.grid.height == 8
    assert stats.grid.total_tiles == 96
    assert stats.ticks == 100
    assert stats.unpainted_tiles == 11
    assert stats.winner_slot == 0
    assert stats.margin_tiles == 9
    assert stats.tie is False
    assert [s.slot for s in stats.slots] == [0, 1]
    assert stats.slots[0].policy_name == "champion-v3"
    assert stats.slots[0].painted_tiles == 47
    assert stats.slots[0].share_pct == pytest.approx(48.96, abs=0.01)


def test_happy_path_summary_html_content() -> None:
    payload = _build_zip()
    summary = _extract(payload)["summary.html"].decode("utf-8")
    assert summary.startswith("<!DOCTYPE html>")
    assert "PaintArena" in summary
    assert "ep_abc123" in summary
    assert "champion-v3" in summary
    assert "Winner" in summary
    # Self-contained: no external links to fonts/scripts/stylesheets.
    assert "<link" not in summary
    assert "<script" not in summary


def test_happy_path_stats_json_content() -> None:
    payload = _build_zip()
    stats = json.loads(_extract(payload)["stats.json"])
    assert stats["episode_id"] == "ep_abc123"
    assert stats["variant_id"] == "default"
    assert stats["grid"] == {"width": 12, "height": 8, "total_tiles": 96}
    assert stats["winner_slot"] == 0
    assert stats["margin_tiles"] == 9
    assert stats["tie"] is False
    # The new aggregate fields exposing the frame-derived signal:
    assert stats["proximity_event_count"] >= 1
    assert isinstance(stats["highlights"], list)


def test_zero_paint_episode() -> None:
    payload = _build_zip(
        results=fixtures.make_results_zero_paint(),
        replay=fixtures.make_replay_no_frames(),
    )
    files = _extract(payload)
    stats = json.loads(files["stats.json"])
    assert stats["winner_slot"] is None
    assert stats["tie"] is False
    assert stats["margin_tiles"] == 0
    assert stats["unpainted_tiles"] == 96
    summary = files["summary.html"].decode("utf-8")
    assert "no tiles were painted" in summary.lower()


def test_tie_episode() -> None:
    payload = _build_zip(results=fixtures.make_results_tie())
    files = _extract(payload)
    stats = json.loads(files["stats.json"])
    assert stats["winner_slot"] is None
    assert stats["tie"] is True
    assert stats["margin_tiles"] == 0
    summary = files["summary.html"].decode("utf-8")
    assert "tied" in summary.lower()


def test_policy_name_falls_back_to_slot_label() -> None:
    metadata_dict = fixtures.make_metadata()
    metadata_dict["players"][1]["policy_name"] = None
    payload = _build_zip(metadata=metadata_dict)
    stats = json.loads(_extract(payload)["stats.json"])
    assert stats["slots"][1]["policy_name"] == "Slot 1"


def test_replay_missing_config_raises() -> None:
    bad_replay = fixtures.make_replay()
    del bad_replay["config"]
    with pytest.raises(ValidationError):
        par.PaintArenaReplay.model_validate(bad_replay)


def test_replay_config_missing_dimensions_raises() -> None:
    bad_replay = fixtures.make_replay()
    del bad_replay["config"]["width"]
    with pytest.raises(ValidationError):
        par.PaintArenaReplay.model_validate(bad_replay)


def test_replay_with_no_frames_still_writes_valid_zip() -> None:
    """No-frames is the degenerate case: HTML renders the verdict + an empty
    grid heatmap; parquet is a well-formed zero-row table; no highlights."""
    payload = _build_zip(replay=fixtures.make_replay_no_frames())
    files = _extract(payload)
    assert set(files.keys()) == _EXPECTED_ENTRIES
    rows = _read_parquet(files["proximity.parquet"])
    assert rows == []
    stats = json.loads(files["stats.json"])
    assert stats["proximity_event_count"] == 0
    assert stats["highlights"] == []
    summary = files["summary.html"].decode("utf-8")
    assert "No back-and-forth moments detected" in summary


# ---------- frame-derived extractors ----------


def test_extract_tile_flips_only_counts_painted_to_painted() -> None:
    """First-time paints (-1 → slot) are excluded; only painted→painted
    transitions count as flips."""
    _, _, replay = _models()
    flips = par.extract_tile_flips(replay.frames, width=replay.config.width)
    # In the scripted fixture, tile (5, 3) is the only contested tile and
    # gets painted->painted flips at ticks 11, 12, 13, 14.
    contested = [f for f in flips if f["x"] == 5 and f["y"] == 3]
    assert [f["tick"] for f in contested] == [11, 12, 13, 14]
    for f in contested:
        assert f["prev_owner"] in (0, 1)
        assert f["new_owner"] in (0, 1)
        assert f["prev_owner"] != f["new_owner"]
    # No other tiles flip in the scripted fixture (everything else is either
    # untouched or only painted once).
    assert all(f["x"] == 5 and f["y"] == 3 for f in flips)


def test_detect_back_and_forth_highlights_picks_contested_tile() -> None:
    _, _, replay = _models()
    flips = par.extract_tile_flips(replay.frames, width=replay.config.width)
    highlights = par.detect_back_and_forth_highlights(flips)
    assert len(highlights) == 1
    h = highlights[0]
    assert (h.x, h.y) == (5, 3)
    assert h.flips == 4
    assert h.tick_start == 11
    assert h.tick_end == 14
    assert h.slots == [0, 1]


def test_detect_back_and_forth_highlights_respects_window() -> None:
    """If the flips are spread over more than window_ticks, no highlight
    fires unless a sub-window still meets min_flips."""
    flips = [
        {"tick": 0, "x": 1, "y": 1, "prev_owner": 0, "new_owner": 1},
        {"tick": 50, "x": 1, "y": 1, "prev_owner": 1, "new_owner": 0},
    ]
    # min_flips=2, default window=10: the two flips are 50 ticks apart.
    assert par.detect_back_and_forth_highlights(flips) == []


def test_detect_back_and_forth_highlights_caps_results() -> None:
    """When more tiles flip than max_results allows, only the top-N survive."""
    flips = []
    # 10 different tiles each flipping 2 times within 1 tick.
    for i in range(10):
        flips.append({"tick": 2 * i, "x": i, "y": 0, "prev_owner": 0, "new_owner": 1})
        flips.append({"tick": 2 * i + 1, "x": i, "y": 0, "prev_owner": 1, "new_owner": 0})
    highlights = par.detect_back_and_forth_highlights(flips, max_results=3)
    assert len(highlights) == 3


def test_build_proximity_rows_counts_match_fixture() -> None:
    """The scripted fixture is designed so that exactly seven frames have
    the two agents within Chebyshev distance ≤ 2 (ticks 9..15)."""
    _, _, replay = _models()
    rows = par.build_proximity_rows(replay.frames, width=replay.config.width)
    assert [r["tick"] for r in rows] == [9, 10, 11, 12, 13, 14, 15]
    # Each row in this 2-player fixture is the (0, 1) pair.
    assert all(r["slot_a"] == 0 and r["slot_b"] == 1 for r in rows)
    # Chebyshev distance respects the threshold.
    assert all(r["chebyshev_distance"] <= par.PROXIMITY_THRESHOLD for r in rows)


def test_build_proximity_rows_generalizes_over_slot_count() -> None:
    """A 3-agent frame within range produces C(3,2)=3 rows for that tick."""
    frame = par.PaintArenaFrame(
        tick=7,
        positions=[[1, 1], [2, 1], [1, 2]],  # all mutually within Cheb=1
        tile_owners=[-1] * 96,
    )
    rows = par.build_proximity_rows([frame], width=12)
    pairs = sorted((r["slot_a"], r["slot_b"]) for r in rows)
    assert pairs == [(0, 1), (0, 2), (1, 2)]
    assert all(r["tick"] == 7 for r in rows)


# ---------- parquet output ----------


def test_parquet_uses_shared_event_log_schema() -> None:
    payload = _build_zip()
    blob = _extract(payload)["proximity.parquet"]
    table = pq.read_table(io.BytesIO(blob))
    assert table.schema.names == ["ts", "player", "key", "value"]
    # `key` partitions the row kinds.
    keys = set(table.column("key").to_pylist())
    assert keys == {"proximity", "back_and_forth"}


def test_parquet_proximity_rows_carry_pair_payload() -> None:
    payload = _build_zip()
    rows = _read_parquet(_extract(payload)["proximity.parquet"])
    proximity_rows = [r for r in rows if r["key"] == "proximity"]
    assert len(proximity_rows) == 7  # matches the fixture
    for r in proximity_rows:
        assert r["player"] == -1  # pair-event => global
        payload_dict = json.loads(r["value"])
        assert payload_dict["slot_a"] == 0
        assert payload_dict["slot_b"] == 1
        assert payload_dict["chebyshev_distance"] <= par.PROXIMITY_THRESHOLD
        assert "pos_a" in payload_dict and "pos_b" in payload_dict


def test_parquet_highlight_rows_carry_contested_tile() -> None:
    payload = _build_zip()
    rows = _read_parquet(_extract(payload)["proximity.parquet"])
    highlight_rows = [r for r in rows if r["key"] == "back_and_forth"]
    assert len(highlight_rows) == 1
    payload_dict = json.loads(highlight_rows[0]["value"])
    assert (payload_dict["x"], payload_dict["y"]) == (5, 3)
    assert payload_dict["flips"] == 4
    assert payload_dict["slots"] == [0, 1]


# ---------- end-to-end via file:// URIs ----------


def _setup_inputs(
    tmp_path: Path,
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
    include_metadata: bool = True,
    bundle_status: str = "success",
) -> tuple[dict[str, str], Path]:
    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(
        fixtures.make_bundle_zip(
            status=bundle_status,
            results=results,
            replay=replay,
            metadata=metadata,
            include_metadata=include_metadata,
        )
    )
    out_path = tmp_path / "report.zip"
    env = {
        "COGAME_EPISODE_BUNDLE_URI": bundle_path.as_uri(),
        "COGAME_REPORT_URI": out_path.as_uri(),
    }
    return env, out_path


def _invoke_run(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    par.run(par.load_reporter_inputs())


def test_run_happy_path_writes_valid_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path)
    _invoke_run(monkeypatch, env)
    payload = out_path.read_bytes()
    files = _extract(payload)
    assert set(files.keys()) == _EXPECTED_ENTRIES
    stats = json.loads(files["stats.json"])
    assert stats["winner_slot"] == 0


def test_run_is_byte_identical_on_rerun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D12 determinism: two runs over identical inputs must produce identical
    bytes. Holds within one pyarrow version (the requirements.txt pin)."""
    env, out_path = _setup_inputs(tmp_path)
    _invoke_run(monkeypatch, env)
    first = out_path.read_bytes()
    out_path.unlink()
    _invoke_run(monkeypatch, env)
    second = out_path.read_bytes()
    assert first == second


def test_run_malformed_replay_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_replay = fixtures.make_replay()
    del bad_replay["config"]
    env, out_path = _setup_inputs(tmp_path, replay=bad_replay)
    with pytest.raises(ValidationError):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_run_malformed_results_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path, results=fixtures.make_results_missing_field())
    with pytest.raises(ValidationError):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_run_falls_back_to_defaults_when_metadata_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bundle's `metadata` token is optional. When absent, the reporter
    populates `episode_id` from the inner manifest's `ereq_id` and lets
    `variant_id` / `duration_seconds` / `policy_name` fall back to defaults."""
    env, out_path = _setup_inputs(tmp_path, include_metadata=False)
    _invoke_run(monkeypatch, env)
    stats = json.loads(_extract(out_path.read_bytes())["stats.json"])
    assert stats["episode_id"] == "ereq_test_001"
    assert stats["variant_id"] == "unknown"
    assert stats["duration_seconds"] is None
    # No metadata.players -> policy_name falls back to "Slot N".
    assert stats["slots"][0]["policy_name"] == "Slot 0"


def test_run_failed_bundle_status_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bundle whose inner manifest reports `status: "failed"` must surface
    a non-zero exit; the reporter cannot operate on a failed episode."""
    env, out_path = _setup_inputs(tmp_path, bundle_status="failed")
    with pytest.raises(RuntimeError, match="failed"):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_load_reporter_inputs_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in (
        "COGAME_EPISODE_BUNDLE_URI",
        "COGAME_REPORT_URI",
    ):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KeyError):
        par.load_reporter_inputs()
