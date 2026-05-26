# Tribal Cog Global and Replay Protocol

Global viewers connect to:

```text
WEBSOCKET /global
```

Browser clients may request an initial full-map frame with:

```text
WEBSOCKET /global?frame=1
```

Replay viewers connect to:

```text
WEBSOCKET /replay?uri=<replay-uri>
```

The hosted Coworld replay proxy must preserve the `uri` query parameter when it
iframes `/clients/replay?uri=...` and opens `/replay?uri=...`.

## Global messages

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
  "step_seconds": 0.05,
  "global_view": {
    "protocol": "tribalcog-global-sprite-v1",
    "width": 306,
    "height": 192,
    "tile_size": 24,
    "terrain": {
      "encoding": "u8-base64",
      "labels": ["empty", "water"],
      "sprites": [{"id": 0, "label": "empty", "asset": "/assets/floor.png"}],
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

`global_view` is the canonical spectator contract. Terrain is a compact
row-major `uint8` ordinal grid. Objects are also compact: decode the base64 as
little-endian signed 16-bit rows using the listed columns, map ordinals through
`legend.object_layer`, `legend.thing`, `legend.unit_class`, and
`legend.orientation`, and map the `asset` column through `objects.sprites`.
Render terrain first, then objects by `z`, loading PNGs from the served
`/assets/...` URLs.

`/global?frame=1` is retained as a legacy fallback. When requested, snapshots
also include `frame`, whose bytes are raw RGB pixels produced by the Nim
renderer through the Python FFI. New Coworld clients should prefer
`global_view` so the spectator sees the same sprite assets as player views.

## Browser clients

`/client/global` and `/clients/global` serve the Coworld spectator client for
the `/global` websocket.
If opened with `?slot=<team>&token=<token>`, it also connects to `/player` for
that team. The dedicated `/client/player` and `/clients/player` page is the
richer town-control view; the global page remains primarily a spectator.
After running `nimble wasm` from the Tribal Cog package root, `/clients/wasm/`
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
