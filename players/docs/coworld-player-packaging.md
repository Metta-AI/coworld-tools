# Coworld Player Packaging Contract

Reference for what every policy under `players/<game>/<policy>/` must produce
in order to be (a) uploadable as an independent Coworld policy and (b)
bundleable into a larger Coworld manifest.

Captured 2026-05-19 from `~/coding/metta/packages/coworld/` and
`~/coding/bitworld/`. Update this document if you observe drift against those
sources.

## TL;DR

A Coworld "player" is **a Linux/amd64 Docker image** that, when given
`COGAMES_ENGINE_WS_URL` in its environment, connects to that websocket and
speaks the game-specific player protocol until the game ends.

Two distinct artifacts can be produced from one player:

1. **An uploaded policy version** — `coworld upload-policy <image> --name <name>`
   pushes the image to Softmax-managed storage and creates a versioned policy
   that can be `coworld submit`-ted to a league.
2. **A `player[]` entry in a Coworld manifest** — a JSON object that declares
   the player as a bundled, in-package player for a game-author's
   `coworld_manifest.json`. Used when shipping a Coworld + bundled players in
   one `upload-coworld`.

Both consume the same Docker image. They are independent operations; one image
can be used for either or both.

## Resolved Design Decisions

Every `players/<game>/<policy>/build.sh` produces, on a successful build:

- **A local Docker image with a local tag.** No mandatory registry push.
  An optional flag may push to a public registry, but it must work without a
  remote registry configured.
- **A `coworld_manifest.json` `player[]` snippet** — emitted to STDOUT *and*
  to an output file path controlled by a CLI flag (so callers in pipelines
  can capture the artifact without parsing stdout).
- **A `coplayer_manifest.json`** — small documentary metadata
  (`{author, name, image_uri, games}`). Not consumed by any Coworld CLI today
  but useful for human/discovery.

Out of scope (intentionally not produced by `build.sh`):

- Full self-contained `coworld_manifest.json` (would require the player author
  to also own the game container, variants, and certification fixture).
- Automatic upload — `build.sh` produces artifacts; uploading is a separate
  invocation of `coworld upload-policy` or `coworld upload-coworld`.

## 1. The Docker image contract (player runtime)

