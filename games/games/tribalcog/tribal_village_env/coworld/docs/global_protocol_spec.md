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
  "connected_players": 1000,
  "total_player_slots": 1000,
  "team_scores": [0, 0, 0, 0, 0, 0, 0, 0],
  "team_connected_players": [125, 125, 125, 125, 125, 125, 125, 125],
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
    "objects": [
      {
        "id": "foreground:14:20",
        "layer": "foreground",
        "x": 14,
        "y": 20,
        "z": 120,
        "thing": "agent",
        "team_id": 0,
        "agent_id": 0,
        "unit_class": "villager",
        "orientation": "north",
        "asset": "/assets/oriented/gatherer.n.png"
      }
    ]
  }
}
```

`global_view` is the canonical spectator contract. Terrain is a compact
row-major `uint8` ordinal grid, and `objects` are already flattened from the
engine's blocking/background grids into drawable sprite placements. Browser
clients should render terrain first, then objects by `z`, and load PNGs from
the served `/assets/...` URLs.

`/global?frame=1` is retained as a legacy fallback. When requested, snapshots
also include `frame`, whose bytes are raw RGB pixels produced by the Nim
renderer through the Python FFI. New Coworld clients should prefer
`global_view` so the spectator sees the same sprite assets as player views.

## Browser clients

`/clients/global` is the Coworld spectator client for the `/global` websocket.
If opened with `?slot=<slot>&token=<token>`, it also connects to `/player` for
that slot and sends sprite-player button packets for keyboard control while
continuing to render the global map.
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
