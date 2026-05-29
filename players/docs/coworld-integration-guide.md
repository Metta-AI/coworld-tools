# Coworld Integration Guide

Developer-facing reference for what a player built in this repo actually does
at runtime, how the Coworld system reaches it, and how to debug it once it is
live.

This is a companion to
[`coworld-player-packaging.md`](coworld-player-packaging.md). Use the
packaging contract for what `build.sh` must emit and how `coworld
upload-policy` / `upload-coworld` consume those artifacts. Use this guide for
the *runtime* picture: lifecycle, environment, protocol expectations, and the
Observatory-side tools you use to inspect a running or finished episode.

Captured 2026-05-19 from `~/coding/metta/packages/coworld/` (`runner/`,
`COWORLD_README.md`, `GAME_RUNTIME_README.md`, `CLI_README.md`). Update this
document if you observe drift against those sources.

## 1. Where a player sits in the system

A Coworld **episode** has exactly one game container and one player container
per game-declared slot. The two surfaces that matter to a player author live
on opposite ends of the episode:

- The **runner** (`coworld.runner.runner` locally, `coworld.runner.kubernetes_runner`
  in hosted) starts the game, generates per-slot tokens, then starts one
  player container per slot. The runner is the *only* thing that injects
  environment variables into the player and the *only* thing that sees the
  player's container logs.
- **Observatory** is the backend + web UI that owns uploaded policies,
  leagues, episode requests, captured logs, and replays. Players never talk
  to Observatory directly. Observatory pulls everything it shows from the
  artifacts the runner uploaded.

The game container sits between them. Players never see the manifest, the
game config, the variant, or any other player's identity — only what the
runner places in their environment and what the game sends over the
websocket.

## 2. Episode lifecycle from the player's perspective

In order, every time:

1. The runner generates per-slot tokens, writes the concrete game config,
   and starts the game container.
2. The runner waits for the game's `GET /healthz` to return 200.
3. The runner starts one player container per slot. Each container receives
   the env documented in §3.
4. The player reads `COGAMES_ENGINE_WS_URL` and opens that websocket.
5. The game accepts the connection only if the slot + token in the URL match
   one it issued for this episode. Mismatched tokens are rejected.
6. The player speaks the game-specific protocol (linked from
   `game.protocols.player` in the manifest) until the game closes the socket.
7. The player exits. Non-zero exit codes are recorded but do not retroactively
   invalidate the episode if the game already produced results.
8. The runner waits for the game to write `results.json` and `replay.json`,
   validates `results.json` against the game's `results_schema`, and uploads
   results, replay, and per-slot player logs.

### Reconnect

The `/player` websocket allows the same slot + token pair to reconnect while
the episode is still running. The slot's in-game state survives short
disconnects; during the disconnect the game applies a no-op (or whatever its
protocol documents as the default). A player that crashes and is restarted
*within the same container* can reconnect cleanly. A player container that
exits is not restarted by the runner.

## 3. Environment surface

This is the complete set of variables a player container can rely on. Anything
else you read from the env is either explicit `env:` in the manifest or a
secret attached to the policy version.

| Variable | Source | Guarantee |
|---|---|---|
| `COGAMES_ENGINE_WS_URL` | Runner | Always set. Full `ws://...:8080/player?slot=<slot>&token=<token>[&...]`. Use exactly as given. |
| `<public env>` | `player[].env` in the manifest | Whatever the manifest declared for this player entry. Empty if the manifest declared nothing. |
| `<secret env>` | `coworld upload-policy --secret-env KEY=VAL` | Delivered only to the pod running that exact policy version. Never written to the manifest. |
| `USE_BEDROCK` | `coworld upload-policy --use-bedrock` | Equivalent to `--secret-env USE_BEDROCK=true`. Routes to a Bedrock-enabled service account on the hosted runner. |

What is **not** set:

- `COGAME_LOG_URI` is documented as "optionally" set for players by the
  contract in `GAME_RUNTIME_README.md`, but as of this writing neither the
  local nor the Kubernetes runner injects it for player containers. Treat it
  as not set. Use stdout/stderr for diagnostic output; the runner captures
  both and uploads them as the per-slot player log.
