import pytest

import werecog


def test_standalone_package_exports_metta_play_recipe() -> None:
    try:
        from metta.tools.play import PlayTool
    except (ImportError, SystemExit) as exc:
        pytest.skip(f"metta play integration unavailable in this environment: {exc}")

    tool = werecog.play(max_steps=120)

    assert isinstance(tool, PlayTool)
    assert tool.policy_uri == "metta://policy/werecog"
    assert tool.sim.suite == "werecog"
    assert tool.sim.env.game.num_agents == 16
    assert tool.max_steps == 120
    assert tool.render == "none"
    assert tool.autostart is True
