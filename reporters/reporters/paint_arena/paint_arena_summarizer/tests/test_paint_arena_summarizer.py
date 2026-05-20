"""Test suite for paint_arena_summarizer.

Covers pure-function envelope construction (build_envelope, build_stats) plus
end-to-end run() invocations against file:// URIs, exercising the failure-mode
table in DESIGN.md. The reporter raises on every documented failure mode
rather than returning an exit code; the entry-point lets the exception
propagate so the process crashes with a non-zero status.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import paint_arena_summarizer as par
from tests import fixtures


# ---------- helpers ----------


def _models(
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> tuple[par.PaintArenaResults, par.EpisodeMetadata, par.PartialManifest]:
    return (
        par.PaintArenaResults.model_validate(results or fixtures.make_results_happy()),
        par.EpisodeMetadata.model_validate(metadata or fixtures.make_metadata()),
        par.PartialManifest.model_validate(manifest or fixtures.make_manifest()),
    )


# ---------- pure build_envelope / build_stats ----------


def test_happy_path_envelope_shape() -> None:
    results, metadata, manifest = _models()
    env = par.build_envelope(results=results, metadata=metadata, manifest=manifest)
    assert env.version == "1"
    assert [a.id for a in env.artifacts] == ["summary", "stats"]
    assert env.artifacts[0].content_type == "text/markdown"
    assert env.artifacts[1].content_type == "application/json"


def test_envelope_key_order_is_intentional_not_alphabetical() -> None:
    """Regression: serialized envelope must follow contract key order, not sort_keys.

    Top-level (version, artifacts); per-artifact (id, content_type, content);
    the artifact list itself in primary-first order. The first artifact is
    the primary one by D3 convention -- accidental sort_keys reintroduction
    would clobber this and break the contract's primary-artifact rule.
    """
    results, metadata, manifest = _models()
    env = par.build_envelope(results=results, metadata=metadata, manifest=manifest)
    payload = env.to_json_bytes()
    text = payload.decode("utf-8")
    assert text.index('"version"') < text.index('"artifacts"')
    first_id = text.index('"id"')
    first_ct = text.index('"content_type"', first_id)
    first_c = text.index('"content"', first_ct)
    assert first_id < first_ct < first_c
    assert text.index('"summary"') < text.index('"stats"')
    parsed = json.loads(payload)
    assert list(parsed.keys()) == ["version", "artifacts"]
    assert list(parsed["artifacts"][0].keys())[:3] == ["id", "content_type", "content"]


def test_happy_path_stats_numbers() -> None:
    results, metadata, manifest = _models()
    variant = next(v for v in manifest.variants if v.id == metadata.variant_id)
    stats = par.build_stats(results=results, metadata=metadata, variant=variant)
    assert stats.episode_id == "ep_abc123"
    assert stats.variant_id == "default"
    assert stats.grid.width == 12
    assert stats.grid.height == 8
    assert stats.grid.total_tiles == 96
    assert stats.ticks == 100
    assert stats.unpainted_tiles == 11  # 96 - 47 - 38
    assert stats.winner_slot == 0
    assert stats.margin_tiles == 9
    assert stats.tie is False
    assert [s.slot for s in stats.slots] == [0, 1]
    assert stats.slots[0].policy_name == "champion-v3"
    assert stats.slots[0].painted_tiles == 47
    assert stats.slots[0].share_pct == pytest.approx(48.96, abs=0.01)


def test_zero_paint_episode() -> None:
    results, metadata, manifest = _models(results=fixtures.make_results_zero_paint())
    env = par.build_envelope(results=results, metadata=metadata, manifest=manifest)
    stats = env.artifacts[1].content
    assert stats["winner_slot"] is None
    assert stats["tie"] is False
    assert stats["margin_tiles"] == 0
    assert stats["unpainted_tiles"] == 96
    summary = env.artifacts[0].content
    assert "no tiles" in summary.lower()


def test_tie_episode() -> None:
    results, metadata, manifest = _models(results=fixtures.make_results_tie())
    env = par.build_envelope(results=results, metadata=metadata, manifest=manifest)
    stats = env.artifacts[1].content
    assert stats["winner_slot"] is None
    assert stats["tie"] is True
    assert stats["margin_tiles"] == 0
    summary = env.artifacts[0].content
    assert "tied" in summary.lower()


def test_policy_name_falls_back_to_slot_label() -> None:
    metadata_dict = fixtures.make_metadata()
    metadata_dict["players"][1]["policy_name"] = None
    results, metadata, manifest = _models(metadata=metadata_dict)
    env = par.build_envelope(results=results, metadata=metadata, manifest=manifest)
    stats = env.artifacts[1].content
    assert stats["slots"][1]["policy_name"] == "Slot 1"


def test_lookup_variant_missing_raises() -> None:
    results, metadata, manifest = _models(
        metadata=fixtures.make_metadata(variant_id="not-a-real-variant"),
    )
    with pytest.raises(KeyError):
        par.build_envelope(results=results, metadata=metadata, manifest=manifest)


def test_envelope_model_rejects_bad_shape() -> None:
    """Pydantic enforces structural validity at Envelope/Artifact construction time."""
    with pytest.raises(ValidationError):
        # Missing top-level 'version'.
        par.Envelope.model_validate({"artifacts": []})
    with pytest.raises(ValidationError):
        # Artifact missing required 'content_type' and 'content'.
        par.Envelope.model_validate(
            {"version": "1", "artifacts": [{"id": "x"}]}
        )


def test_envelope_rejects_duplicate_artifact_ids() -> None:
    """Producer-side contract: artifact ids within an envelope must be unique."""
    with pytest.raises(ValidationError, match="duplicate artifact id"):
        par.Envelope.model_validate(
            {
                "version": "1",
                "artifacts": [
                    {"id": "a", "content_type": "text/plain", "content": ""},
                    {"id": "a", "content_type": "text/plain", "content": ""},
                ],
            }
        )


# ---------- end-to-end via file:// URIs ----------


def _write_json(path: Path, obj: Any) -> str:
    path.write_text(json.dumps(obj))
    return path.as_uri()


def _setup_inputs(
    tmp_path: Path,
    *,
    results: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> tuple[dict[str, str], Path]:
    results_uri = _write_json(tmp_path / "results.json", results or fixtures.make_results_happy())
    metadata_uri = _write_json(tmp_path / "metadata.json", metadata or fixtures.make_metadata())
    manifest_uri = _write_json(tmp_path / "manifest.json", manifest or fixtures.make_manifest())
    out_path = tmp_path / "report.json"
    env = {
        "COGAME_RESULTS_URI": results_uri,
        "COGAME_EPISODE_METADATA_URI": metadata_uri,
        "COGAME_MANIFEST_URI": manifest_uri,
        "COGAME_REPORT_OUTPUT_URI": out_path.as_uri(),
        "COGAME_REPORTER_ID": "paint-arena-summarizer",
    }
    return env, out_path


def _invoke_run(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    par.run(par.load_reporter_inputs())


def test_run_happy_path_writes_valid_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path)
    _invoke_run(monkeypatch, env)
    payload = json.loads(out_path.read_text())
    parsed = par.Envelope.model_validate(payload)
    assert parsed.artifacts[1].content["winner_slot"] == 0


def test_run_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, out_path = _setup_inputs(tmp_path)
    _invoke_run(monkeypatch, env)
    first = out_path.read_bytes()
    out_path.unlink()
    _invoke_run(monkeypatch, env)
    second = out_path.read_bytes()
    assert first == second


def test_run_missing_variant_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(
        tmp_path, metadata=fixtures.make_metadata(variant_id="ghost")
    )
    with pytest.raises(KeyError, match="ghost"):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_run_malformed_results_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path, results=fixtures.make_results_missing_field())
    with pytest.raises(ValidationError):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_run_unparseable_results_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path)
    # Corrupt the results file after _setup_inputs wrote it.
    (tmp_path / "results.json").write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        _invoke_run(monkeypatch, env)
    assert not out_path.exists()


def test_load_reporter_inputs_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in (
        "COGAME_RESULTS_URI",
        "COGAME_EPISODE_METADATA_URI",
        "COGAME_MANIFEST_URI",
        "COGAME_REPORT_OUTPUT_URI",
        "COGAME_REPORTER_ID",
    ):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(KeyError):
        par.load_reporter_inputs()