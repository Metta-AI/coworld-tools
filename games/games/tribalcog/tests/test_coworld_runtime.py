from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest

from tribal_village_env.coworld.server import (
    AGENTS_PER_TEAM,
    PLAYER_SLOT_COUNT,
    CoworldConfig,
    decode_action,
    load_replay_data,
    slot_team_index,
    slot_to_team,
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


def test_config_requires_1000_tokens() -> None:
    with pytest.raises(ValueError, match="exactly 1000 tokens"):
        CoworldConfig.from_dict({"tokens": ["one"], "max_steps": 1})

    config = CoworldConfig.from_dict(
        {
            "tokens": [f"token-{idx}" for idx in range(PLAYER_SLOT_COUNT)],
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


def test_decode_action_accepts_integer_and_verb_argument() -> None:
    assert decode_action({"action": 17}) == 17
    assert decode_action({"action": {"verb": 2, "argument": 3}}) == 59
    assert decode_action({"action": -1}) == 0
    assert decode_action({"action": 9999}) == 0
    assert decode_action({"action": "not-an-action"}) == 0
    assert decode_action({}) == 0


def test_winner_team_returns_none_on_tie() -> None:
    assert winner_team([0.0, 2.0, 1.0]) == 1
    assert winner_team([2.0, 2.0, 1.0]) is None


def test_load_replay_data_reads_zlib_json(tmp_path: Path) -> None:
    replay_path = tmp_path / "replay.json.z"
    payload = {"version": 1, "objects": [], "max_steps": 2}
    replay_path.write_bytes(zlib.compress(json.dumps(payload).encode()))

    assert load_replay_data(str(replay_path)) == payload
