from pathlib import Path

import pytest

import amongcogs


def _has_repo_root() -> bool:
    return any((path / ".repo-root").exists() for path in (Path.cwd(), *Path.cwd().parents))


pytestmark = pytest.mark.skipif(not _has_repo_root(), reason="requires running from a Metta repo")


def test_standalone_package_exports_metta_play_recipe() -> None:
    from metta.tools.play import PlayTool

    tool = amongcogs.play(num_agents=10, max_steps=222)

    assert isinstance(tool, PlayTool)
    assert tool.sim.suite == "amongcogs"
    assert tool.sim.env.game.num_agents == 10
    assert tool.policy_uri == "metta://policy/amongcogs_agent"
    assert tool.max_steps == 222
    assert tool.render == "none"
    assert tool.autostart is True
