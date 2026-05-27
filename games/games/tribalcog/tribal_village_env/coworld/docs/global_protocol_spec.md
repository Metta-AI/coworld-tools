# Tribal Cog Global and Replay Protocol

Global viewers connect to:

```text
WEBSOCKET /global
```

Replay viewers connect to:

```text
WEBSOCKET /replay?uri=<replay-uri>
```

The hosted Coworld replay proxy must preserve the `uri` query parameter when it
iframes `/client/replay?uri=...` and opens `/replay?uri=...`.

## View-plane messages

The game server sends state snapshots:

```json
{
  "type": "state",
  "step": 12,
  "max_steps": 1000,
  "started": true,
  "paused": false,
  "done": false,
  "connected_players": 1,
  "total_player_slots": 8,
  "team_scores": [0, 0, 0, 0, 0, 0, 0, 0],
  "team_connected_players": [1, 0, 0, 0, 0, 0, 0, 0],
  "step_seconds": 0.1,
  "view_plane": {
    "protocol": "tribalcog-view-plane-v1",
    "width": 306,
    "height": 192,
    "tile_size": 24,
    "team_colors": [
      "#e3655b",
      "#f0c552",
      "#6bbf69",
      "#58b6b2",
      "#5b8de0",
      "#b46ce0",
      "#df8a3b",
      "#d96f9f"
    ],
    "terrain": {
      "encoding": "u8-base64",
      "labels": ["empty", "water"],
      "sprites": [{"id": 0, "label": "empty", "asset": "/assets/floor.png"}],
      "data": "..."
    },
    "tint": {
      "encoding": "rgba8-base64",
      "columns": ["r", "g", "b", "a"],
      "data": "..."
    },
    "objects": {
      "encoding": "i16-base64",
      "columns": [
        "layer",
        "x",
        "y",
        "z",
        "thing",
        "team_id",
        "agent_id",
        "unit_class",
        "orientation",
        "asset"
      ],
      "sprites": ["/assets/oriented/gatherer.n.png"],
      "data": "..."
    },
    "object_count": 8063
  }
}
```

`view_plane` is the canonical spectator contract. Terrain is a compact
row-major `uint8` ordinal grid. `team_colors` comes from the Nim simulation's
active team palette and is the source of truth for team-owned sprite tinting.
`tint` is the row-major RGBA territory layer produced by the Nim tint pass:
lanterns, citizens, and other tint emitters write color into the map, and the
alpha channel is the per-tile tint intensity used for territory scoring. Render
terrain first, then apply the territory tint over that terrain, then render
objects by `z`.

Objects are also compact: decode the base64 as little-endian signed 16-bit rows
using the listed columns, map ordinals through `legend.object_layer`,
`legend.thing`, `legend.unit_class`, and `legend.orientation`, and map the
`asset` column through `objects.sprites`. A non-negative `team_id` means the
sprite should be tinted with `team_colors[team_id]`. Team IDs are intentionally
limited to actual team-owned citizens and healthy lanterns so resource and
building sprites do not inherit misleading ownership colors. Load PNGs from the
served `/assets/...` URLs.

## Browser clients

`/client/global` serves the Coworld spectator client for the `/global`
websocket. This is a thin JavaScript canvas client over the Coworld sprite/tint
protocol, not the native Nim/Emscripten renderer. `/client/player` is the
town-control view and uses the same thin-client renderer scoped to one team's
fog-of-war.
After running `nimble wasm` from the Tribal Cog package root, `/client/wasm/`
serves the native Emscripten build from `build/web/` for local browser checks.
The WASM client is separate from the Coworld player protocol; player slots still
connect through `/player`.

## Replay messages

In replay mode the server reads the replay artifact passed in `uri` and sends:

```json
{
  "type": "replay",
  "object_count": 1006,
  "max_steps": 1000,
  "replay": {}
}
```

`replay` is the native Tribal Cog replay document. Native `.json.z` artifacts
are zlib-compressed JSON and are decompressed by the replay server before being
sent to the browser client.