- The manifest, the game config, the variant ID, the slot count, the other
  players' identities, and the league/division context are all **invisible**
  to a player. If your player needs to vary behavior across variants, encode
  the relevant knob in the manifest's `player[].env` for that bundled entry,
  or accept that league-submitted policies are one-size-fits-all per upload.

### Connection URL parsing

`COGAMES_ENGINE_WS_URL` may include extra game-owned query parameters beyond
`slot` and `token` (for example `role=scout`). Do not strip them, reorder
them, or merge any host-side query state into the URL. Pass the value through
to your websocket client untouched.

## 4. Player protocol

Coworld itself only defines the URL contract and reconnect semantics. The
wire format is **game-owned** and documented at the URI in the manifest's
`game.protocols.player`. For games currently in this repo:

| Game | Protocol | Wire format summary |
|---|---|---|
| Among Them | [bitscreen_v1](https://github.com/Metta-AI/bitworld/blob/master/docs/bitscreen_v1.md) | Binary. Server → client: 8192-byte frame (128×128 4-bit packed pixels). Client → server: 2-byte button packet or `[0x01] + ascii` chat packet. |
| Cogs vs Clips | `coworld.player.v1` | JSON. First server message is `player_config`; subsequent server messages are `observation` with mettagrid tokens. Player replies with `action` (by `action_index` or `action_name`). Server sends `final` and closes. |
| Paint Arena | custom JSON | `observation` in, `move` out. |

When you add a player for a new game, read the protocol URI before writing
any code, and link it from the policy's README.

## 5. Logs and visibility

Three independent channels carry information out of a running player. Only
the first two are part of the platform contract; the third exists only when
the player chooses to emit it.

1. **Container stdout/stderr.** The runner captures both into a per-slot
   file (`policy_agent_<slot>.txt` locally, `policy_log_path` on Kubernetes).
   At episode end, the Kubernetes worker uploads each captured file via the
   per-slot URLs in `POLICY_LOG_URLS`. Observatory exposes these via
   `coworld episode-logs ereq_... --agent <slot>`.
2. **Game-side replay.** The game writes a full game-state replay to
   `COGAME_SAVE_REPLAY_URI` at episode end. Players do not write replays;
   they appear in the replay as a consequence of what the game observed.
3. **Player-emitted structured traces.** Optional. If your player writes
   newline-delimited JSON (or any other structured form) to stdout, those
   lines become part of the captured log. The Coborg framework uses this
   pattern: each strategy/reflex tick emits a JSON line that downstream
   tooling can replay against the captured frames.

Practical implication: anything you want to see after the fact must come out
over stdout/stderr before the container exits. Write traces eagerly, flush
on each tick (or use `PYTHONUNBUFFERED=1`), and avoid stderr-only logging if
you also want it visible in normal `docker logs` runs.

## 6. Local development loop

The local runner uses Docker, an isolated `coworld-local` network, and a
single workspace directory under `/tmp` per episode. It is the canonical
target for iterating before uploading.

```bash
# 1. Download a Coworld package for the game you're targeting.
uv run coworld download <coworld-name-or-id> --output-dir ./coworld

# 2. Build your player image (must be linux/amd64).
docker buildx build --platform=linux/amd64 --load -t my-player:latest .

# 3. Run one local episode. One image can fill every slot, or pass one per slot.
uv run coworld run-episode \
    ./coworld/<coworld-id>/coworld_manifest.json \
    my-player:latest

# 4. Inspect the local workspace the runner just used.
ls /tmp/coworld-cert-*/
#   config.json  results.json  replay.json  logs/{game.stdout.log,game.stderr.log,policy_agent_0.txt,...}
```

`coworld play` is the same flow optimized for human play (it opens a browser
client for the human-driven slot and uses your built image for the rest).
For both commands, browser/debug URLs are printed on `127.0.0.1:<port>`
while player containers connect to the game via
`ws://coworld-game-<run-id>:8080/...` on the `coworld-local` Docker network.

If your image's default `CMD` is not the player entrypoint, pass `--run`
arguments to `run-episode` (the same `--run` flags you would later pass to
`upload-policy`) so the local and hosted invocations stay in sync.

## 7. Hosted lifecycle

After local episodes work end-to-end, the hosted path is:

```bash
# Upload the image and create a versioned policy.
uv run coworld upload-policy my-player:latest --name my-player

# Submit to a league. The latest version is used when :vN is omitted.
uv run coworld submit my-player --league league_...
```

`upload-policy` saves the image with `docker image save`, validates that the
embedded config reports `os=linux, architecture=amd64`, then pushes the
layers + manifest directly via the OCI distribution API. Server-side it
becomes a `PolicyVersion` row addressable as `<name>:vN`. `submit` enters
that exact policy version into a league.

From there, Observatory's tournament scheduler turns league memberships into
**episode requests**, which the hosted Kubernetes runner consumes one
episode at a time. Each episode produces:

- A `results.json` validated against `game.results_schema`.
- A compressed `replay.json.z` artifact.
- Per-slot text logs (your player's captured stdout/stderr).
- An entry in the division standings if `results.json` contains valid scores.

The platform identifies any one execution by an **episode request ID**
(`ereq_...`). Everything in §8 keys off that ID.

## 8. Debugging a hosted player

The Coworld CLI is the supported way to retrieve everything Observatory
captured. The most useful commands while iterating:

```bash
# What did I submit and when?
uv run coworld submissions --mine --league league_...

# Which episodes ran for my submission?
uv run coworld episodes --division div_... --mine --with-replay

# Look at one episode end-to-end.
uv run coworld episode-stats   ereq_...
uv run coworld episode-results ereq_... --output results.json
uv run coworld episode-logs    ereq_... --agent 0      # my slot's stdout/stderr
uv run coworld episode-logs    ereq_... --list         # all available log files
uv run coworld replays         --division div_... --mine --download-dir replays/
uv run coworld replay-open     ereq_...                # local replay viewer
uv run coworld replay-open     ereq_... --hosted       # Observatory-hosted viewer URL
```

`episode-logs --agent <slot>` is the single most useful debugging tool: it
gives back exactly what your container wrote to stdout/stderr, which is also
the only channel by which player-side traces survive an episode.

`results.json` carries the `scores` array (one number per slot) plus any
game-declared extra fields, so it is the right place to look for "did my
player even play to completion" signals.

The web UI (Observatory) exposes the same data graphically; the CLI is the
ground truth and what to use from scripts.

## 9. What this means for code in this repo

A player in this repo — i.e., a `players/<game>/<policy>/` directory — is
expected to be:

- A Docker build that produces a `linux/amd64` image whose entrypoint reads
  `COGAMES_ENGINE_WS_URL` and speaks the protocol at
  `game.protocols.player`.
- Quiet by default on success, verbose on failure, and *always* emitting
  diagnostic information to stdout (not stderr-only) since stdout is the
  only channel Observatory will surface to you after the fact.
- Free of secrets in the image. API keys etc. get attached at
  `upload-policy` time with `--secret-env`.
- Reconnect-safe if you choose to handle in-container restarts. The platform
  itself never restarts a player container, so absence of reconnect logic
  is acceptable.

The Coworld Player SDK under `players/player_sdk/` already wires the
websocket loop, stdout-trace pattern, and entrypoint shape; new players
should prefer it over an ad-hoc scaffold. A retired worked example, the
Among Them Coborg player, is preserved under
`archive/players/among_them/coborg/`.

## 10. Reference: source-of-truth files in `metta`

When this guide drifts, check these first.

- Player runtime contract: `metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md`
- Local Docker runner: `metta/packages/coworld/src/coworld/runner/runner.py`,
  `metta/packages/coworld/src/coworld/runner/RUNNER_README.md`
- Hosted Kubernetes runner: `metta/packages/coworld/src/coworld/runner/kubernetes_runner.py`,
  `metta/packages/coworld/src/coworld/runner/KUBERNETES_RUNNER_README.md`
- CLI surface: `metta/packages/coworld/src/coworld/cli.py`,
  `metta/packages/coworld/src/coworld/CLI_README.md`
- Manifest types: `metta/packages/coworld/src/coworld/types.py`
- Upload + image push: `metta/packages/coworld/src/coworld/upload.py`
- Submit: `metta/packages/coworld/src/coworld/submit.py`
- Certifier: `metta/packages/coworld/src/coworld/certifier.py`
- Game-specific player protocols: linked from each manifest's
  `game.protocols.player`.
