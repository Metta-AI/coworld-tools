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
  "frame": {
    "width": 1224,
    "height": 768,
    "encoding": "rgb-base64",
    "data": "..."
  }
}
```

The `frame` field is sent every `render_every_steps` and at the end of the
episode. `/global?frame=1` also includes a frame in the first snapshot. Its
bytes are raw RGB pixels produced by the Nim renderer through the Python FFI.

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
