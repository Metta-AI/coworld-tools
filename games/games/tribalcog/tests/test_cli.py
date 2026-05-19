"""Tests for the tribal_village CLI (typer app)."""

import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from typer.testing import CliRunner

from tests.conftest import requires_nim_library
import tribal_village_env
from tribal_village_env import cogames as cogames_module
import tribal_village_env.cli as cli
import tribal_village_env.recipe as recipe
from tribal_village_env.cli import app

runner = CliRunner()


def _install_fake_metta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    metta_module = ModuleType("metta")
    common_module = ModuleType("metta.common")
    tool_module = ModuleType("metta.common.tool")
    util_module = ModuleType("metta.common.util")
    fs_module = ModuleType("metta.common.util.fs")

    class Tool:
        pass

    tool_module.Tool = Tool
    fs_module.get_repo_root = lambda: tmp_path
    metta_module.common = common_module
    common_module.tool = tool_module
    common_module.util = util_module
    util_module.fs = fs_module

    monkeypatch.setitem(sys.modules, "metta", metta_module)
    monkeypatch.setitem(sys.modules, "metta.common", common_module)
    monkeypatch.setitem(sys.modules, "metta.common.tool", tool_module)
    monkeypatch.setitem(sys.modules, "metta.common.util", util_module)
    monkeypatch.setitem(sys.modules, "metta.common.util.fs", fs_module)


class TestAppCreation:
    """Verify the Typer app can be created without errors."""

    def test_app_exists(self):
        assert app is not None

    def test_cogames_module_exports_register_cli(self):
        assert callable(cogames_module.register_cli)

    def test_package_exports_metta_play_recipe(self):
        assert tribal_village_env.play is recipe.play

    def test_app_has_play_command(self):
        command_names = [cmd.name for cmd in app.registered_commands]
        assert "play" in command_names


class TestPlayHelp:
    """Verify --help flag works."""

    def test_play_help(self):
        result = runner.invoke(app, ["play", "--help"])
        assert result.exit_code == 0
        assert "render" in result.output.lower()

    def test_root_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0


class TestInvalidRenderMode:
    """Verify invalid render mode produces error exit."""

    def test_invalid_render_mode(self):
        result = runner.invoke(app, ["play", "--render", "invalid"])
        assert result.exit_code != 0


class TestPlayDispatch:
    """Verify render-mode-specific startup work."""

    def test_play_gui_skips_nim_library_refresh(self, monkeypatch):
        gui_calls: list[str] = []

        monkeypatch.setattr(
            cli, "ensure_nim_library_current", lambda: gui_calls.append("lib")
        )
        monkeypatch.setattr(
            cli,
            "_run_gui",
            lambda **_: gui_calls.append("gui"),
        )

        result = runner.invoke(app, ["play", "--render", "gui"])
        assert result.exit_code == 0
        assert gui_calls == ["gui"]

    def test_play_ansi_refreshes_nim_library(self, monkeypatch):
        ansi_calls: list[str] = []

        monkeypatch.setattr(
            cli, "ensure_nim_library_current", lambda: ansi_calls.append("lib")
        )
        monkeypatch.setattr(
            cli,
            "_run_ansi",
            lambda **_: ansi_calls.append("ansi"),
        )

        result = runner.invoke(app, ["play", "--render", "ansi"])
        assert result.exit_code == 0
        assert ansi_calls == ["lib", "ansi"]


class TestMettaRecipe:
    """Verify the Metta recipe bridge command shape."""

    def test_play_tool_wraps_external_cli(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        captured: dict[str, object] = {}

        def fake_run(cmd, cwd, check, stdout=None):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            captured["check"] = check
            captured["stdout"] = stdout
            return SimpleNamespace(returncode=0)

        _install_fake_metta(monkeypatch, tmp_path)
        monkeypatch.setattr(recipe.subprocess, "run", fake_run)

        tool = recipe.play()
        tool.max_steps = 77
        tool.steps = 5

        assert tool.invoke({}) == 0
        assert captured == {
            "cmd": [
                "uv",
                "run",
                "--project",
                str(tmp_path),
                "--extra",
                "tribalcog",
                "tribalcog",
                "play",
                "--render",
                "ansi",
                "--steps",
                "5",
                "--random-actions",
                "--max-steps",
                "77",
            ],
            "cwd": tmp_path,
            "check": True,
            "stdout": recipe.subprocess.DEVNULL,
        }

    def test_play_tool_propagates_cli_failures(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        def fake_run(cmd, cwd, check, stdout=None):  # noqa: ARG001
            raise subprocess.CalledProcessError(returncode=2, cmd=cmd)

        _install_fake_metta(monkeypatch, tmp_path)
        monkeypatch.setattr(recipe.subprocess, "run", fake_run)

        with pytest.raises(subprocess.CalledProcessError):
            recipe.play().invoke({})


class TestGuiLaunchStrategy:
    """Verify the GUI launcher uses the fast path when possible."""

    def test_run_gui_uses_cached_binary_without_instrumentation(self, monkeypatch):
        runtime_root = Path("/tmp/tribal_village_runtime")
        binary_path = runtime_root / "tribal_village"
        calls: list[tuple[list[str], Path | None]] = []

        monkeypatch.setattr(cli, "ensure_nim_binary_current", lambda: binary_path)
        monkeypatch.setattr(cli, "get_runtime_project_root", lambda: runtime_root)
        monkeypatch.setattr(
            cli.subprocess,
            "run",
            lambda cmd, **kwargs: calls.append((cmd, kwargs.get("cwd")))
            or SimpleNamespace(returncode=0),
        )

        cli._run_gui(
            profile=False,
            profile_steps=1,
            step_timing=False,
            step_timing_target=0,
            step_timing_window=0,
            render_timing=False,
            render_timing_target=0,
            render_timing_window=0,
            render_timing_every=1,
            render_timing_exit=None,
        )

        assert calls == [([str(binary_path)], runtime_root)]

    def test_run_gui_uses_nim_when_instrumented(self, monkeypatch):
        runtime_root = Path("/tmp/tribal_village_runtime")
        calls: list[tuple[list[str], Path | None]] = []

        monkeypatch.setattr(cli, "get_runtime_project_root", lambda: runtime_root)
        monkeypatch.setattr(
            cli.subprocess,
            "run",
            lambda cmd, **kwargs: calls.append((cmd, kwargs.get("cwd")))
            or SimpleNamespace(returncode=0),
        )

        cli._run_gui(
            profile=False,
            profile_steps=1,
            step_timing=True,
            step_timing_target=0,
            step_timing_window=1,
            render_timing=False,
            render_timing_target=0,
            render_timing_window=0,
            render_timing_every=1,
            render_timing_exit=None,
        )

        assert calls == [
            (
                ["nim", "r", "-d:release", "-d:stepTiming", "--path:src", "tribal_village.nim"],
                runtime_root,
            )
        ]


@requires_nim_library
class TestPlayAnsi:
    """Integration tests for play command with ANSI renderer."""

    def test_play_ansi_short(self):
        result = runner.invoke(app, ["play", "--render", "ansi", "--steps", "2"])
        assert result.exit_code == 0
        assert len(result.output) > 0
