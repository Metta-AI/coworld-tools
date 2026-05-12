from __future__ import annotations

from pathlib import Path

from cogames_rl_researcher.json_io import read_json
from cogames_rl_researcher.pickup import PickupConfig, run_pickup

from tests.test_startup import _write_fake_cogames


def test_pickup_workflow_writes_result_and_replays(tmp_path: Path, monkeypatch) -> None:
    fake_cogames = tmp_path / "fake_cogames.py"
    _write_fake_cogames(fake_cogames)

    state_path = tmp_path / "state.json"
    monkeypatch.setenv("FAKE_COGAMES_STATE", str(state_path))

    result = run_pickup(
        PickupConfig(
            policy="class=greedy",
            pool=["class=random"],
            output_root=tmp_path / "artifacts",
            cogames_bin=str(fake_cogames),
            detect_idle_seconds=10,
            max_step_seconds=30,
        )
    )

    assert result.status == "success"
    assert (Path(result.run_dir) / "pickup_result.json").exists()
    assert (Path(result.run_dir) / "pickup_diagnosis.md").exists()
    assert Path(result.replay_dir).exists()

    state = read_json(state_path)
    assert state["pickup_count"] == 1
