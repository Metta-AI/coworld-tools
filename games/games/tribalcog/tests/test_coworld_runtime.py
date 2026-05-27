from __future__ import annotations

import base64
import json
import random
import zlib
from pathlib import Path

import pytest
import numpy as np

from tribal_village_env.coworld.player import (
    choose_overseer_command,
    player_ws_url,
)
from tribal_village_env.coworld.server import (
    AGENTS_PER_TEAM,
    GLOBAL_CELL_BACKGROUND_AGENT_ID,
    GLOBAL_CELL_BACKGROUND_KIND,
    GLOBAL_CELL_BACKGROUND_ORIENTATION,
    GLOBAL_CELL_BACKGROUND_TEAM,
    GLOBAL_CELL_BACKGROUND_UNIT_CLASS,
    GLOBAL_CELL_FIELD_COUNT,
    GLOBAL_CELL_TERRAIN,
    GLOBAL_CELL_THING_AGENT_ID,
    GLOBAL_CELL_THING_KIND,
    GLOBAL_CELL_THING_ORIENTATION,
    GLOBAL_CELL_THING_TEAM,
    GLOBAL_CELL_THING_UNIT_CLASS,
    GLOBAL_CELL_TINT_ALPHA,
    GLOBAL_CELL_TINT_B,
    GLOBAL_CELL_TINT_G,
    GLOBAL_CELL_TINT_R,
    OBSCURED_LAYER,
    ORIENTATION_LAYER,
    PLAYER_SLOT_COUNT,
    SIM_AGENT_COUNT,
    TEAM_LAYER,
    TERRAIN_LAYER_START,
    THING_LAYER_START,
    UNIT_CLASS_LAYER,
    CoworldConfig,
    DEFAULT_RENDER_EVERY_STEPS,
    TribalCogCoworld,
    _decode_action_rows,
    asset_media_type,
    view_plane_from_cells,
    iter_view_plane_objects,
    load_replay_data,
    resolve_sprite_asset_path,
    resolve_wasm_asset_path,
    slot_team_index,
    slot_to_team,
    sprite_view_from_plane_cells,
    sprite_view_from_observation,
    wasm_media_type,
    winner_team,
)


def test_slot_mapping() -> None:
    assert PLAYER_SLOT_COUNT == 8
    assert SIM_AGENT_COUNT == 1000
    assert AGENTS_PER_TEAM == 125
    assert slot_to_team(0) == 0
    assert slot_to_team(7) == 7
    assert slot_team_index(0) == 0
    assert slot_team_index(7) == 0


def test_config_accepts_certification_sized_token_lists() -> None:
    with pytest.raises(ValueError, match="between 1 and 8 team tokens"):
        CoworldConfig.from_dict({"tokens": [], "max_steps": 1})

    default_config = CoworldConfig.from_dict({"tokens": ["token-0"], "max_steps": 1})
    assert default_config.render_every_steps == DEFAULT_RENDER_EVERY_STEPS == 1

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

    with pytest.raises(ValueError, match="between 1 and 8 team tokens"):
        CoworldConfig.from_dict(
            {"tokens": [f"token-{idx}" for idx in range(PLAYER_SLOT_COUNT + 1)]}
        )


def test_sprite_view_from_observation_exposes_semantic_cells() -> None:
    obs = np.zeros((101, 11, 11), dtype=np.uint8)
    obs[TERRAIN_LAYER_START + 5, 5, 5] = 1
    obs[THING_LAYER_START, 5, 5] = 1
    obs[THING_LAYER_START + 3, 5, 5] = 1
    obs[TEAM_LAYER, 5, 5] = 1
    obs[UNIT_CLASS_LAYER, 5, 5] = 1
    obs[ORIENTATION_LAYER, 5, 5] = 1
    obs[OBSCURED_LAYER, 0, 0] = 1

    view = sprite_view_from_observation(obs)

    assert view["protocol"] == "tribalcog-sprite-v1"
    assert view["width"] == 11
    assert view["center"] == {"x": 5, "y": 5}
    center = view["cells"][5][5]
    assert center["sprite"] == "thing.agent"
    assert center["thing"] == "agent"
    assert center["things"] == ["tree", "agent"]
    assert center["terrain_asset"] == "/assets/grass.png"
    assert center["thing_asset"] == "/assets/oriented/gatherer.n.png"
    assert center["thing_assets"] == [
        "/assets/tree.png",
        "/assets/oriented/gatherer.n.png",
    ]
    assert center["sprite_asset"] == "/assets/oriented/gatherer.n.png"
    assert center["team_id"] == 0
    assert center["unit_class"] == "villager"
    assert view["cells"][0][0]["sprite"] == "fog.unknown"
    assert view["cells"][0][0]["sprite_asset"] is None


