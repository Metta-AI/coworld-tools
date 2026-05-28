from __future__ import annotations

import json
from pathlib import Path

from overcogged.coworld.server import build_env

ROOT = Path(__file__).resolve().parents[1]


def test_coworld_manifest_has_fixed_slots_and_reference_player() -> None:
    manifest = json.loads((ROOT / "coworld_manifest.json").read_text())
    tokens = manifest["game"]["config_schema"]["properties"]["tokens"]
    assert tokens["minItems"] == 2
    assert tokens["maxItems"] == 2
    assert len(manifest["certification"]["players"]) == 2
    assert manifest["player"][0]["image"] == "coworld-overcogged-player:latest"


def test_coworld_build_env_uses_configured_slot_count() -> None:
    config = {"tokens": [f"token-{idx}" for idx in range(2)], "max_steps": 3, "seed": 0, "step_seconds": 0.01, "mission": "classic"}
    env = build_env(config)
    assert env.game.num_agents == 2
    assert env.game.max_steps == 3
