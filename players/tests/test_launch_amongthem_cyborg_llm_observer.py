from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


def _load_launcher_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "launch_amongthem_cyborg_llm_observer.py"
    spec = importlib.util.spec_from_file_location("launch_amongthem_cyborg_llm_observer", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apply_tailscale_address_rejects_empty_ip_output(monkeypatch) -> None:
    launcher = _load_launcher_module()
    args = argparse.Namespace(tailscale=True, host="0.0.0.0", browser_host="localhost")

    monkeypatch.setattr(launcher.subprocess, "check_output", lambda _cmd, text: "\n")

    with pytest.raises(RuntimeError, match="No Tailscale IPv4 address found"):
        launcher._apply_tailscale_address(args)


def test_parse_args_defaults_to_canonical_game_settings(monkeypatch) -> None:
    launcher = _load_launcher_module()
    monkeypatch.setattr(sys, "argv", ["launch_amongthem_cyborg_llm_observer.py"])

    args = launcher._parse_args()

    assert args.players == 8
    assert args.imposters == 2
    assert args.tasks_per_player == 8
    assert args.imposter_cooldown_ticks == 1200
    assert args.vote_timer_ticks == 600


def test_parse_args_allows_short_task_smoke_override(monkeypatch) -> None:
    launcher = _load_launcher_module()
    monkeypatch.setattr(
        sys,
        "argv",
        ["launch_amongthem_cyborg_llm_observer.py", "--tasks-per-player", "1"],
    )

    args = launcher._parse_args()

    assert args.tasks_per_player == 1


def test_crewmate_count_caps_imposters_to_leave_one_crewmate() -> None:
    launcher = _load_launcher_module()
    args = argparse.Namespace(players=5, imposters=7)

    assert launcher._crewmate_count(args) == 1


def test_policy_uri_keeps_env_shape_out_of_policy_kwargs() -> None:
    launcher = _load_launcher_module()
    args = argparse.Namespace(llm_talk=False, provider="auto", no_nim_core=False, model=None)

    parsed_uri = urlparse(launcher._policy_uri(args))
    query = parse_qs(parsed_uri.query)

    assert parsed_uri.geturl().startswith("metta://policy/amongthem_cyborg?")
    assert "frame_stack" not in query
    assert query == {
        "llm_talk": ["false"],
        "llm_provider": ["auto"],
        "use_nim_core": ["true"],
    }


def test_apply_tailscale_address_uses_first_tailscale_ip(monkeypatch) -> None:
    launcher = _load_launcher_module()
    args = argparse.Namespace(tailscale=True, host="0.0.0.0", browser_host="localhost")

    monkeypatch.setattr(launcher.subprocess, "check_output", lambda _cmd, text: "100.64.0.1\n100.64.0.2\n")

    launcher._apply_tailscale_address(args)

    assert args.host == "100.64.0.1"
    assert args.browser_host == "100.64.0.1"