def test_view_plane_from_cells_exposes_terrain_and_objects() -> None:
    cells = np.full((2, 3, GLOBAL_CELL_FIELD_COUNT), -1, dtype=np.int16)
    cells[:, :, GLOBAL_CELL_TERRAIN] = 0
    cells[1, 2, GLOBAL_CELL_TERRAIN] = 6
    cells[1, 2, GLOBAL_CELL_BACKGROUND_KIND] = 3
    cells[1, 2, GLOBAL_CELL_BACKGROUND_TEAM] = -1
    cells[1, 2, GLOBAL_CELL_BACKGROUND_ORIENTATION] = 0
    cells[1, 2, GLOBAL_CELL_BACKGROUND_UNIT_CLASS] = -1
    cells[1, 2, GLOBAL_CELL_BACKGROUND_AGENT_ID] = -1
    cells[1, 2, GLOBAL_CELL_THING_KIND] = 0
    cells[1, 2, GLOBAL_CELL_THING_TEAM] = 0
    cells[1, 2, GLOBAL_CELL_THING_ORIENTATION] = 0
    cells[1, 2, GLOBAL_CELL_THING_UNIT_CLASS] = 0
    cells[1, 2, GLOBAL_CELL_THING_AGENT_ID] = 7
    cells[0, 1, GLOBAL_CELL_TINT_R] = 255
    cells[0, 1, GLOBAL_CELL_TINT_G] = 96
    cells[0, 1, GLOBAL_CELL_TINT_B] = 48
    cells[0, 1, GLOBAL_CELL_TINT_ALPHA] = 128

    view = view_plane_from_cells(cells)

    assert view["protocol"] == "tribalcog-view-plane-v1"
    assert view["width"] == 3
    assert view["height"] == 2
    assert view["team_colors"][0] == "#e3655b"
    assert base64.b64decode(view["terrain"]["data"]) == bytes([0, 0, 0, 0, 0, 6])
    assert base64.b64decode(view["tint"]["data"]) == bytes(
        [
            0,
            0,
            0,
            0,
            255,
            96,
            48,
            128,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )
    assert view["terrain"]["sprites"][6]["asset"] == "/assets/grass.png"
    assert view["object_count"] == 2
    assert view["objects"]["encoding"] == "i16-base64"
    objects = list(iter_view_plane_objects(view))
    assert objects[0]["thing"] == "tree"
    assert objects[0]["asset"] == "/assets/tree.png"
    assert objects[1]["thing"] == "agent"
    assert objects[1]["agent_id"] == 7
    assert objects[1]["asset"] == "/assets/oriented/gatherer.n.png"
    assert "visibility" not in view


def test_sprite_view_from_plane_cells_matches_view_plane_protocol() -> None:
    cells = np.full((4, 4, GLOBAL_CELL_FIELD_COUNT), -1, dtype=np.int16)
    cells[:, :, GLOBAL_CELL_TERRAIN] = 6
    cells[1, 1, GLOBAL_CELL_TERRAIN] = 10
    cells[2, 2, GLOBAL_CELL_TERRAIN] = 2
    cells[2, 2, GLOBAL_CELL_THING_KIND] = 0
    cells[2, 2, GLOBAL_CELL_THING_TEAM] = 0
    cells[2, 2, GLOBAL_CELL_THING_ORIENTATION] = 0
    cells[2, 2, GLOBAL_CELL_THING_UNIT_CLASS] = 0
    cells[2, 2, GLOBAL_CELL_THING_AGENT_ID] = 7
    cells[2, 2, GLOBAL_CELL_TINT_R] = 227
    cells[2, 2, GLOBAL_CELL_TINT_G] = 101
    cells[2, 2, GLOBAL_CELL_TINT_B] = 91
    cells[2, 2, GLOBAL_CELL_TINT_ALPHA] = 192

    view = sprite_view_from_plane_cells(cells, 2, 2, radius=1)

    assert view["protocol"] == "tribalcog-sprite-v1"
    assert view["source"] == "view_plane_cells"
    assert view["center"] == {"x": 1, "y": 1, "world_x": 2, "world_y": 2}
    assert view["cells"][0][0]["terrain"] == "mud"
    center = view["cells"][1][1]
    assert center["terrain"] == "shallow_water"
    assert center["thing"] == "agent"
    assert center["thing_assets"] == ["/assets/oriented/gatherer.n.png"]
    assert center["thing_drawables"] == [
        {
            "asset": "/assets/oriented/gatherer.n.png",
            "team_id": 0,
            "thing": "agent",
        }
    ]
    assert center["team_id"] == 0
    assert center["territory_tint"] == {
        "rgba": [227, 101, 91, 192],
        "color": "#e3655b",
        "alpha": 0.753,
    }


def test_reference_overseer_edits_visible_military_building() -> None:
    rng = random.Random(0)
    message = {
        "visible_buildings": [
            {
                "x": 4,
                "y": 9,
                "thing": "barracks",
                "program": {"id": 2},
            }
        ]
    }

    assert choose_overseer_command(message, "overseer", rng) == {
        "type": "town.set_program",
        "x": 4,
        "y": 9,
        "program_id": 3,
    }


def test_visible_town_objects_use_building_ownership_lookup() -> None:
    class DummyEnv:
        def building_team_id(self, x: int, y: int) -> int:
            return 0 if (x, y) == (4, 9) else -1

        def building_program(self, x: int, y: int) -> dict[str, int]:
            return {"program_id": 2, "revision": 7}

        def agent_program(self, agent_id: int) -> dict[str, int]:
            return {
                "program_id": 0,
                "revision": 0,
                "source_building_id": -1,
                "assigned_step": 0,
            }

    state = TribalCogCoworld.__new__(TribalCogCoworld)
    state.env = DummyEnv()

    buildings, citizens = state._visible_town_objects(
        0,
        {
            "objects": [
                {
                    "id": "foreground:4:9",
                    "x": 4,
                    "y": 9,
                    "thing": "barracks",
                    "team_id": None,
                },
                {
                    "id": "foreground:5:9",
                    "x": 5,
                    "y": 9,
                    "thing": "stable",
                    "team_id": None,
                },
                {
                    "id": "foreground:6:9",
                    "x": 6,
                    "y": 9,
                    "thing": "agent",
                    "team_id": 0,
                    "agent_id": 0,
                    "unit_class": "villager",
                },
            ]
        },
    )

    assert citizens == [
        {
            "agent_id": 0,
            "x": 6,
            "y": 9,
            "unit_class": "villager",
            "program": state._agent_program_payload(0),
        }
    ]
    assert buildings == [
        {
            "id": "foreground:4:9",
            "x": 4,
            "y": 9,
            "thing": "barracks",
            "team_id": 0,
            "program": {
                "id": 2,
                "key": "fighter_guard",
                "name": "Fighter Guard",
                "summary": "Defense: guard home territory and respond to nearby threats.",
                "source": (
                    "step(obs): stay near home or rally point; attack visible enemies "
                    "that threaten friendly citizens or buildings; regroup when isolated."
                ),
                "revision": 7,
                "x": 4,
                "y": 9,
            },
        }
    ]


def test_winner_team_returns_none_on_tie() -> None:
    assert winner_team([0.0, 2.0, 1.0]) == 1
    assert winner_team([2.0, 2.0, 1.0]) is None


def test_load_replay_data_reads_zlib_json(tmp_path: Path) -> None:
    replay_path = tmp_path / "replay.json.z"
    payload = {"version": 1, "objects": [], "max_steps": 2}
    replay_path.write_bytes(zlib.compress(json.dumps(payload).encode()))

    assert load_replay_data(str(replay_path)) == payload


def test_decode_action_rows_reads_uint16_action_log() -> None:
    actions = np.asarray([[1, 2, 300], [0, 59, 307]], dtype="<u2")
    replay = {
        "num_agents": 3,
        "actions": {
            "encoding": "u16le-base64",
            "shape": [2, 3],
            "data": base64.b64encode(actions.tobytes()).decode("ascii"),
        },
    }

    rows = _decode_action_rows(replay)

    assert rows.dtype == np.dtype("<u2")
    assert rows.tolist() == [[1, 2, 300], [0, 59, 307]]


def test_coworld_replay_bytes_are_action_log(tmp_path: Path) -> None:
    class DummyEnv:
        num_agents = 3

    config = CoworldConfig.from_dict(
        {
            "tokens": ["token-0"],
            "max_steps": 2,
            "seed": 5,
            "step_seconds": 0.01,
            "victory_condition": 0,
            "render_every_steps": 1,
        }
    )
    action_path = tmp_path / "replay.json.z.actions"
    action_bytes = np.asarray([[1, 2, 3], [4, 5, 6]], dtype="<u2").tobytes()
    action_path.write_bytes(action_bytes)

    state = TribalCogCoworld.__new__(TribalCogCoworld)
    state.config = config
    state.env = DummyEnv()
    state.local_replay_path = tmp_path / "replay.json.z"
    state.action_replay_path = action_path
    state.replay_steps = 2
    state.actual_seed = 5
    state.initial_view_plane = {"width": 9, "height": 7}
    state.replay_action_file = action_path.open("rb")
    try:
        replay = json.loads(zlib.decompress(state._replay_bytes({"steps": 2})))
    finally:
        state.replay_action_file.close()

    assert replay["format"] == "tribalcog-action-log-v1"
    assert replay["map_size"] == [9, 7]
    assert replay["initial_state"]["view_plane"] == {"width": 9, "height": 7}
    assert replay["actions"]["shape"] == [2, 3]
    assert replay["action_argument_count"] == 28
    assert base64.b64decode(replay["actions"]["data"]) == action_bytes


def test_wasm_asset_resolution_stays_inside_build_dir(tmp_path: Path) -> None:
    build_dir = tmp_path / "web"
    build_dir.mkdir()
    asset = build_dir / "tribal_village.js"
    asset.write_text("console.log('tribal cog')\n")

    assert resolve_wasm_asset_path(build_dir, "tribal_village.js") == asset.resolve()

    with pytest.raises(FileNotFoundError):
        resolve_wasm_asset_path(build_dir, "missing.js")
    with pytest.raises(FileNotFoundError):
        resolve_wasm_asset_path(build_dir, "nimcache/generated.c")
    with pytest.raises(FileNotFoundError):
        resolve_wasm_asset_path(build_dir, "../tribal_village.js")


def test_sprite_asset_resolution_stays_inside_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    asset = data_dir / "grass.png"
    asset.write_bytes(b"not-really-a-png")

    assert resolve_sprite_asset_path(data_dir, "grass.png") == asset.resolve()

    with pytest.raises(FileNotFoundError):
        resolve_sprite_asset_path(data_dir, "missing.png")
    with pytest.raises(FileNotFoundError):
        resolve_sprite_asset_path(data_dir, "Inter-Regular.ttf")
    with pytest.raises(ValueError):
        resolve_sprite_asset_path(data_dir, "../grass.png")


def test_wasm_asset_media_types() -> None:
    assert wasm_media_type(Path("tribal_village.html")) == "text/html"
    assert wasm_media_type(Path("tribal_village.js")) == "application/javascript"
    assert wasm_media_type(Path("tribal_village.wasm")) == "application/wasm"
    assert wasm_media_type(Path("tribal_village.data")) == "application/octet-stream"


def test_sprite_asset_media_types() -> None:
    assert asset_media_type(Path("grass.png")) == "image/png"
    assert asset_media_type(Path("grass.bin")) == "application/octet-stream"


def test_reference_player_requires_coworld_player_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COWORLD_PLAYER_WS_URL", "ws://coworld-player")

    assert player_ws_url() == "ws://coworld-player"

    monkeypatch.delenv("COWORLD_PLAYER_WS_URL")
    with pytest.raises(KeyError):
        player_ws_url()
