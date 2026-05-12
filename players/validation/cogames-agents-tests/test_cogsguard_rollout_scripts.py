from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_cogsguard_rollout.py"


@cache
def _load_rollout_module():
    spec = importlib.util.spec_from_file_location("test_run_cogsguard_rollout", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rollout_tag_helpers_match_current_cogsguard_labels() -> None:
    rollout = _load_rollout_module()

    assert rollout._is_hub_tag("hub", [])
    assert rollout._is_hub_tag("charger", ["main_nexus"])
    assert rollout._is_junction_tag("junction", [])
    assert rollout._is_junction_tag("charger", ["neutral_junction"])
    assert rollout._is_junction_tag("charger", ["supply_depot"])
    assert not rollout._is_junction_tag("hub", ["team:cogs"])
    assert rollout._has_alignment_tag("cogs_hub", [])
    assert rollout._has_alignment_tag("charger", ["team:clips"])
    assert not rollout._has_alignment_tag("neutral_junction", [])
