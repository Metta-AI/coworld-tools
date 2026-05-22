from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest
import numpy as np

from tribal_village_env.coworld.player import choose_sprite_action
from tribal_village_env.coworld.server import (
    AGENTS_PER_TEAM,
    OBSCURED_LAYER,
    PLAYER_SLOT_COUNT,
    TEAM_LAYER,
    TERRAIN_LAYER_START,
    THING_LAYER_START,
    UNIT_CLASS_LAYER,
    CoworldConfig,
    decode_action,
    load_replay_data,
    slot_team_index,
    slot_to_team,
    sprite_view_from_observation,
    winner_team,
)


def test_slot_mapping() -> None:
    assert PLAYER_SLOT_COUNT == 1000
    assert AGENTS_PER_TEAM == 125
    assert slot_to_team(0) == 0
    assert slot_to_team(124) == 0
    assert slot_to_team(125) == 1
    assert slot_to_team(999) == 7
    assert slot_team_index(125) == 0
    assert slot_team_index(999) == 124


def test_config_accepts_certification_sized_token_lists() -> None:
    with pytest.raises(ValueError, match="between 1 and 1000 tokens"):
        CoworldConfig.from_dict({"tokens": [], "max_steps": 1})

    config = CoworldConfig.from_dict(
        {
            "tokens": ["token-0"],
            "max_steps": 3,
            "seed": 7,
            "step_seconds": 0.01,
            "victory_condition": 0,
            "render_every_steps": 2,
        }
    )

    assert config.max_steps == 3
    assert config.seed == 7
    assert config.render_every_steps == 2

    with pytest.raises(ValueError, match="between 1 and 1000 tokens"):
        CoworldConfig.from_dict(
            {"tokens": [f"token-{idx}" for idx in range(PLAYER_SLOT_COUNT + 1)]}
        )


def test_decode_action_accepts_integer_and_verb_argument() -> None:
    assert decode_action({"action": 17}) == 17
    assert decode_action({"action": {"verb": 2, "argument": 3}}) == 59
    assert decode_action({"action": -1}) == 0
    assert decode_action({"action": 9999}) == 0
    assert decode_action({"action": "not-an-action"}) == 0
    assert decode_action({}) == 0


def test_sprite_view_from_observation_exposes_semantic_cells() -> None:
    obs = np.zeros((101, 11, 11), dtype=np.uint8)
    obs[TERRAIN_LAYER_START + 5, 5, 5] = 1
    obs[THING_LAYER_START, 5, 5] = 1
    obs[TEAM_LAYER, 5, 5] = 1
    obs[UNIT_CLASS_LAYER, 5, 5] = 1
    obs[OBSCURED_LAYER, 0, 0] = 1

    view = sprite_view_from_observation(obs)

    assert view["protocol"] == "tribalcog-sprite-v1"
    assert view["width"] == 11
    assert view["center"] == {"x": 5, "y": 5}
    center = view["cells"][5][5]
    assert center["sprite"] == "thing.agent"
    assert center["team_id"] == 0
    assert center["unit_class"] == "villager"
    assert view["cells"][0][0]["sprite"] == "fog.unknown"


def test_sprite_player_policy_moves_toward_visible_resource() -> None:
    message = {
        "team_id": 0,
        "sprite_view": {
            "center": {"x": 5, "y": 5},
            "cells": [
                [
                    {"x": x, "y": y, "thing": None, "team_id": None, "obscured": False}
                    for x in range(11)
                ]
                for y in range(11)
            ],
        },
    }
    message["sprite_view"]["cells"][5][6]["thing"] = "tree"

    assert choose_sprite_action(message) == 1 * 28 + 3


def test_winner_team_returns_none_on_tie() -> None:
    assert winner_team([0.0, 2.0, 1.0]) == 1
    assert winner_team([2.0, 2.0, 1.0]) is None


def test_load_replay_data_reads_zlib_json(tmp_path: Path) -> None:
    replay_path = tmp_path / "replay.json.z"
    payload = {"version": 1, "objects": [], "max_steps": 2}
    replay_path.write_bytes(zlib.compress(json.dumps(payload).encode()))

    assert load_replay_data(str(replay_path)) == payload
