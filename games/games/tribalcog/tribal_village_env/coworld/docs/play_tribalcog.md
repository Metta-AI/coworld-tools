# Play Tribal Cog as a Coworld

Tribal Cog can run either as the standalone PufferLib/Nim game or as a Coworld
game server. The Coworld path uses the existing Python FFI wrapper and exposes
the standard Coworld runtime routes on port 8080.

## Local Coworld server

Create a config file with one token for a local human-player smoke test. Hosted
leagues can inject up to 1000 tokens, one per controllable villager.

```bash
python3 - <<'PY'
import json
from pathlib import Path

Path("/tmp/tribalcog-config.json").write_text(json.dumps({
    "tokens": ["token-0"],
    "max_steps": 100,
    "seed": 0,
    "step_seconds": 0.05,
    "victory_condition": 0,
    "player_connect_timeout_seconds": 10,
    "render_every_steps": 5,
}, indent=2))
PY
```

Run the server:

```bash
COGAME_CONFIG_URI=file:///tmp/tribalcog-config.json \
COGAME_RESULTS_URI=file:///tmp/tribalcog-results.json \
COGAME_SAVE_REPLAY_URI=file:///tmp/tribalcog-replay.json.z \
python -m tribal_village_env.coworld.server
```

Open `/clients/global` for the live map. It connects to `/global?frame=1` and
renders the normal Nim renderer's RGB frame stream from the Python FFI. A
player connects to `/clients/player?slot=<slot>&token=<token>` and controls one
villager through the 11x11 `tribalcog-sprite-v1` local view exposed by
`/player`. The player client renders the same PNG sprite assets served from
`/assets/...` into a single 2D canvas tile per observation cell, with semantic
glyphs kept only as a fallback.

## Native WASM client

The native Nim/Emscripten browser build is optional for local development:

```bash
nimble wasm
```

That writes `tribal_village.js`, `tribal_village.wasm`, and
`tribal_village.data` under `build/web/`. While the Coworld server is running,
open `/clients/wasm/` to load those generated assets. This client is the native
standalone Tribal Cog browser build; `/global` and `/player` remain the Coworld
spectator and player-control routes.

## Reference player

The bundled reference player reads the Coworld-standard `COWORLD_PLAYER_WS_URL`
and falls back to `COGAMES_ENGINE_WS_URL` for older local harnesses:

```bash
COWORLD_PLAYER_WS_URL=ws://localhost:8080/player?slot=0\&token=token-0 \
python -m tribal_village_env.coworld.player
```

The default mode is `TRIBALCOG_PLAYER_MODE=sprite`, which uses the semantic
11x11 `tribalcog-sprite-v1` view and moves toward visible resources or threats.
Set `TRIBALCOG_PLAYER_MODE=noop` for a deterministic noop player or
`TRIBALCOG_PLAYER_MODE=random` for random legal actions.

## Certification

From a Metta checkout with Coworld installed, the checked-in hosted manifest can
be validated with:

```bash
uv run --package coworld coworld certify /Users/relh/Code/games/games/tribalcog/coworld_manifest.json
```

That full manifest is fixed at 1000 slots because current Coworld manifest
validation requires `tokens.minItems == tokens.maxItems` and
`certification.players` must match that count. For routine local certification,
generate a one-slot manifest from the checked-in manifest:

```bash
jq '(.game.config_schema.properties.tokens.minItems = 1) |
    (.game.config_schema.properties.tokens.maxItems = 1) |
    (.game.results_schema.properties.scores.minItems = 1) |
    (.game.results_schema.properties.scores.maxItems = 1) |
    (.certification.players = [.certification.players[0]])' \
  /Users/relh/Code/games/games/tribalcog/coworld_manifest.json \
  > /tmp/tribalcog-cert-manifest.json

uv run --package coworld coworld certify /tmp/tribalcog-cert-manifest.json --timeout-seconds 60
```

This exercises the same runtime and reference player without connecting every
hosted player slot.

## Replay

Completed episodes write the native Tribal Cog replay artifact to
`COGAME_SAVE_REPLAY_URI`. In replay mode, the hosted runner starts the same
image with `COGAME_REPLAY_SERVER=1` and iframes:

```text
/clients/replay?uri=<replay-uri>
```

The replay client opens `/replay?uri=<replay-uri>`, decompresses `.json.z`
artifacts, and draws the native object timeline.
