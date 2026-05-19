"""Test suite for paint_arena_summarizer.

Covers pure-function envelope construction (build_envelope, build_stats) plus
end-to-end main() runs against file:// URIs, exercising the failure-mode table
in DESIGN.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import paint_arena_summarizer as par
from tests import fixtures


# ---------- pure build_envelope / build_stats ----------


def test_happy_path_envelope_shape() -> None:
    env = par.build_envelope(
        results=fixtures.make_results_happy(),
        metadata=fixtures.make_metadata(),
        manifest=fixtures.make_manifest(),
    )
    d = env.to_dict()
    assert d["version"] == "1"
    assert [a["id"] for a in d["artifacts"]] == ["summary", "stats"]
    assert d["artifacts"][0]["content_type"] == "text/markdown"
    assert d["artifacts"][1]["content_type"] == "application/json"
    par.validate_envelope(d)


def test_envelope_key_order_is_intentional_not_alphabetical() -> None:
    """Regression: serialized envelope must follow contract key order, not sort_keys.

    Top-level (version, artifacts); per-artifact (id, content_type, content);
    the artifact list itself in primary-first order. The first artifact is
    the primary one by D3 convention -- accidental sort_keys reintroduction
    would clobber this and break the contract's primary-artifact rule.
    """
    env = par.build_envelope(
        results=fixtures.make_results_happy(),
        metadata=fixtures.make_metadata(),
        manifest=fixtures.make_manifest(),
    )
    payload = env.to_json_bytes()
    text = payload.decode("utf-8")
    # Top-level: "version" appears before "artifacts".
    assert text.index('"version"') < text.index('"artifacts"')
    # Per artifact: "id" before "content_type" before "content".
    first_id = text.index('"id"')
    first_ct = text.index('"content_type"', first_id)
    first_c = text.index('"content"', first_ct)
    assert first_id < first_ct < first_c
    # Artifact list order: 'summary' before 'stats'.
    assert text.index('"summary"') < text.index('"stats"')
    # Round-tripped dict keys also follow the contract order.
    parsed = json.loads(payload)
    assert list(parsed.keys()) == ["version", "artifacts"]
    assert list(parsed["artifacts"][0].keys())[:3] == ["id", "content_type", "content"]


def test_happy_path_stats_numbers() -> None:
    stats = par.build_stats(
        results=fixtures.make_results_happy(),
        metadata=fixtures.make_metadata(),
        variant=fixtures.make_manifest()["variants"][0],
    )
    assert stats["episode_id"] == "ep_abc123"
    assert stats["variant_id"] == "default"
    assert stats["grid"] == {"width": 12, "height": 8, "total_tiles": 96}
    assert stats["ticks"] == 100
    assert stats["unpainted_tiles"] == 11  # 96 - 47 - 38
    assert stats["winner_slot"] == 0
    assert stats["margin_tiles"] == 9
    assert stats["tie"] is False
    assert [s["slot"] for s in stats["slots"]] == [0, 1]
    assert stats["slots"][0]["policy_name"] == "champion-v3"
    assert stats["slots"][0]["painted_tiles"] == 47
    assert stats["slots"][0]["share_pct"] == pytest.approx(48.96, abs=0.01)


def test_zero_paint_episode() -> None:
    env = par.build_envelope(
        results=fixtures.make_results_zero_paint(),
        metadata=fixtures.make_metadata(),
        manifest=fixtures.make_manifest(),
    )
    d = env.to_dict()
    stats = d["artifacts"][1]["content"]
    assert stats["winner_slot"] is None
    assert stats["tie"] is False
    assert stats["margin_tiles"] == 0
    assert stats["unpainted_tiles"] == 96
    summary = d["artifacts"][0]["content"]
    assert "no tiles" in summary.lower()


def test_tie_episode() -> None:
    env = par.build_envelope(
        results=fixtures.make_results_tie(),
        metadata=fixtures.make_metadata(),
        manifest=fixtures.make_manifest(),
    )
    d = env.to_dict()
    stats = d["artifacts"][1]["content"]
    assert stats["winner_slot"] is None
    assert stats["tie"] is True
    assert stats["margin_tiles"] == 0
    summary = d["artifacts"][0]["content"]
    assert "tied" in summary.lower()


def test_policy_name_falls_back_to_slot_label() -> None:
    metadata = fixtures.make_metadata()
    metadata["players"][1]["policy_name"] = None
    env = par.build_envelope(
        results=fixtures.make_results_happy(),
        metadata=metadata,
        manifest=fixtures.make_manifest(),
    )
    stats = env.to_dict()["artifacts"][1]["content"]
    assert stats["slots"][1]["policy_name"] == "Slot 1"


def test_lookup_variant_missing_raises() -> None:
    metadata = fixtures.make_metadata(variant_id="not-a-real-variant")
    with pytest.raises(KeyError):
        par.build_envelope(
            results=fixtures.make_results_happy(),
            metadata=metadata,
            manifest=fixtures.make_manifest(),
        )


def test_envelope_self_validation_rejects_bad_shape() -> None:
    with pytest.raises(ValueError):
        par.validate_envelope({"version": "1"})  # missing artifacts
    with pytest.raises(ValueError):
        par.validate_envelope(
            {"version": "1", "artifacts": [{"id": "x", "content_type": "text/plain"}]}
        )  # artifact missing 'content'
    with pytest.raises(ValueError):
        par.validate_envelope(
            {
                "version": "1",
                "artifacts": [
                    {"id": "a", "content_type": "text/plain", "content": ""},
                    {"id": "a", "content_type": "text/plain", "content": ""},
                ],
            }
        )  # duplicate ids


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


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_main_happy_path_writes_valid_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path)
    _set_env(monkeypatch, env)
    assert par.main() == 0
    payload = json.loads(out_path.read_text())
    par.validate_envelope(payload)
    assert payload["artifacts"][1]["content"]["winner_slot"] == 0


def test_main_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env, out_path = _setup_inputs(tmp_path)
    _set_env(monkeypatch, env)
    assert par.main() == 0
    first = out_path.read_bytes()
    out_path.unlink()
    assert par.main() == 0
    second = out_path.read_bytes()
    assert first == second


def test_main_missing_variant_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env, out_path = _setup_inputs(
        tmp_path, metadata=fixtures.make_metadata(variant_id="ghost")
    )
    _set_env(monkeypatch, env)
    assert par.main() == 1
    assert not out_path.exists()
    assert "ghost" in capsys.readouterr().err


def test_main_malformed_results_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path, results=fixtures.make_results_missing_field())
    _set_env(monkeypatch, env)
    assert par.main() == 1
    assert not out_path.exists()


def test_main_unparseable_results_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, out_path = _setup_inputs(tmp_path)
    # Corrupt the results file after _setup_inputs wrote it.
    bad_results = tmp_path / "results.json"
    bad_results.write_text("{not valid json")
    _set_env(monkeypatch, env)
    assert par.main() == 1
    assert not out_path.exists()


def test_main_missing_env_var_exits_nonzero(
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
    assert par.main() == 1
