"""Phase 2 tests: aggregates path (verdict + scoreboard from results.json).

Phase 2 of among_them_summarizer adds:
- `.bitreplay` header-only parser (magic + version + game-name + version +
  timestamp + configJson; refuses unknown magic / version != 3).
- Verdict derivation (Imposter / Crewmate / Draw).
- Per-slot stats including the `likely_dead` inference.
- Meetings count estimate (bounded; max across slots).
- HTML rendering (header + verdict band + scoreboard table).
- stats.json (full per-slot detail, phase-2 placeholders for replay-derived
  fields).
- events.parquet with three keys: game_config, player_summary, game_result.

The full zip now has four entries: summary.html (rendered), stats.json,
events.parquet, render.txt. render.txt lists summary.html.
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

import among_them_summarizer as ats
import fixtures  # see conftest.py — tests/ is added to sys.path


_RENDERABLE_EXTS = {".md", ".txt", ".html", ".htm"}
_PINNED_MTIME = (1980, 1, 1, 0, 0, 0)
_EXPECTED_ENTRIES = {"summary.html", "stats.json", "events.parquet", "render.txt"}


# ---------- helpers ----------


def _open_zip(payload: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(payload))


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


def _build_zip(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    replay_bytes: bytes | None = None,
) -> bytes:
    return ats.build_zip_bytes(
        results=ats.AmongThemResults.model_validate(
            results or fixtures.make_results_crewmate_win()
        ),
        metadata=ats.EpisodeMetadata.model_validate(
            metadata or fixtures.make_metadata()
        ),
        replay_bytes=replay_bytes
        if replay_bytes is not None
        else fixtures.make_replay_bytes(),
    )


# ---------- header parser ----------


def test_parse_replay_header_returns_config() -> None:
    cfg_in = fixtures.make_game_config(imposterCount=3, tasksPerPlayer=4)
    blob = fixtures.make_replay_bytes(config=cfg_in)
    parsed = ats.parse_bitreplay_header(blob)
    assert parsed.game_name == "among_them"
    assert parsed.format_version == 3
    assert parsed.config.imposter_count == 3
    assert parsed.config.tasks_per_player == 4


def test_parse_replay_header_rejects_bad_magic() -> None:
    blob = fixtures.make_replay_bytes(magic=b"NOPEWORD")
    with pytest.raises(ValueError, match="magic"):
        ats.parse_bitreplay_header(blob)


def test_parse_replay_header_rejects_bad_version() -> None:
    blob = fixtures.make_replay_bytes(format_version=2)
    with pytest.raises(ValueError, match="format version"):
        ats.parse_bitreplay_header(blob)


def test_parse_replay_header_rejects_wrong_game() -> None:
    blob = fixtures.make_replay_bytes(game_name="not_among_them")
    with pytest.raises(ValueError, match="game name"):
        ats.parse_bitreplay_header(blob)


def test_parse_replay_header_rejects_truncated() -> None:
    blob = fixtures.make_replay_bytes()[:10]  # cut mid-header
    with pytest.raises(ValueError):
        ats.parse_bitreplay_header(blob)


# ---------- verdict derivation ----------


def test_derive_verdict_imposter_win() -> None:
    results = ats.AmongThemResults.model_validate(fixtures.make_results_imposter_win())
    verdict = ats.derive_verdict(results)
    assert verdict.winner_side == "Imposter"
    assert verdict.time_limit_reached is False
    assert verdict.any_winner is True


def test_derive_verdict_crewmate_win() -> None:
    results = ats.AmongThemResults.model_validate(fixtures.make_results_crewmate_win())
    verdict = ats.derive_verdict(results)
    assert verdict.winner_side == "Crewmate"
    assert verdict.any_winner is True


def test_derive_verdict_draw() -> None:
    results = ats.AmongThemResults.model_validate(fixtures.make_results_draw())
    verdict = ats.derive_verdict(results)
    assert verdict.winner_side == "Draw"
    assert verdict.time_limit_reached is True
    assert verdict.any_winner is False


# ---------- slot stats ----------


@pytest.mark.parametrize("n_slots", [4, 8, 16])
def test_build_slot_stats_generalized(n_slots: int) -> None:
    results = fixtures.make_results(slots=n_slots, winner_side="Crewmate")
    metadata = fixtures.make_metadata(slots=n_slots)
    config = ats.GameConfig.model_validate(fixtures.make_game_config())
    slots = ats.build_slot_stats(
        ats.AmongThemResults.model_validate(results),
        ats.EpisodeMetadata.model_validate(metadata),
        config,
    )
    assert len(slots) == n_slots
    for i, s in enumerate(slots):
        assert s.slot == i
        # Phase 2: replay-derived fields are placeholders.
        assert s.in_game_name is None
        assert s.joined_tick == 0
        assert s.left_tick is None
        assert s.input_press_total is None


def test_slot_stats_tasks_assigned_only_for_crew() -> None:
    results = fixtures.make_results(slots=8, winner_side="Crewmate")
    metadata = fixtures.make_metadata(slots=8)
    config = ats.GameConfig.model_validate(fixtures.make_game_config(tasksPerPlayer=8))
    slots = ats.build_slot_stats(
        ats.AmongThemResults.model_validate(results),
        ats.EpisodeMetadata.model_validate(metadata),
        config,
    )
    for s in slots:
        if s.role == "Crewmate":
            assert s.tasks_assigned == 8
        elif s.role == "Imposter":
            assert s.tasks_assigned == 0


def test_slot_stats_policy_name_fallback() -> None:
    """When metadata's policy_name is null, the slot's policy_name
    falls back to the results' `names[i]`, then to 'Slot N'."""
    results = fixtures.make_results(slots=2, imposter_slots=(0,))
    results["names"] = ["custom-name", None]
    metadata = fixtures.make_metadata(slots=2, policy_names=[None, None])
    config = ats.GameConfig.model_validate(fixtures.make_game_config())
    slots = ats.build_slot_stats(
        ats.AmongThemResults.model_validate(results),
        ats.EpisodeMetadata.model_validate(metadata),
        config,
    )
    assert slots[0].policy_name == "custom-name"  # from results.names
    assert slots[1].policy_name == "Slot 1"  # final fallback


