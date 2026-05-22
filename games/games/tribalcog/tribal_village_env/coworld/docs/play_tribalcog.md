# Play Tribal Cog as a Coworld

Tribal Cog can run either as the standalone PufferLib/Nim game or as a Coworld
game server. The Coworld path uses the existing Python FFI wrapper and exposes
the standard Coworld runtime routes on port 8080.

## Local Coworld server

Create a config file with 1000 tokens. For example:

```bash
python3 - <<'PY'
import json
from pathlib import Path

Path("/tmp/tribalcog-config.json").write_text(json.dumps({
    "tokens": [f"token-{idx}" for idx in range(1000)],
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

Open `/clients/global` for the live map. A player connects to
`/clients/player?slot=<slot>&token=<token>`.

## Reference player

The bundled reference player reads `COGAMES_ENGINE_WS_URL`:

```bash
COGAMES_ENGINE_WS_URL=ws://localhost:8080/player?slot=0\&token=token-0 \
python -m tribal_village_env.coworld.player
```

Set `TRIBALCOG_PLAYER_MODE=noop` for a deterministic noop player or leave the
default random policy.

## Certification

From a Metta checkout with Coworld installed, validate the manifest with:

```bash
uv run --package coworld coworld certify /Users/relh/Code/games/games/tribalcog/coworld_manifest.json
```

The full hosted league shape has 1000 player slots, so certifying the checked-in
manifest launches 1000 reference player containers. For local development,
certify the same runtime with a temporary one-slot manifest:

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

This keeps the hosted manifest honest while avoiding 1000 local player
connections for routine smoke checks.

## Replay

Completed episodes write the native Tribal Cog replay artifact to
`COGAME_SAVE_REPLAY_URI`. In replay mode, the hosted runner starts the same
image with `COGAME_REPLAY_SERVER=1` and iframes:

```text
/clients/replay?uri=<replay-uri>
```

The replay client opens `/replay?uri=<replay-uri>`, decompresses `.json.z`
artifacts, and draws the native object timeline.
