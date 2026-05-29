from __future__ import annotations

import json
from pathlib import Path

from amongcogs.coworld.server import build_env

ROOT = Path(__file__).resolve().parents[1]


def test_coworld_manifest_has_fixed_slots_and_reference_player() -> None:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text())
    tokens = manifest["game"]["config_schema"]["properties"]["tokens"]
    assert tokens["minItems"] == 8
    assert tokens["maxItems"] == 8
    assert len(manifest["certification"]["players"]) == 8
    assert manifest["player"][0]["image"] == "coworld-amongcogs-player:latest"


def test_coworld_build_env_uses_configured_slot_count() -> None:
    config = {"tokens": [f"token-{idx}" for idx in range(8)], "max_steps": 3, "seed": 0, "step_seconds": 0.01}
    env = build_env(config)
    assert env.game.num_agents == 8
    assert env.game.max_steps == 3
