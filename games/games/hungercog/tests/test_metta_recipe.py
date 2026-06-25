import pytest

import hungercog


def test_standalone_package_exports_metta_play_recipe() -> None:
    try:
        from metta.tools.play import PlayTool
    except (ImportError, SystemExit) as exc:
        pytest.skip(f"metta play integration unavailable in this environment: {exc}")

    tool = hungercog.play(max_steps=120)

    assert isinstance(tool, PlayTool)
    assert tool.policy_uri == "metta://policy/hungercog.agent.hunger_agent.policy.HungerPolicy"
    assert tool.sim.suite == "hungercog"
    assert tool.sim.env.game.num_agents == 40
    assert tool.max_steps == 120
    assert tool.render == "none"
    assert tool.autostart is True
