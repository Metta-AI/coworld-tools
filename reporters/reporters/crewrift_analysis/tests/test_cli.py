"""End-to-end CLI tests over on-disk synthetic JSONL."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

from crewrift_analysis.cli import main  # noqa: E402
from crewrift_analysis.testing import synthetic_lines  # noqa: E402


@pytest.fixture
def episode_dir(tmp_path):
    for name in ("ep1", "ep2"):
        (tmp_path / f"{name}.jsonl").write_text("\n".join(synthetic_lines()))
    return tmp_path


def test_contrast_table(episode_dir, tmp_path):
    out = tmp_path / "viz"
    assert main(["contrast-table", str(episode_dir), "--out", str(out)]) == 0
    assert (out / "contrast_table.png").exists()


def test_vote_ladder(episode_dir, tmp_path):
    out = tmp_path / "viz"
    assert main(["vote-ladder", str(episode_dir / "ep1.jsonl"), "--out", str(out)]) == 0
    assert (out / "vote_ladder_ep1.png").exists()


def test_missed_blend_defaults_to_first_imposter(episode_dir, tmp_path, capsys):
    out = tmp_path / "viz"
    assert main(["missed-blend", str(episode_dir / "ep1.jsonl"), "--out", str(out)]) == 0
    assert "using imposter slot 0 (red)" in capsys.readouterr().out
    assert (out / "missed_blend_ep1_slot0.png").exists()


def test_missed_blend_explicit_slot(episode_dir, tmp_path):
    out = tmp_path / "viz"
    assert main(["missed-blend", str(episode_dir / "ep1.jsonl"), "--slot", "2", "--out", str(out)]) == 0
    assert (out / "missed_blend_ep1_slot2.png").exists()


def test_fog_of_war(episode_dir, tmp_path):
    out = tmp_path / "viz"
    args = ["fog-of-war", str(episode_dir / "ep1.jsonl"), "--observer", "1", "--phases", "1", "--out", str(out)]
    assert main(args) == 0
    assert (out / "fog_of_war_ep1_obs1.png").exists()


def test_empty_directory_fails(tmp_path, capsys):
    assert main(["contrast-table", str(tmp_path), "--out", str(tmp_path)]) == 1
    assert "no files match" in capsys.readouterr().err


def test_missing_episode_file_fails(tmp_path, capsys):
    assert main(["vote-ladder", str(tmp_path / "nope.jsonl"), "--out", str(tmp_path)]) == 1
    assert "error:" in capsys.readouterr().err


def test_unknown_observer_fails(episode_dir, tmp_path, capsys):
    args = ["fog-of-war", str(episode_dir / "ep1.jsonl"), "--observer", "99", "--out", str(tmp_path)]
    assert main(args) == 1
    assert "unknown observer" in capsys.readouterr().err
