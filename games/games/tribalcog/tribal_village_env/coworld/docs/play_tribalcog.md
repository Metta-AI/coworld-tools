# Play Tribal Cog as a Coworld

Tribal Cog can run either as the standalone PufferLib/Nim game or as a Coworld
game server. The Coworld path uses the existing Python FFI wrapper and exposes
the standard Coworld runtime routes on port 8080.

## Local Coworld server

Create a config file with one token for a local human-player smoke test. Hosted
leagues inject 8 tokens, one per town/team. Local smoke tests may provide fewer
tokens; towns without a connected controller run the built-in default policies.

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

Open `/clients/global` for the live map. It connects to `/global` and renders
the `tribalcog-global-sprite-v1` terrain/object/tint stream using the same PNG
assets served from `/assets/...` as the player view. Team-owned citizens and
lanterns are tinted with the active Nim team palette, and the territory tint
layer is drawn over terrain before sprites.

Open `/clients/player?slot=0&token=token-0` to control team 0 as a town
overseer. The player page shows the team's fog-of-war global map, a
picture-in-picture 11x11 `tribalcog-sprite-v1` view for the selected citizen,
visible citizens/buildings, stockpiles, and the program editor for selected
friendly buildings. `/clients/global?slot=0&token=token-0` can still attach a
team token while watching the whole map, but the dedicated player page is the
primary controller surface.

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

The default mode is `TRIBALCOG_PLAYER_MODE=overseer`, which watches the
team-scoped observation and edits visible military-building programs when it
can. Set `TRIBALCOG_PLAYER_MODE=noop` for a deterministic passive controller.
Legacy `sprite` and `random` modes remain for old local harnesses, but town
control is the Coworld path.

## Certification

From a Metta checkout with Coworld installed, the checked-in hosted manifest can
be validated with:

```bash
uv run --package coworld coworld certify /Users/relh/Code/games/games/tribalcog/coworld_manifest.json
```

The checked-in manifest is fixed at 8 town slots because Coworld manifest
validation requires `tokens.minItems == tokens.maxItems` and
`certification.players` must match that count. This certification path exercises
the same town-overseer reference player used by hosted variants. At runtime,
the local server can still start with fewer connected human controllers and let
unconnected towns run defaults.

## Replay

Completed episodes write the native Tribal Cog replay artifact to
`COGAME_SAVE_REPLAY_URI`. In replay mode, the hosted runner starts the same
image with `COGAME_REPLAY_SERVER=1` and iframes:

```text
/clients/replay?uri=<replay-uri>
```

The replay client opens `/replay?uri=<replay-uri>`, decompresses `.json.z`
artifacts, and draws the native object timeline.