All other surfaces sit on top of this. Sources:
[`COWORLD_README.md`](https://github.com/Metta-AI/metta/blob/main/packages/coworld/src/coworld/COWORLD_README.md),
[`GAME_RUNTIME_README.md`](https://github.com/Metta-AI/metta/blob/main/packages/coworld/src/coworld/GAME_RUNTIME_README.md),
and `bitworld/among_them/players/how_to_submit_coworld_policy.md`.

- **Platform**: `linux/amd64`. On Apple Silicon, build with
  `docker buildx build --platform=linux/amd64 --load -t <tag> .`. `upload-policy`
  inspects the saved image's embedded config and rejects anything that is not
  `linux/amd64`.
- **Entrypoint**: the image's `CMD`/`ENTRYPOINT` runs the player process. If
  the image hosts multiple roles or its default CMD is not the player, pass
  `--run` (argv list, repeatable) to override at episode and upload time.
  Stored on the policy version as `run`.
- **Environment variables it receives** at episode start:
  - `COGAMES_ENGINE_WS_URL` — full `ws://...:8080/player?slot=<slot>&token=<token>`.
    Use exactly as given; do not merge other query params, rewrite the host,
    or hardcode slots/tokens.
  - `COGAME_LOG_URI` — *contract: optional.* The
    [`GAME_RUNTIME_README.md`](https://github.com/Metta-AI/metta/blob/main/packages/coworld/src/coworld/GAME_RUNTIME_README.md)
    contract says a player may receive this; the documented behavior is
    that the player POSTs plain-text log lines (one or more
    newline-separated lines per request) to it. **As of 2026-05-19,
    neither the local Docker runner (`coworld.runner.runner`) nor the
    hosted Kubernetes runner (`coworld.runner.kubernetes_runner`) injects
    `COGAME_LOG_URI` into player containers** — only into game
    containers. Treat it as not set for players, and rely on
    stdout/stderr (which the runner captures into the per-slot policy
    log and uploads to Observatory). Re-check the runner source before
    depending on this variable.
  - Public env from manifest `player[i].env`.
  - Secret env attached to the policy version via
    `coworld upload-policy ... --secret-env KEY=VAL` (only delivered in
    production, never written into the manifest).
  - `USE_BEDROCK=true` if uploaded with `--use-bedrock`.
- **Resources (hosted)**: each player pod is scheduled with **2 CPU / 2Gi
  memory** requested. These are scheduling requests, not hard limits.
- **Lifecycle**:
  1. Read `COGAMES_ENGINE_WS_URL` from env.
  2. Open the websocket exactly as supplied.
  3. Speak the game-specific player protocol until the game ends or the
     runner stops the container.
  4. Exit when the game closes the socket.
- **Reconnect**: a player may reconnect to the same slot with the same token
  while the episode is running; the slot's game state survives short
  disconnects. During disconnect the game applies a no-op or other documented
  default action.
- **No secrets in the image**. Keep API keys etc. as `--secret-env` on the
  policy version. Secrets are scoped to that policy version's player pods and
  not shared with bundled-player slots or other roles.

### Game-specific player protocols

Not part of the Coworld spec; defined by each game container and documented at
the URI in its `game.protocols.player`. Currently relevant to this repo:

| Game | Protocol | Wire format |
|---|---|---|
| Among Them | [bitscreen_v1](https://github.com/Metta-AI/bitworld/blob/master/docs/bitscreen_v1.md) | Binary. Server → client: 8192-byte frame (128×128 4-bit packed pixels). Client → server: 2-byte button packet `[0x00, mask]` (Up=1, Down=2, Left=4, Right=8, Select=16, A=32, B=64) or chat packet `[0x01] + ascii_bytes`. |
| Cogs vs Clips | coworld.player.v1 | JSON. First server message is `{"type":"player_config","protocol":"coworld.player.v1",...}`. Subsequent server messages are `{"type":"observation",...}` with mettagrid observation tokens. Player replies with `{"type":"action","action_index":N}` or `{"type":"action","action_name":"..."}`. Server sends `{"type":"final"}` and closes when done. |
| Paint Arena | custom JSON | `{"type":"observation","positions":[...],"width","height"}` in; `{"move":"left|right|up|down"}` out. |

For any new game in `players/`, treat the manifest's `game.protocols.player`
URI as the source of truth and link it from the policy's README.

## 2. `coworld upload-policy` — what it needs

From `coworld.cli.upload_policy` and `coworld.upload.upload_policy_cmd` /
`complete_docker_image_policy`.

**Inputs**:

- Positional: a local Docker image reference (e.g. `my-policy:latest`). The
  CLI shells out to `docker image save <image>` to read bytes.
- `--name <NAME>` (required): the policy name. Versioning is automatic on the
  server — `vN` increments per upload of that name.
- `--run ARG ... --run ARG` (optional, repeatable): argv list to use as the
  container command. Required when the image's default CMD is not the player.
  Stored on the policy version and used by every episode using this policy.
- `--secret-env KEY=VALUE` (optional, repeatable): per-policy-version secrets
  stored in AWS Secrets Manager and injected only into pods for this exact
  policy version.
- `--use-bedrock`: shorthand that adds `USE_BEDROCK=true` to the secret env.
- `--server <URL>` (optional, default Softmax API): targets a non-default
  Observatory environment.

**Auth**: requires `softmax login` to have produced a `softmax-cli` token.
The `coworld[auth]` extra brings this in.

**Server-side flow** (`POST /v2/container_images/upload` → push to ECR via the
OCI distribution API → `POST /v2/container_images/upload/complete` →
`POST /stats/policies/docker-img/complete`):

1. `docker image save <image>` → temp tar.
2. Verify `linux/amd64` from the embedded config JSON; reject otherwise.
3. Compute a SHA over the config + layer digests; this is the client-side
   content hash.
4. Request an upload slot (`request_image_upload`). The server returns either
   pre-signed ECR push info (push needed) or a reference to an existing
   identical image (no push).
5. If pushing: `aws ecr get-login-password` with the returned credentials →
   push layers and manifest directly via the OCI distribution HTTP API (the
   code sidesteps `docker push` because of a Docker 29 + ECR HEAD/manifest-403
   bug).
6. `complete_image_upload` to mark the image complete on the server.
7. `complete_docker_image_policy` with
   `{name, container_image_id, run?, policy_secret_env?}` — creates the
   versioned policy row. Result: `name`, `version` (int), and the policy
   version ID.

**Output**: `Upload complete: <name>:v<N>`.

**Submit** is a separate command:

```bash
coworld submit <name>[:vN] --league <league_id>
```

Hits `POST /v2/league-submissions` with the resolved policy-version ID.
Omitting `:vN` resolves to the most recently uploaded version for that name.

## 3. `coworld_manifest.json` `player[]` — what it needs

From `coworld.types.CoworldManifest` and `CoworldDeclaredRoleSpec`. The
manifest is validated with `extra="forbid"`, so unknown fields fail.

A manifest's `player` is `list[CoworldDeclaredRoleSpec]` with `min_length=1`.
Each entry:

```json
{
  "id": "starter-policy-player",        // unique within manifest; referenced by certification
  "name": "Starter Policy Player",      // human-readable
  "type": "player",                     // literal; same shape covers grader/reporter/etc.
  "description": "...",                 // required, min_length=1
  "image": "ghcr.io/.../image:tag",     // Docker image ref
  "run": ["python", "/app/player.py"],  // optional argv list; overrides image CMD
  "env": { "COGAMES_POLICY_URI": "..." } // optional, public env vars only; no secrets
}
```

This is the snippet shape `build.sh` emits.

Adjacent required manifest sections that bundled players interact with (the
game author owns these; `build.sh` does not produce them):

- **`game.config_schema`** must require `tokens` as a string array with equal
  `minItems` and `maxItems`. That fixed length is the number of player slots.
  Variants and certification fixtures omit `tokens`; the runner injects them.
- **`game.protocols.player`** — a document object
  `{"type":"uri","value":"https://..."}` (or `"text"`) describing the player
  websocket protocol the image must implement.
- **`certification`** — `{game_config, players: [{player_id: "..."}]}`. Each
  `player_id` must match a declared `player[].id`. The fixture is used by
  `coworld certify` to run one short episode that boots the game + bundled
  players, verifies HTTP routes / token rejection, validates final results
  against `results_schema`, and confirms a replay is produced. Without a
  valid certification, you cannot `upload-coworld` — `upload_coworld` calls
  `certify_coworld(manifest_path)` before uploading.
- **`variants`** — at least one variant; each is
  `{id, name, description, game_config, parent_id?}`. Used for league configs
  and local play.

When `upload-coworld` runs:

1. Manifest validated against the Pydantic schema (`extra="forbid"`).
2. Certification fixture run end-to-end with the declared `player[].image`
   references. Images must be locally reachable; `assert_docker_image_reachable`
   runs first — the certifier does NOT build images.
3. Every distinct `image` string under `game.runnable.image`, `player[].image`,
   `grader[].image`, ... is uploaded the same way `upload-policy` uploads a
   single image, and the manifest's `image` strings are rewritten to
   Softmax-managed image IDs before the manifest itself is stored.

Each bundled player receives the same runtime env as any league player
(`COGAMES_ENGINE_WS_URL`, optional `COGAME_LOG_URI`, public `env` from the
manifest). Secrets cannot be attached to a manifest-bundled player —
`--secret-env` only exists for `upload-policy`.

## 4. The "policy package" sidecar (`coplayer_manifest.json`)

`coworld make-policy among_them -o my-player` writes a starter project
including a `coplayer_manifest.json`:

```json
{
  "author": "treeform@softmax.com",
  "name": "amongthemstarter",
  "image_uri": "ghcr.io/metta-ai/amongthemstarter:latest",
  "games": ["among_them"]
}
```

**This file is not currently consumed by any Coworld CLI command** —
`upload-policy`, `submit`, `certify`, `upload-coworld`, and `run-episode`
ignore it. It's documentary metadata, useful for sharing/discovery of a
packaged player. `build.sh` produces it as a courtesy.

## 5. The `build.sh` contract

Every `players/<game>/<policy>/build.sh` must:

1. Build a Linux/amd64 Docker image with a deterministic local tag (e.g.
   `players-<game>-<policy>:<version>`, where `<version>` is read from a
   `VERSION` file in the policy dir if present, otherwise `dev`).
2. Print the `player[]` snippet (the JSON described in §3) to STDOUT.
3. Accept a CLI flag (e.g. `--manifest-out <path>` or `-o <path>`) to write
   the same `player[]` snippet to a file path of the caller's choosing.
4. Write `coplayer_manifest.json` next to the policy's other artifacts (e.g.
   `players/<game>/<policy>/dist/coplayer_manifest.json`).
5. Be runnable from any working directory.
6. Support an optional `--push <registry-ref>` flag that re-tags and pushes
   to a public registry. Default behavior is local-only.

Implications for the policy's source layout:

- Each policy directory contains its own `Dockerfile`.
- For CogsGuard policies that depend on `players/cogsguard/_shared/`, the
  `Dockerfile` `COPY`s both the policy dir and `_shared/` into the image.
  The on-disk layout still keeps `_shared/` separate; only the build inputs
  consolidate.
- Each policy's CMD (or `--run` argv encoded in its `player[]` snippet's
  `run`) is the player entrypoint that reads `COGAMES_ENGINE_WS_URL`.

A top-level walker can `find players -name build.sh -exec {} \;` to build
every policy. The flat per-game layout (`players/{among_them,cogsguard,...}`)
plus per-policy directories makes this discoverable without orchestration
code.

## 6. Hard constraints, by source

Anchored to the live Coworld source. Verify before relying on edge cases.

- `extra="forbid"` on `CoworldManifest` and all role specs — manifest entries
  fail validation on any unknown field. (`coworld/types.py`)
- `image` must be a string and non-empty wherever it appears in the manifest;
  `_manifest_image_fields` raises if not. (`coworld/upload.py`)
- Player `image` must resolve via `docker image inspect` or the certifier
  fails before uploading. (`certifier.validate_image_references`)
- The image's archived config must be `os=linux, architecture=amd64` or
  `upload-policy` errors before any push.
  (`upload._docker_archive_client_hash`)
- The game container is the source of truth for the player protocol;
  `players/<game>/<policy>/` must implement what the game's
  `protocols.player` URI says.
- A player image only gets `COGAMES_ENGINE_WS_URL` plus its declared
  public `env` plus per-version secrets. (`COGAME_LOG_URI` is permitted
  by the contract but not injected by either runner today — see §1.) It
  does not get the manifest, game config, variant, slot count, or
  per-slot identity outside of the URL query parameters.
- Certification, not just packaging, is required to publish a Coworld. If
  `players/` is asked to produce the `certification.players[]` for a Coworld
  manifest, every `player_id` there must match a declared `player[].id` in
  the same manifest.

## 7. Reference: source files

When this document drifts, check these locations first.

- Manifest types: `metta/packages/coworld/src/coworld/types.py`
- Upload + image push: `metta/packages/coworld/src/coworld/upload.py`
- Submit: `metta/packages/coworld/src/coworld/submit.py`
- Certifier: `metta/packages/coworld/src/coworld/certifier.py`
- Runner: `metta/packages/coworld/src/coworld/runner/runner.py`
- CLI surface: `metta/packages/coworld/src/coworld/cli.py`
- Guides: `metta/packages/coworld/src/coworld/{COWORLD_README.md, GAME_RUNTIME_README.md, CLI_README.md}`
- Among Them protocol: `bitworld/docs/bitscreen_v1.md`
- Cogs vs Clips protocol: `metta/packages/coworld/src/coworld/examples/cogs_vs_clips/game/docs/player_protocol_spec.md`
- Paint Arena protocol: `metta/packages/coworld/src/coworld/examples/paintarena/game/docs/player_protocol_spec.md`
- Among Them manifest example: `bitworld/among_them/coworld_manifest.json`
- Paint Arena example (smallest complete Coworld): `metta/packages/coworld/src/coworld/examples/paintarena/`