# ---------- zip-shape + render.txt ----------


def test_build_zip_bytes_has_four_entries() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        assert set(zf.namelist()) == _EXPECTED_ENTRIES


def test_render_txt_lists_summary_html_only() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        render_txt = zf.read("render.txt").decode("utf-8")
    assert render_txt == "summary.html\n"


def test_render_txt_entries_have_renderable_extensions() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        render_txt = zf.read("render.txt").decode("utf-8")
    for line in render_txt.splitlines():
        line = line.strip()
        if not line:
            continue
        ext = Path(line).suffix
        assert ext in _RENDERABLE_EXTS, f"{line!r} has non-renderable extension {ext!r}"


def test_zip_entries_have_pinned_mtime() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        for info in zf.infolist():
            assert info.date_time == _PINNED_MTIME, (info.filename, info.date_time)


# ---------- HTML ----------


def test_html_contains_every_display_name() -> None:
    metadata = fixtures.make_metadata(
        slots=8, policy_names=[f"policy_{i}" for i in range(8)]
    )
    payload = _build_zip(metadata=metadata)
    with _open_zip(payload) as zf:
        html = zf.read("summary.html").decode("utf-8")
    for i in range(8):
        assert f"policy_{i}" in html


def test_html_is_self_contained() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        html = zf.read("summary.html").decode("utf-8")
    assert "<script" not in html.lower()
    assert "<link" not in html.lower()


def test_html_verdict_band_matches_outcome() -> None:
    cases = [
        (fixtures.make_results_imposter_win(), "Imposters win"),
        (fixtures.make_results_crewmate_win(), "Crewmates win"),
        (fixtures.make_results_draw(), "Draw"),
    ]
    for results, expected in cases:
        payload = _build_zip(results=results)
        with _open_zip(payload) as zf:
            html = zf.read("summary.html").decode("utf-8")
        assert expected in html, f"missing {expected!r} for {results['win']}"


