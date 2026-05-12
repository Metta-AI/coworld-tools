from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_cogsguard_parity.py"


@cache
def _load_parity_module():
    spec = importlib.util.spec_from_file_location("test_run_cogsguard_parity", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_load_multi_policy_prefers_installed_package_code(monkeypatch) -> None:
    parity = _load_parity_module()
    calls: list[str] = []

    class _Context:
        def __enter__(self):
            calls.append("enter")

        def __exit__(self, exc_type, exc, tb):
            calls.append("exit")

    def fake_prefer_installed_package_code():
        calls.append("context")
        return _Context()

    monkeypatch.setattr(parity, "prefer_installed_package_code", fake_prefer_installed_package_code)
    monkeypatch.setattr(parity, "policy_spec_from_uri", lambda uri: {"uri": uri})
    monkeypatch.setattr(
        parity,
        "initialize_or_load_policy",
        lambda policy_env_info, policy_spec: ("loaded", policy_env_info, policy_spec),
    )

    result = parity._load_multi_policy("env-info", "metta://policy/example:v1")

    assert result == ("loaded", "env-info", {"uri": "metta://policy/example:v1"})
    assert calls == ["context", "enter", "exit"]
