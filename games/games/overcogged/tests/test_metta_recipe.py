import pytest

import overcogged
import overcogged.recipe as recipe
from overcogged.rendering import default_render_mode


def test_default_render_mode_prefers_gui_with_display() -> None:
    assert default_render_mode(display_available=True, interactive=False) == "gui"


def test_default_render_mode_uses_unicode_for_interactive_headless_terminal() -> None:
    assert default_render_mode(display_available=False, interactive=True) == "unicode"


def test_default_render_mode_uses_none_for_noninteractive_headless_session() -> None:
    assert default_render_mode(display_available=False, interactive=False) == "none"


def test_standalone_package_exports_metta_play_recipe() -> None:
    try:
        from metta.tools.play import PlayTool
    except (ImportError, SystemExit) as exc:
        pytest.skip(f"metta play integration unavailable in this environment: {exc}")

    tool = overcogged.play(max_steps=120, render="log")

    assert isinstance(tool, PlayTool)
    assert tool.policy_uri == "metta://policy/overcogged.agent.overcogged_agent.policy.OvercookedPolicy"
    assert tool.sim.env.game.num_agents == 4
    assert tool.max_steps == 120
    assert tool.autostart is True
    assert tool.render == "log"


def test_metta_play_recipe_uses_auto_render_default(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        from metta.tools.play import PlayTool
    except (ImportError, SystemExit) as exc:
        pytest.skip(f"metta play integration unavailable in this environment: {exc}")

    monkeypatch.setattr(recipe, "auto_render_mode", lambda: "none")

    tool = recipe.play(max_steps=120)

    assert isinstance(tool, PlayTool)
    assert tool.render == "none"