# ---------- stats.json ----------


def test_stats_json_shape() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        stats = json.loads(zf.read("stats.json"))
    assert stats["episode_id"] == "ep_abc123"
    assert stats["variant_id"] == "default"
    assert stats["replay_fps"] == 24
    assert stats["verdict"]["winner_side"] == "Crewmate"
    assert isinstance(stats["slots"], list)
    assert len(stats["slots"]) == 8
    assert stats["config"]["imposter_count"] == 2


# ---------- events.parquet ----------


def test_events_parquet_emits_three_keys() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    keys = {r["key"] for r in rows}
    assert keys == {"game_config", "player_summary", "game_result"}


def test_events_parquet_player_summary_one_per_slot() -> None:
    payload = _build_zip()
    with _open_zip(payload) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    player_summary_rows = [r for r in rows if r["key"] == "player_summary"]
    assert len(player_summary_rows) == 8
    assert {r["player"] for r in player_summary_rows} == set(range(8))


def test_events_parquet_game_result_payload() -> None:
    payload = _build_zip(results=fixtures.make_results_imposter_win())
    with _open_zip(payload) as zf:
        rows = _read_parquet_rows(zf.read("events.parquet"))
    [gr] = [r for r in rows if r["key"] == "game_result"]
    assert gr["player"] == -1
    assert gr["value"]["winner_side"] == "Imposter"
    assert gr["value"]["any_winner"] is True


# ---------- end-to-end run() ----------


def test_run_end_to_end(tmp_path: Path) -> None:
    results_path = tmp_path / "results.json"
    metadata_path = tmp_path / "metadata.json"
    replay_path = tmp_path / "replay.bitreplay"
    output_path = tmp_path / "report.zip"
    results_path.write_text(json.dumps(fixtures.make_results_crewmate_win()))
    metadata_path.write_text(json.dumps(fixtures.make_metadata()))
    replay_path.write_bytes(fixtures.make_replay_bytes())
    inputs = ats.ReporterInputs(
        results_uri=results_path.as_uri(),
        replay_uri=replay_path.as_uri(),
        episode_metadata_uri=metadata_path.as_uri(),
        report_output_uri=output_path.as_uri(),
        reporter_id="among-them-summarizer",
    )
    ats.run(inputs)
    with zipfile.ZipFile(output_path) as zf:
        assert set(zf.namelist()) == _EXPECTED_ENTRIES


def test_results_validation_rejects_missing_required() -> None:
    """`scores` is the only required field in the results schema."""
    with pytest.raises(ValidationError):
        ats.AmongThemResults.model_validate({})


def test_run_is_byte_identical_on_rerun(tmp_path: Path) -> None:
    """Two invocations over identical inputs produce byte-identical zips.

    Phase 6 is the canonical determinism phase, but the property holds
    now and is cheap to assert.
    """

    def _do_run(out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        results_path = out_dir / "results.json"
        metadata_path = out_dir / "metadata.json"
        replay_path = out_dir / "replay.bitreplay"
        output_path = out_dir / "report.zip"
        results_path.write_text(json.dumps(fixtures.make_results_crewmate_win()))
        metadata_path.write_text(json.dumps(fixtures.make_metadata()))
        replay_path.write_bytes(fixtures.make_replay_bytes())
        inputs = ats.ReporterInputs(
            results_uri=results_path.as_uri(),
            replay_uri=replay_path.as_uri(),
            episode_metadata_uri=metadata_path.as_uri(),
            report_output_uri=output_path.as_uri(),
            reporter_id="among-them-summarizer",
        )
        ats.run(inputs)
        return output_path

    a = _do_run(tmp_path / "a").read_bytes()
    b = _do_run(tmp_path / "b").read_bytes()
    assert a == b
