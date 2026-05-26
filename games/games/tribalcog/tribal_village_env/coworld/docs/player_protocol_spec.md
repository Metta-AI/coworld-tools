# Tribal Cog Player Protocol

Town controllers connect to:

```text
WEBSOCKET /player?slot=<0-7>&token=<runner-token>
```

Each slot controls one team/town. Citizens continue to act individually through
compiled Nim policies. A town controller edits the programs assigned by visible
friendly buildings and can inspect one selected citizen's local 11x11 view.

## Server to player

The server sends one JSON observation message per tick:

```json
{
  "type": "observation",
  "slot": 0,
  "team_id": 0,
  "selected_agent_id": 0,
  "step": 12,
  "max_steps": 1000,
  "started": true,
  "done": false,
  "reward": 0.0,
  "score": 1.25,
  "team_score": 91.5,
  "program_catalog": [
    {
      "id": 0,
      "key": "gatherer_default",
      "name": "Gatherer Default",
      "summary": "Economy: gather, deposit, and keep the stockpile moving.",
      "source": "step(obs): ..."
    }
  ],
  "citizen_program": {
    "id": 0,
    "key": "gatherer_default",
    "revision": 1,
    "source_building_id": 42,
    "assigned_step": 120,
    "source": "step(obs): ..."
  },
  "visible_buildings": [
    {
      "x": 20,
      "y": 30,
      "thing": "barracks",
      "program": {"id": 2, "key": "fighter_guard", "revision": 0}
    }
  ],
  "visible_citizens": [
    {
      "agent_id": 7,
      "x": 21,
      "y": 31,
      "unit_class": "man_at_arms",
      "program": {"id": 2, "key": "fighter_guard", "revision": 1}
    }
  ],
  "stockpiles": {"food": 10, "wood": 12, "gold": 3, "stone": 0, "water": 0},
  "global_view": {"protocol": "tribalcog-global-sprite-v1"},
  "sprite_view": {"protocol": "tribalcog-sprite-v1"},
  "observation": {"dtype": "uint8", "shape": [101, 11, 11], "encoding": "base64", "data": "..."}
}
```

`global_view` is the team fog-of-war map rendered with the same sprite/object
schema as `/global`, including `team_colors`, team-tinted sprites, and the RGBA
territory tint layer used for score. Unrevealed cells are hidden. `sprite_view`
and `observation` are centered on the selected citizen and keep the existing
11x11 local view for inspection and lightweight policies.

Each `sprite_view` cell includes the same visual information needed to match the
map: `terrain_asset`, `thing_drawables` with per-object `team_id`, and
`territory_tint` with `{rgba, color, alpha}`. Player clients should render this
11x11 view as a crop of the fog-scoped map, not as a separate bitworld-style
pixel protocol.

The final message has `"type": "final"` and the same shape as an observation.

## Player to server

Select a citizen for the PiP/local observation:

```json
{"type": "town.select_citizen", "agent_id": 7}
```

Select a visible friendly building:

```json
{"type": "town.select_building", "x": 20, "y": 30}
```

Set the program future citizens will snapshot when they transform through that
building:

```json
{"type": "town.set_program", "x": 20, "y": 30, "program_id": 3}
```

Edits apply only to future entrants. Existing citizens keep their already
assigned program snapshot until they transform through another building.

Legacy integer actions and BitWorld-style `0x84 <buttons-u8>` packets are
accepted as no-ops for old clients. Town controllers do not directly drive one
citizen's action each tick.
