# Coworld Reference

> Primary navigation guide for coding agents working in this `reporters` project. This is not the authoritative coworld spec — it's an index. When a section here is too thin, follow the cited paths into `~/coding/metta/` and read the source. Treat the metta sources as the source of truth; treat this file as the map.

---

## 1. What this project is

`reporters` is a brand-new component of "coworld". A **coworld** is the unit Softmax v2 uses to run a tournament locally, in hosted play, and in leagues. A coworld bundles one game container, one or more player/policy containers, and a `coworld_manifest.json` describing them. The manifest also declares optional roles — including **reporter** — that the platform can run alongside the game.

The reporter role is **declared in the manifest schema today but has no runtime contract yet, no example implementation, and no invocation site in the runner**. This project is where that contract gets written. See [§7 Reporters in detail](#7-reporters-in-detail).

---

## 2. TL;DR for a future agent

- The canonical coworld package is at `~/coding/metta/packages/coworld/`.
- The game runtime contract is `~/coding/metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md`. Re-read it before changing anything reporter-adjacent.
- The manifest schema is `~/coding/metta/packages/coworld/src/coworld/coworld_manifest_schema.json`, generated from Pydantic models in `~/coding/metta/packages/coworld/src/coworld/types.py`.
- "Roles" (player, grader, **reporter**, commissioner, diagnoser, optimizer) all share the same shape: image + optional `run` argv + optional public `env` (`types.py:35-36`, `0043-user-container-management.md:66-95`).
- Only **commissioner** has a documented protocol so far (`packages/coworld/src/coworld/commissioner/protocol.py`). Reporter, grader, diagnoser, optimizer are stubs in the schema — certification validates their images are reachable, but the runner never launches them.
- The two reference games to learn from are `examples/paintarena/` (simple) and `examples/cogs_vs_clips/` (real tournament).
- Don't confuse coworld reporters with metta's RL-training "reporters" (`metta/rl/training/{gradient,microbench,stats}_reporter.py`, `tests/devops/runners/reporters/`) — those are training observability, not the coworld role.
- The "daily tournament report" spec (`docs/specs/0038-daily-tournament-report.md`) is a *separate* concept — a cron job summarizing tournament health into a Google Doc. It is adjacent inspiration, not the coworld reporter role.

---

## 3. Coworld 101

### What a coworld is

> "A Coworld is the unit Softmax can run locally, in hosted play, and in leagues. It combines: one game container that owns rules, state, viewers, results, and replays; one or more player or policy containers that connect to the game and choose actions; a `coworld_manifest.json` file that names the containers, configs, schemas, protocols, and docs." — `packages/coworld/src/coworld/COWORLD_README.md:7-11`

Key source files:

| File | Purpose |
| --- | --- |
| `packages/coworld/src/coworld/COWORLD_README.md` | High-level coworld overview, CLI quickstart, manifest sections. |
| `packages/coworld/src/coworld/GAME_RUNTIME_README.md` | **Canonical** runtime contract for game containers. |
| `packages/coworld/src/coworld/CLI_README.md` | Coworld CLI command reference. |
| `packages/coworld/src/coworld/coworld_manifest_schema.json` | JSON Schema for the manifest (generated from `types.py`). |
| `packages/coworld/src/coworld/types.py` | Pydantic models — single source of truth for manifest types. |
| `packages/coworld/src/coworld/runner/RUNNER_README.md` | How the local Docker runner launches an episode. |
| `packages/coworld/src/coworld/runner/KUBERNETES_RUNNER_README.md` | How the hosted K8s runner does the same. |
| `docs/specs/0043-user-container-management.md` | "Runnable" concept: image + `run` + `env`. Defines the role list. |

### Episode lifecycle

From `GAME_RUNTIME_README.md:126-145`:

1. Runner gets a job: manifest, concrete game config, players, artifact output URIs.
2. Runner generates one fresh `secrets.token_urlsafe(16)` token per slot.
3. Runner writes a concrete game config including `tokens`.
4. Runner starts the game container with env: `COGAME_CONFIG_URI`, `COGAME_RESULTS_URI`, `COGAME_SAVE_REPLAY_URI`, optional `COGAME_LOG_URI`.
5. Game reads its config, listens on `0.0.0.0:8080`.
6. Runner polls `GET /healthz` until 200.
7. Runner starts one player container per slot.
8. Each player gets `COGAMES_ENGINE_WS_URL=ws://<engine-host>/player?slot=<slot>&token=<token>` (plus optional `COGAME_LOG_URI`).
9. Players connect to `/player`, exchange game-specific messages.
10. Viewers may connect to `/global` (must support late join).
11. Game ends.
12. Game writes results JSON to `COGAME_RESULTS_URI`.
13. Game writes a replay artifact to `COGAME_SAVE_REPLAY_URI`.
14. Runner validates results against `results_schema`, stores results, replay, and logs.

Reporters are **not currently part of this lifecycle**. Designing where they slot in (post-episode? on-demand? batched per round?) is part of this project — see [§7](#7-reporters-in-detail).

---

## 4. The manifest

### Top-level shape

Defined by `CoworldManifest` at `packages/coworld/src/coworld/types.py:120-139`:

```python
class CoworldManifest(BaseModel):
    schema_: str | None = Field(default=None, alias="$schema")
    game: CoworldGameManifest                              # required
    player: list[CoworldDeclaredRoleSpec] = Field(min_length=1)   # required, >=1
    grader: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    reporter: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    commissioner: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    diagnoser: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    optimizer: list[CoworldDeclaredRoleSpec] = Field(default_factory=list)
    variants: list[CoworldVariant] = Field(min_length=1)   # required, >=1
    certification: CoworldCertificationFixture             # required
```

### Game section

`CoworldGameManifest` at `types.py:78-94`:

- `name`, `version` (PEP 440 — validated by `packaging.version.Version`), `description`, `owner`.
- `config_schema`: JSON Schema for the runtime game config. **Must declare `tokens` as a required string array with equal `minItems` and `maxItems`** — that length is the number of player slots (`GAME_RUNTIME_README.md:46-51`).
- `results_schema`: JSON Schema for the final results JSON. **Must include `scores`** (one number per slot) — see `GAME_RUNTIME_README.md:144-145`.
- `runnable`: `CoworldGameRunnableSpec` (`types.py:31-32`) — `image`, optional `run` argv, optional `env`.
- `protocols`: `CoworldProtocolDocs` — required `player` and `global` (aliased from `global_`) docs (`types.py:56-60`).
- `docs`: optional `CoworldDocs` — `readme` + array of `CoworldDocPage` (id, title, content).

### Runnable & document shapes

- `CoworldRunnableSpec` (`types.py:13-18`): `image: str`, `run: list[str]`, `env: dict[str, str]`. The `run` array is the complete argv; if omitted the image's `ENTRYPOINT`/`CMD` is used (`0043-user-container-management.md:88-90`). Secrets do **not** go in `env` — they're attached to the policy version at upload time (`COWORLD_README.md` "Upload And Inspect" section).
- `CoworldDeclaredRunnableSpec` (`types.py:25-28`): adds required `id`, `name`, `description`.
- `CoworldDeclaredRoleSpec` (`types.py:35-36`): adds `type: Literal["player","grader","reporter","commissioner","diagnoser","optimizer"]`.
- `CoworldTextDoc` / `CoworldUriDoc` (`types.py:39-53`): discriminated union on `type`. `uri` docs must match `^https?://`.

### Variants and certification

- `CoworldVariant` (`types.py:97-104`): `id`, `name`, `game_config`, optional `parent_id`, `description`. Used as named configs for leagues and local testing. Variants and certification configs **omit `tokens`** — the runner injects them.
- `CoworldCertificationFixture` (`types.py:107-117`): `game_config` + `players: list[CoworldCertificationPlayer]` where each entry is `{"player_id": "..."}` naming a bundled `player[]` entry. Used by `coworld certify` and as the default for `coworld run-episode`.

### Episode job spec (runner input)

`CoworldEpisodeJobSpec` at `types.py:142-175`. Schema lives at `packages/coworld/src/coworld/runner/episode_request_schema.json`.

```python
class CoworldEpisodeJobSpec(BaseModel):
    manifest: CoworldManifest
    game_config: dict[str, Any]            # game config WITHOUT tokens (runner adds them)
    players: list[CoworldPlayerSpec]
    episode_tags: dict[str, str] = {}
    policy_names: list[str] | None = None  # if set, must match player count
```

---

## 5. Game runtime contract

Re-read `GAME_RUNTIME_README.md` whenever you're unsure. The short version:

### Rollout mode env vars

| Var | Direction | Purpose |
| --- | --- | --- |
| `COGAME_CONFIG_URI` | Game reads | URI of the JSON game config (with injected `tokens`). Must support `file://`. |
| `COGAME_RESULTS_URI` | Game writes | URI to write final results JSON. |
| `COGAME_SAVE_REPLAY_URI` | Game writes | URI to write the replay artifact. |
| `COGAME_LOG_URI` | Game POSTs | Optional. If set, game POSTs newline-separated log lines as plain text. If unset, skip log posting (stdout/stderr always free). |
| `COGAMES_ENGINE_WS_URL` | Player reads | Per-player websocket URL with `slot` and `token` query params. |

`GAME_RUNTIME_README.md:55-71`, player env at lines 134-136.

### Routes the game must serve

On `0.0.0.0:8080`:

- `GET /healthz` — 200 when ready.
- `GET /clients/player?slot=<N>&token=<T>&...` — HTML client for one slot.
- `WEBSOCKET /player?slot=<N>&token=<T>&...` — player connection. Must reject bad `(slot, token)` pairs. Same slot can reconnect with same token mid-episode; state survives disconnects (`GAME_RUNTIME_README.md:53, 96-98`).
- `GET /clients/global` — HTML live viewer.
- `WEBSOCKET /global` — viewer feed. **Must support late join** — give a late viewer enough state to render from that point forward (`GAME_RUNTIME_README.md:93-94`).
- Optional `GET /clients/admin` / `WEBSOCKET /admin?...` — local-only; the platform must not expose this in production.

Browser clients parse the page query string before opening their websocket. If `address` is present, they use it verbatim (after `http→ws` substitution); otherwise they replace `/clients/player` with `/player` and forward the slot/token (`GAME_RUNTIME_README.md:84-91`).

### Replay mode

When `COGAME_REPLAY_SERVER=1` is set, the same image runs as a replay server:

- `GET /healthz`
- `GET /clients/replay?uri=<uri>` — HTML replay viewer.
- `WEBSOCKET /replay?uri=<uri>` — replay control (game-owned protocol).

Replay artifact format is game-owned.

### Hosted resource baseline

Game container, runner worker, each player, replay container: 2 CPU + 2Gi memory requested (not limits). `GAME_RUNTIME_README.md:13-24`.

---

## 6. The roles

| Role | Schema | Protocol? | Invoked by runner today? | Source |
| --- | --- | --- | --- | --- |
| `game` | `CoworldGameRunnableSpec` (`types.py:31`) | `GAME_RUNTIME_README.md` (canonical) | Yes, every episode. | `runner/runner.py` |
| `player` | `CoworldDeclaredRoleSpec` (`types.py:35`) | Game-specific; linked from `game.protocols.player` | Yes, every episode (one per slot). | `runner/runner.py` |
| `grader` | same | None documented | **No.** | stub |
| `reporter` | same | **None documented — this project defines it.** | **No.** | stub |
| `commissioner` | same | `packages/coworld/src/coworld/commissioner/protocol.py` | Not in episode runner — separate tournament orchestration. | full protocol |
| `diagnoser` | same | None documented | **No.** | stub |
| `optimizer` | same | None documented | **No.** | stub |

Certification (`packages/coworld/src/coworld/certifier.py:180-191`) checks that every declared role image is reachable, but the smoke-test episode only launches the game + certification players. Reporter/grader/diagnoser/optimizer images are *validated* but never *executed* in the current pipeline.

### Commissioner — the one role with a real protocol

`packages/coworld/src/coworld/commissioner/protocol.py` defines a stateful round-orchestration protocol the platform uses to drive tournament rounds. It's the closest precedent for what a reporter protocol could look like.

- Inbound (platform → commissioner): `RoundStart` carrying `LeagueInfo`, divisions, memberships, recent results, variants, optional opaque `state` (≤10 MB).
- Outbound (commissioner → platform): `ScheduleEpisodes` (a list of `EpisodeRequest{variant_id, policy_version_ids, seed, tags}`) and `RoundComplete` (final scores, graduation changes, optional `round_display`, optional new `state`).
- All messages are stateless JSON; state continuity is by the platform threading the `state` field forward.

If you're designing the reporter protocol, mirror this discriminated-union, request/response, ≤10 MB-state pattern.

---

## 7. Reporters in detail

### Everything the codebase says about reporter today

1. **Schema enum entry** — `coworld_manifest_schema.json` and `runner/episode_request_schema.json` include `"reporter"` in the role type enum. Pydantic source: `types.py:36`.
2. **Manifest field** — `CoworldManifest.reporter: list[CoworldDeclaredRoleSpec]` defaults to `[]` (`types.py:134`).
3. **Certification reachability check** — `certifier.py:186` iterates `("player", "grader", "reporter", "commissioner", "diagnoser", "optimizer")` and `docker manifest inspect`s every declared image. That's the only place "reporter" appears in non-schema runtime code.
4. **No runner integration** — `runner/runner.py` never launches reporters. There's no command, no env var contract, no input/output convention.
5. **No examples** — neither `examples/paintarena/coworld_manifest.json` nor `examples/cogs_vs_clips/coworld_manifest.json` declares a reporter.
6. **No tests** — `packages/coworld/tests/` has no reporter test file.
7. **CLI silence** — no `coworld` subcommand mentions reporter.
8. **Spec 0043-user-container-management.md** (lines 66-95) uses reporter as an *example* runnable: a `paintarena-reporter` runnable inside a shared `paintarena-runtime` image with `run: ["python", "-m", "paintarena.reporter", "--format=json"]`. Notes from that spec worth carrying into design:
   - "Other roles should be process-style containers unless their role contract later requires networking" (line 94-95). **Default the reporter contract to process-style** — read input URIs from env, write outputs to env-supplied URIs, exit.
   - "If `run` is omitted, the image's default `ENTRYPOINT`/`CMD` is used" (line 89-90).
   - "`env` is for public, reproducible config only. Secrets remain a separate mechanism" (line 92).
   - One image can implement many runnables — game + player + reporter can all share `paintarena-runtime:latest` (line 13-14).

### What reporters are NOT

- **Not the daily tournament report** (`docs/specs/0038-daily-tournament-report.md`): that spec describes a separate cron job that reads `app_backend` directly and writes a Google Doc summary of cross-tournament health/leaderboard/submissions. Same word, different scope. A coworld reporter is per-coworld and per-episode (or per-round); the daily report is platform-wide and per-day.
- **Not RL-training reporters**: `metta/rl/training/{gradient,microbench,stats}_reporter.py` and `tests/devops/runners/reporters/test_datadog_reporter.py` are training-loop observability inside the metta RL stack. They share the noun but are unrelated infrastructure.
- **Not graders**: graders are also stubs, but the natural division is scoring/judging vs. summarizing/communicating. The schema treats them as peers.

### Design space (open questions for this project)

Things the contract you write will need to answer:

- **When does a reporter run?** Per-episode (after results land)? Per-round (over a batch of episodes)? On demand from the CLI/Observatory? Some combination?
- **What inputs does it receive?** Likely some subset of `{results URI, replay URI, logs URI, manifest, episode metadata, round/league context}`. Spec-style hint: mirror the game env contract — `COGAME_RESULTS_URI`, `COGAME_SAVE_REPLAY_URI` (read-only here), `COGAME_LOG_URI` for input plus a new `COREPORT_OUTPUT_URI` (or similar) for output.
- **What outputs does it produce?** JSON metrics? Markdown summaries? HTML pages? Multiple artifacts? How are they discovered later (Observatory? a results bucket?)?
- **Synchronous or detached?** Does the runner wait for it (like the game), or is it dispatched async?
- **Where does it run?** Local Docker `coworld-local` network (like `runner.py`) or only in K8s (like `kubernetes_runner.py`)?
- **Schema for outputs?** Should reporters declare an output schema in the manifest (parallel to `game.results_schema`)?
- **Multiple reporters per coworld?** The manifest already allows `reporter: [...]` to be a list. Do they all run? In what order? Independently?
- **Certification?** Should `coworld certify` invoke declared reporters against the smoke-test episode's artifacts (currently it only checks image reachability)?

These are decisions to be made — not assumptions baked in.

---

## 8. The runner & certification

### Local runner

`packages/coworld/src/coworld/runner/runner.py` + `runner/RUNNER_README.md`.

- Reuses a Docker network `coworld-local`. The game joins as `coworld-game-<run-id>:8080`; players reach it via that DNS name on the shared network. Game port is published on `127.0.0.1:<random>` for browser viewers.
- `EpisodeArtifacts` (`runner.py` near line 34) materializes a workspace with `config.json`, `results.json`, `replay.json`, `logs/`, `game.stdout.log`, `game.stderr.log`, `policy_agent_<slot>.txt`.
- `RunnableLaunchSpec` / `PlayerLaunchSpec` build Docker `docker run` invocations from manifest specs.
- `assert_docker_image_reachable(image, label=...)` is what certification uses to validate images.
- `run_coworld_episode(spec, artifacts, timeout_seconds, verify_replay)` is the top-level entry — generates tokens, writes config, starts containers, waits, collects results.
- `validate_replay=True` in certification spins up the game once more in `COGAME_REPLAY_SERVER=1` mode to verify the replay viewer starts.

### I/O abstraction

`packages/coworld/src/coworld/runner/io.py` (~lines 22-68): `read_data(uri)`, `post_data(uri, data)`, `upload_data(uri, data)` all transparently handle `file://`, bare paths, and `http(s)://`. HTTP writes retry on 429/500/502/503/504. **Reporters should reuse this.**

### Kubernetes runner

`packages/coworld/src/coworld/runner/kubernetes_runner.py` + `KUBERNETES_RUNNER_README.md`. Same contract, K8s Jobs + Service DNS instead of a Docker network. Artifact URIs are typically presigned S3.

### Certification

`packages/coworld/src/coworld/certifier.py`:

| Function | What it does |
| --- | --- |
| `load_coworld_package(path)` (`:48-67`) | Parses manifest JSON, validates against generated JSON Schema, validates Pydantic model, validates `game_config` for every variant + the certification fixture, returns a frozen `CoworldPackage`. |
| `validate_image_references(package)` (`:74-76`) | Calls `docker manifest inspect` for the game image, each certification player image, and every declared role image (player/grader/reporter/commissioner/diagnoser/optimizer). |
| `build_episode_request(package, artifacts)` (`:85-92`) | Builds the runner-facing `CoworldEpisodeJobSpec` for the certification smoke episode. |
| `certify_coworld(manifest_path, ...)` (`:151-177`) | The top-level: validates everything, runs one local episode with the certification fixture, loads results, validates against `results_schema`, confirms replay exists. Returns `CertificationResult`. |

Run via `coworld certify <manifest>`.

---

## 9. CLI surface

Entry points: `packages/coworld/src/coworld/cli.py` and `packages/coworld/src/coworld/tournament_cli.py`. Reference doc: `CLI_README.md`.

### Local / package commands

```text
coworld download <id-or-name> [--output-dir ...]   # fetch manifest + image refs
coworld make-policy <starter-name> [-o dir]         # copy a starter policy template
coworld run-episode <manifest> [player images...]   # local episode (Docker)
coworld play <manifest> [player images...]          # local interactive (opens browser)
coworld certify <manifest>                          # smoke-test + validation
coworld upload-coworld <manifest>                   # publish to Observatory
coworld upload-policy <image> --name <name>         # publish a policy version
coworld submit <policy> --league <league_id>        # enter league
coworld list / show / images                        # inspect published coworlds/images
```

### Tournament inspection (via Observatory API)

```text
coworld leagues / divisions / rounds / pools / results / memberships / submissions
coworld episodes / episode-stats / episode-results / episode-logs
coworld replays / replay-open
coworld hosted-game create/join
```

API client models live in `packages/coworld/src/coworld/api_client.py` (Pydantic models for `LeagueInfo`, `DivisionInfo`, `RoundDetailPublic`, `RoundResultPublic`, `EpisodeStatsResponse`, etc.).

---

## 10. Examples & starter policies

### Reference coworlds in-tree

- `packages/coworld/src/coworld/examples/paintarena/` — minimal reference. Game writes results matching a `scores + painted_tiles + ticks` schema. One bundled `sweep-painter` player. Single `default` 2-player variant. Best place to learn the contract end-to-end. Game server is plain Python+FastAPI.
- `packages/coworld/src/coworld/examples/cogs_vs_clips/` — real Softmax tournament game. 8-player cooperative `cogsguard` mission. Game and player images live in external registries (referenced from the manifest).

### Other examples worth knowing about

- `packages/coworld/src/coworld/policies/amongthemstarter/` — Nim-based starter policy template (the `among_them` starter packaged by `coworld make-policy`). Source of truth for `starter_policy.py:22-40`.
- `packages/cogames/` — game configs/missions/CLI; sister package, not strictly a coworld but useful context for game-side authoring.
- `cogames-agents/`, `cogames_agents/`, `cogames-rl-researcher/` — scripted/evolved/RL policy implementations for cogames-family games. Look here for what a substantive policy looks like beyond the starter.

---

## 11. Tournament infrastructure (Observatory)

- **App backend**: `app_backend/` is the Observatory FastAPI server (PostgreSQL via `alembic/`). It owns leagues, divisions, rounds, pools, memberships, submissions, episode requests, results, and replay metadata. Read its `README.md` and `src/metta/app_backend/` before assuming a schema or endpoint.
- **Frontend**: `web/` (multiple workspaces: Observatory, softmax.com, gridworks).
- **Auth**: `softmax-cli` (in `packages/softmax-cli`) handles login. `coworld[auth]` extra pulls it in.
- **Commissioner protocol**: `packages/coworld/src/coworld/commissioner/protocol.py` — already cited; this is how a commissioner runnable plugs into round orchestration.

If you are designing how reporter outputs get persisted and exposed, this is where they will need to live. Start by reading `app_backend/CLAUDE.md` and the relevant Alembic migrations.

---

## 12. Replays & results artifacts

- **Results**: JSON conforming to `game.results_schema`, written to `COGAME_RESULTS_URI`. Must include a `scores` array (one number per slot); games are free to add more fields if the schema declares them.
- **Replays**: game-owned format, written to `COGAME_SAVE_REPLAY_URI`. May be compressed (the local runner zlib-compresses if not already). Replayed by running the same image with `COGAME_REPLAY_SERVER=1`.
- **Logs**: stdout/stderr always captured by the runner. If `COGAME_LOG_URI` is set, the game (and optionally each player) POSTs newline-separated text lines to that URL.

These three artifacts are the obvious input candidates for a reporter.

---

## 13. Things that are easy to get wrong (gotchas)

1. **`game` is a `Literal` type, not a role list.** Don't add `game` to the `for section in (...)` loop in `certifier.py:186` — the game is its own field on the manifest, not in any role list.
2. **`tokens` are runner-injected.** Authored configs (variants, certification) must omit `tokens`. The schema requires them at runtime, the runner adds them. (`GAME_RUNTIME_README.md:50-51`)
3. **Protocol docs are URIs to public HTTP(S).** `CoworldUriDoc.value` is `pattern=r"^https?://"`. Upload does not bundle local Markdown — public docs need public URLs (`COWORLD_README.md` "Manifest" section; `types.py:46-50`).
4. **One image, many runnables.** Don't assume a separate image per role. Spec 0043 explicitly endorses one shared image with different `run` argv per runnable.
5. **Two specs share number 0043.** `docs/specs/0043-user-container-management.md` and `docs/specs/0043-softmax-database-consolidation.md` both exist. The reporter-relevant one is the **user-container-management** spec.
6. **Word collision with metta's training "reporters".** `metta/rl/training/*_reporter.py` and `tests/devops/runners/reporters/` are unrelated. Don't conflate.
7. **Word collision with the daily tournament report.** `docs/specs/0038-daily-tournament-report.md` is a separate cron-job feature, not the coworld role.
8. **Late viewers must work.** `WEBSOCKET /global` must send a join snapshot, not just live deltas. Any reporter that drives or simulates a viewer has the same requirement.
9. **Player slot reconnect must work.** Same `(slot, token)` can reattach mid-episode; game state survives the disconnect (`GAME_RUNTIME_README.md:96-98`).
10. **Hosted networking is K8s Service DNS, local is `coworld-local` Docker network.** Don't bake `127.0.0.1` into player code — that's only for browser viewers on the host machine (`COWORLD_README.md` "Player Loop" section).

---

## 14. Glossary

> Each term cites the most authoritative file:line we found. When in doubt, follow the citation.

- **Coworld** — game + players + manifest = the Softmax v2 tournament unit. `packages/coworld/src/coworld/COWORLD_README.md:7-11`. Type: `CoworldManifest` at `types.py:120-139`.
- **Game** — the container that owns rules, state, viewers, results, and replays. Always exactly one per episode. `CoworldGameManifest` at `types.py:78-94`.
- **Player / Policy** — a container that connects to the game over websocket and chooses actions. Distinguish: a **player** is a slot in an episode; a **policy** is an uploaded versioned container that can fill player slots. `CoworldPlayerSpec` at `types.py:21`. Player upload at `submit.py` / `upload.py`.
- **Slot** — a player position in an episode (0, 1, 2, …). The slot count is fixed by `len(tokens)` in the game config. `GAME_RUNTIME_README.md:45-51`.
- **Token** — per-slot, per-episode secret string. Runner generates fresh via `secrets.token_urlsafe(16)`. The game must reject invalid `(slot, token)` pairs. `GAME_RUNTIME_README.md:53`, `runner/runner.py` around the token generation site.
- **Runnable** — image + optional `run` argv + optional public `env`. The shared shape behind every role. `CoworldRunnableSpec` at `types.py:13-18`. Spec: `docs/specs/0043-user-container-management.md:66-95`.
- **Role** — one of `player`, `grader`, `reporter`, `commissioner`, `diagnoser`, `optimizer`. All shaped as `CoworldDeclaredRoleSpec` (`types.py:35-36`). Only `player` and (separately, outside the episode runner) `commissioner` have runtime contracts today.
- **Variant** — named preset game config, e.g. map/difficulty/league preset. `CoworldVariant` at `types.py:97-104`.
- **Certification fixture** — small embedded `(game_config, players)` pair used by `coworld certify` and as the default for `coworld run-episode`. `CoworldCertificationFixture` at `types.py:113-117`. Smoke-test logic in `certifier.py:151-177`.
- **Manifest** — the `coworld_manifest.json` file. Schema at `coworld_manifest_schema.json`; Pydantic source at `types.py`.
- **Results** — JSON matching `game.results_schema`. Must include `scores`. Written to `COGAME_RESULTS_URI`. `GAME_RUNTIME_README.md:142-145`.
- **Replay** — game-owned artifact written to `COGAME_SAVE_REPLAY_URI`. Replayed by running the game image with `COGAME_REPLAY_SERVER=1`. `GAME_RUNTIME_README.md:107-124`.
- **Reporter** — declared role for generating reports from episodes. Schema exists, runtime contract does not (yet). This project. `types.py:134`, `certifier.py:186`, `docs/specs/0043-user-container-management.md:66-95`.
- **Grader / Diagnoser / Optimizer** — declared but undefined roles, peers of reporter. `types.py:133, 136-137`.
- **Commissioner** — round-orchestration role with a documented protocol. `packages/coworld/src/coworld/commissioner/protocol.py`.
- **League** — top-level tournament container. Holds divisions. API model in `api_client.py`.
- **Division** — competitive bracket within a league. Memberships graduate between divisions over time. `api_client.py`.
- **Round** — scheduled batch of episodes within a division. Drives the commissioner protocol. `commissioner/protocol.py`.
- **Pool** — group of episodes within a round (e.g. for round-robin scheduling). `api_client.py`.
- **Membership** — a policy version's enrollment in a division. `api_client.py`.
- **Submission** — a policy version submitted to a league. `submit.py`, `tournament_cli.py`.
- **Policy version** — an immutable upload of a policy container. Created by `coworld upload-policy`. `upload.py`.
- **Episode** — one game run. Inputs: manifest + game_config + players + tokens. Outputs: results, replay, logs.
- **Episode request** — runner-facing job spec for one episode. `CoworldEpisodeJobSpec` at `types.py:142-175`. Schema: `runner/episode_request_schema.json`.
- **Observatory** — the public tournament platform. Backend in `app_backend/`, frontend in `web/`.
- **`COGAME_*` env vars** — game-side artifact URIs and log endpoint. See [§5](#5-game-runtime-contract).
- **`COGAMES_ENGINE_WS_URL`** — player-side websocket URL (note the `S`: `COGAMES` plural). `GAME_RUNTIME_README.md:135`.

---

## 15. "Where do I look for X?" index

| Question | Start here |
| --- | --- |
| What is a coworld, end to end? | `packages/coworld/src/coworld/COWORLD_README.md` |
| What must a game container do? | `packages/coworld/src/coworld/GAME_RUNTIME_README.md` |
| What's in the manifest? | `packages/coworld/src/coworld/types.py` + `coworld_manifest_schema.json` |
| What does spec 0043 say about runnables/roles? | `docs/specs/0043-user-container-management.md:66-95` |
| Where is reporter mentioned in code? | `types.py:36, 134`; `certifier.py:186`; `coworld_manifest_schema.json`; `runner/episode_request_schema.json`. (That's all.) |
| What's a real example manifest? | `examples/paintarena/coworld_manifest.json` (simple), `examples/cogs_vs_clips/coworld_manifest.json` (real). |
| What does a real game server look like? | `examples/paintarena/game/server.py` |
| What does a real player look like? | `examples/paintarena/player/player.py`; `policies/amongthemstarter/` |
| How does an episode actually run locally? | `runner/runner.py` + `runner/RUNNER_README.md` |
| How does it run in production? | `runner/kubernetes_runner.py` + `runner/KUBERNETES_RUNNER_README.md` |
| How is a coworld certified? | `certifier.py` |
| What does the commissioner protocol look like? | `commissioner/protocol.py` (best precedent for a new role protocol) |
| Where do results/replays end up? | `app_backend/` (Observatory backend), `api_client.py` (read models) |
| Where are tournaments orchestrated? | `app_backend/`, `tournament_cli.py`, `commissioner/` |
| Where are leagues/divisions defined in the API? | `packages/coworld/src/coworld/api_client.py` |
| Where's the daily report cron (not a coworld reporter)? | `docs/specs/0038-daily-tournament-report.md` |
| Where are RL training "reporters" (not coworld reporters)? | `metta/rl/training/{gradient,microbench,stats}_reporter.py`, `tests/devops/runners/reporters/` |
| How do I read/write artifact URIs? | `runner/io.py` (`read_data`, `post_data`, `upload_data`) |
| What CLI commands exist? | `cli.py` + `tournament_cli.py` + `CLI_README.md` |
| Where do I configure auth for hitting Observatory? | `softmax-cli` package; `coworld[auth]` extra; `coworld login` flow |
| What's the deployment stack? | `devops/` (Terraform, Helm, SkyPilot, K8s on EKS) |
| Is there a CLAUDE.md in metta? | `~/coding/metta/CLAUDE.md`, `~/coding/metta/AGENTS.md`, `packages/coworld/AGENTS.md` if present |

---

## 16. Keep this file honest

When you do work in this project, update this file if any of the following change in the metta repo:

- A new role gets a documented protocol (especially **reporter** — when we write its contract here, mirror it back to a spec/PR in metta).
- New `COGAME_*` env vars or new routes get added to `GAME_RUNTIME_README.md`.
- The manifest schema gains/loses fields in `types.py`.
- New example coworlds land in `packages/coworld/src/coworld/examples/`.
- The Observatory data model changes in ways that affect how reporter outputs would be stored or served.

This file is a map. Maps drift. Fix them.
