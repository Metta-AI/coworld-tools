# Tribal Cog Player Protocol

Players connect to:

```text
WEBSOCKET /player?slot=<0-999>&token=<runner-token>
```

Each slot controls exactly one Tribal Cog agent. Slot `0` controls agent `0`,
slot `124` controls team 0's final agent, slot `125` controls team 1's first
agent, and slot `999` controls team 7's final agent. Agent IDs `1000..1005`
are game-owned goblin/NPC agents.

## Server to player

The server sends one JSON observation message per tick:

```json
{
  "type": "observation",
  "slot": 0,
  "agent_id": 0,
  "team_id": 0,
  "team_agent_index": 0,
  "step": 12,
  "max_steps": 1000,
  "started": true,
  "done": false,
  "reward": 0.0,
  "score": 1.25,
  "team_score": 91.5,
  "action_space": 308,
  "action_names": [
    "noop",
    "move",
    "attack",
    "use",
    "swap",
    "put",
    "plant_lantern",
    "plant_resource",
    "build",
    "orient",
    "set_rally_point"
  ],
  "orientation_names": [
    "north",
    "south",
    "west",
    "east",
    "north_west",
    "north_east",
    "south_west",
    "south_east"
  ],
  "sprite_view": {
    "protocol": "tribalcog-sprite-v1",
    "width": 11,
    "height": 11,
    "radius": 5,
    "center": {"x": 5, "y": 5},
    "cells": [[
      {
        "x": 5,
        "y": 5,
        "terrain": "grass",
        "thing": "agent",
        "sprite": "thing.agent",
        "glyph": "@",
        "color": "#e3655b",
        "team_id": 0,
        "unit_class": "villager",
        "orientation": "north",
        "idle": true,
        "tint": 0,
        "obscured": false
      }
    ]]
  },
  "observation": {
    "dtype": "uint8",
    "shape": [101, 11, 11],
    "encoding": "base64",
    "data": "..."
  }
}
```

`sprite_view` is the preferred browser and lightweight policy contract. It is
a semantic 11x11 view centered on the controlled villager and uses stable
sprite keys such as `terrain.grass`, `thing.agent`, and `fog.unknown`.

The `observation` bytes are retained for low-level policies that want the
existing Tribal Cog per-agent observation tensor encoded as contiguous raw
`uint8` bytes.

The final message has `"type": "final"` and the same shape as an observation.

## Player to server

Players reply with one action for their controlled agent:

```json
{ "action": 17 }
```

The action must be an integer in `[0, 307]`. The server also accepts
`{"action": {"verb": 0, "argument": 17}}`; the action ID is
`verb * 28 + argument`.

Invalid, missing, late, or out-of-range actions become action `0` noop for that
tick. A duplicate active connection for the same slot is rejected.
