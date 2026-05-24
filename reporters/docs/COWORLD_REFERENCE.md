# Coworld Reference

> Navigation guide for coding agents working in this `reporters` project. **This is not the authoritative Coworld spec — it's an index.** When a section here is too thin, follow the cited paths into `~/coding/metta/` and read the source. Treat the metta docs as the source of truth; treat this file as the map.
>
> **Authoritative entry points in metta** (read these in order when in doubt):
>
> 1. [`packages/coworld/src/coworld/COWORLD_README.md`](../../metta/packages/coworld/src/coworld/COWORLD_README.md) — top-level Coworld guide; the seven roles; the Role Status framework.
> 2. [`packages/coworld/src/coworld/MANIFEST_README.md`](../../metta/packages/coworld/src/coworld/MANIFEST_README.md) — field-by-field manifest reference; runnable shape; `type` field.
> 3. [`packages/coworld/src/coworld/docs/roles/OVERVIEW.md`](../../metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md) — full artifact flow across all seven roles, with diagram.
> 4. [`packages/coworld/src/coworld/docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) — the reporter role contract specifically.
> 5. [`packages/coworld/src/coworld/EPISODE_BUNDLE_README.md`](../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) — the episode-bundle zip every supporting runnable reads.
> 6. [`packages/coworld/src/coworld/GAME_RUNTIME_README.md`](../../metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md) — the game-container runtime contract.
> 7. [`docs/specs/0045-coworld-role-repos.md`](../../metta/docs/specs/0045-coworld-role-repos.md) — per-role-repo structure, `CATALOG.yaml`, `users/<handle>/` subtree.

---

## 1. What this project is

`reporters` is one of six per-role repositories that hold canonical and community implementations of Coworld supporting roles. The six are `Metta-AI/players`, `Metta-AI/commissioners`, `Metta-AI/reporters` (this repo), `Metta-AI/graders`, `Metta-AI/diagnosers`, and `Metta-AI/optimizers`. Each repo is the canonical home for implementations of its role: shared canonical implementations, a per-role `CATALOG.yaml`, a contributor `users/<handle>/` subtree, and optional role-specific tools. See [`docs/specs/0045-coworld-role-repos.md`](../../metta/docs/specs/0045-coworld-role-repos.md) for the per-repo structure.

This repo holds **reporter** implementations. A reporter is a Coworld supporting runnable that turns one episode's artifacts into rendered highlights (Markdown or HTML) and a structured event log (Parquet). Reporters are on-demand: triggered by a CLI command, a hosted button, or an automatic pipeline — **not** automatically by the episode runner.

See [`REPORTER_DESIGN.md`](./REPORTER_DESIGN.md) for this repo's restatement of the canonical reporter contract.

---

## 2. TL;DR for a future agent

- A Coworld manifest declares one `game` and six supporting-role arrays: `player[]`, `commissioner[]`, `reporter[]`, `grader[]`, `diagnoser[]`, `optimizer[]`. **All six arrays are required**, and each must contain at least one entry. Coworlds without a custom implementation for a role reference Softmax's published default image (`softmax/default-reporter:latest`, etc.).
- The reporter role's runtime status is **`contract defined, runtime pending`** per the canonical `COWORLD_README.md` § Role Status table. Contract is written; the platform does not yet auto-invoke reporters in the runner.
- A reporter reads **one** env var (`COGAME_EPISODE_BUNDLE_URI`, a zip) and writes **one** env var (`COGAME_REPORT_URI`, a zip). The output zip carries a top-level `manifest.json` with `reporter_id`, optional `render` (one `.md` or `.html`), and optional `event_log` (one `.parquet` with `(ts, player, key, value)` columns).
- Reporters are **on-demand**, not auto-fired by the runner. The invoker (CLI / button / pipeline) assembles the bundle via the **bundling layer**, sets the env vars, and waits for the container to exit.
- The bundling layer is the seam between in-flight roles (game, player, commissioner) and post-episode roles (reporter, grader, diagnoser, optimizer). It assembles a single zip from the runner's per-URI artifacts on demand, applies access control, and hands the zip to the consumer.
- The reference game to learn from is `packages/coworld/src/coworld/examples/paintarena/` — a complete worked example with game, players, and two reporters under `examples/paintarena/reporter/`. (Note: those reference reporters were written against an earlier pre-canonical contract and will be migrated to the `COGAME_EPISODE_BUNDLE_URI` / `COGAME_REPORT_URI` shape; migration is tracked separately.)
- The reference Coworld CLI lives in metta at [`packages/coworld/src/coworld/CLI_README.md`](../../metta/packages/coworld/src/coworld/CLI_README.md). Bundles are produced via `coworld bundle <ereq_id>`. The planned reporter-runner CLI is `coworld run-reporter` (exact shape TBD).
- Don't confuse Coworld reporters with metta's RL-training "reporters" (`metta/rl/training/{gradient,microbench,stats}_reporter.py`, `tests/devops/runners/reporters/`) — those are training observability, not the Coworld role.
- The "daily tournament report" spec (`docs/specs/0038-daily-tournament-report.md`) is a *separate* concept — a cron job summarizing tournament health into a Google Doc. It is adjacent inspiration, not the Coworld reporter role.

---

## 3. The seven Coworld roles

Every Coworld is built from seven roles. Three (game, player, commissioner) participate during the episode; four (reporter, grader, diagnoser, optimizer) consume the episode's artifacts after it ends.

| Role | Lifecycle | Status | Role doc |
| --- | --- | --- | --- |
| **game** | per-episode, websocket | live | [`docs/roles/game.md`](../../metta/packages/coworld/src/coworld/docs/roles/game.md) |
| **player** | per-episode, websocket | live | [`docs/roles/player.md`](../../metta/packages/coworld/src/coworld/docs/roles/player.md) |
| **commissioner** | per-round, websocket | contract defined, runtime pending | [`docs/roles/commissioner.md`](../../metta/packages/coworld/src/coworld/docs/roles/commissioner.md) |
| **reporter** | post-episode, on-demand | contract defined, runtime pending | [`docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) |
| **grader** | post-episode, on-demand | reserved | [`docs/roles/grader.md`](../../metta/packages/coworld/src/coworld/docs/roles/grader.md) |
| **diagnoser** | post-episode, on-demand | reserved | [`docs/roles/diagnoser.md`](../../metta/packages/coworld/src/coworld/docs/roles/diagnoser.md) |
| **optimizer** | workbench, long-running | reserved | [`docs/roles/optimizer.md`](../../metta/packages/coworld/src/coworld/docs/roles/optimizer.md) |

### Role Status framework

Every role doc opens with one of three status labels, defined in [`COWORLD_README.md` § Role Status](../../metta/packages/coworld/src/coworld/COWORLD_README.md#role-status):

- **live** — the role has a full runtime contract that the platform exercises end to end. The contract is stable enough to build against.
- **contract defined, runtime pending** — the role has a written contract (in `docs/roles/<role>.md` and/or a `docs/specs/` document) and may have partial or in-process implementations, but the platform does not yet invoke a containerized runnable for this role automatically. Manifests must still declare an entry; expect the runtime integration to land soon.
- **reserved** — the role is declared in the manifest schema and has a purpose statement, but no input/output contract or platform integration exists yet. A manifest entry is still required — reference the Softmax-published default image (e.g. `softmax/default-grader:latest`) if a custom implementation does not exist yet.

---

## 4. Artifact flow

The canonical diagram lives in [`docs/roles/OVERVIEW.md`](../../metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md). The short version:

```text
                    DURING EPISODE
                    ══════════════

  commissioner ──schedule_episodes──▶ game ◀──/player── players
                                       │
                                       │ writes per-URI artifacts:
                                       │   results.json
                                       │   replay.json[.z]
                                       │   config.json
                                       │   logs/{game,player}*.log
                                       │   error_info.json (on failure)
                                       ▼

                    POST-EPISODE
                    ════════════

                      bundling layer
                      (on-demand,
                       per consumer
                       request)
                            │
                            │ COGAME_EPISODE_BUNDLE_URI (.zip)
                            ▼
          ┌────────┬────────┴────────┬────────┐
          ▼        ▼                 ▼        ▼
       reporter  grader          diagnoser  optimizer
          │        │                 │        │
          ▼        ▼                 ▼        ▼
  COGAME_REPORT_URI  COGAME_GRADE_URI  COGAME_DIAGNOSIS_URI  policy candidates,
  (.zip:             (.json:           (.zip:                workspaces,
   manifest.json      score +           assays + advice)     evaluation runs
   with render        grader_id)                             (workbench side
   + event_log)                                              effects; final
                                                             policy exported
                                                             via coworld
                                                             upload-policy)
```

**Key invariants:**

- All four post-episode roles are **read-only** with respect to the episode artifacts — they consume, never modify.
- The **bundling layer** is the seam: everything before it is the game's responsibility (per-URI artifacts), everything after it is the consumer's (bundle-zip-in, role-specific-output).
- `COGAME_EPISODE_BUNDLE_URI` is the **canonical input env var** for all four supporting runnables.
- Output env vars are role-specific: `COGAME_REPORT_URI`, `COGAME_GRADE_URI`, `COGAME_DIAGNOSIS_URI`. The optimizer is the only supporting role without a single-output-zip shape — its outputs are side effects in its own state.

---

## 5. The manifest

Defined by the Pydantic models at [`packages/coworld/src/coworld/types.py`](../../metta/packages/coworld/src/coworld/types.py) and serialized to JSON Schema at [`packages/coworld/src/coworld/coworld_manifest_schema.json`](../../metta/packages/coworld/src/coworld/coworld_manifest_schema.json). The field-by-field reference is [`MANIFEST_README.md`](../../metta/packages/coworld/src/coworld/MANIFEST_README.md).

### Top-level shape

| Field | Type | Required? | Purpose |
| --- | --- | --- | --- |
| `$schema` | string | no | URI of the JSON Schema. Informational. |
| `game` | object | yes | The game container, its protocols, schemas, and game-authored docs. |
| `player` | array of runnables | yes | Bundled player images. Must contain at least one entry. |
| `commissioner` | array of runnables | yes | Commissioner runnables. Must contain at least one entry; default available. |
| `reporter` | array of runnables | yes | Reporter runnables. Must contain at least one entry; default available. |
| `grader` | array of runnables | yes | Grader runnables. Must contain at least one entry; default available. |
| `diagnoser` | array of runnables | yes | Diagnoser runnables. Must contain at least one entry; default available. |
| `optimizer` | array of runnables | yes | Optimizer runnables. Must contain at least one entry; default available. |
| `variants` | array of variants | yes | Named game configs. At least one entry. |
| `certification` | object | yes | The short smoke-test episode used by `coworld certify` and `coworld run-episode`. |

The manifest schema rejects unknown top-level fields. The six supporting-runnable arrays are **all required, with at least one entry each** — even if that entry just references a Softmax-published default image.

### Runnable shape

Every runnable shares a base shape:

| Field | Type | Required? | Purpose |
| --- | --- | --- | --- |
| `type` | string | yes | Role identifier; must match the array section (`"reporter"` for entries in `reporter[]`, etc.). |
| `image` | string | yes | Docker image reference. |
| `run` | list of strings | no | Process command overriding the image's `ENTRYPOINT`/`CMD`. |
| `env` | map of string→string | no | Public environment variables. Secrets do not belong here. |
| `source_url` | string | no | URL of the repository/directory/file that builds this runnable. |

Declared role runnables (entries in `player[]`, `commissioner[]`, `reporter[]`, `grader[]`, `diagnoser[]`, `optimizer[]`) add three more required fields, plus the optional `source_url` carried over from the base shape:

| Field | Type | Required? | Purpose |
| --- | --- | --- | --- |
| `id` | string | yes | Stable identifier for this runnable within the manifest. |
| `name` | string | yes | Human-readable display name. |
| `description` | string | yes | Short description of what this runnable does. |
| `source_url` | string | no | Same as base; same field, but recommended for declared runnables. |

The `game.runnable` object does not carry `id`, `name`, or `description` directly — that information lives one level up on the `game` object (`game.name`, `game.description`, `game.owner`, `game.version`).

### One image, many runnables

The Coworld system separates three concepts: a **container image** (an uploaded Docker image, untyped), a **runnable** (a typed role invocation of an image), and a **Coworld release** (the published manifest plus its referenced runnables). One image can implement multiple roles by appearing in different runnable entries with different `run` commands. The paintarena example uses one `paintarena` image to back the game, the player, and two reporters.

`coworld upload-coworld` walks the manifest, collects every distinct `image` reference across all runnable sections, deduplicates them, and uploads each one once.

---

## 6. The episode bundle

The reporter's only input. Full contract: [`EPISODE_BUNDLE_README.md`](../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md).

### What's in a bundle

An episode bundle is a single `.zip` containing one Coworld episode's artifacts, assembled on demand for a consumer:

| Token | File(s) in zip | Source artifact |
| --- | --- | --- |
| `results` | `results.json` | `RESULTS_URI` / local `results.json` |
| `replay` | `replay.json` (uncompressed) | `REPLAY_URI` / local `replay.json[.z]` |
| `config` | `config.json` | runner-written concrete game config |
| `error_info` | `error_info.json` (only present if the episode failed) | `ERROR_INFO_URI` |
| `game_logs` | `logs/game.stdout.log`, `logs/game.stderr.log` | inside `DEBUG_URI`'s zip / local `logs/` |
| `player_logs` | `logs/policy_agent_{slot}.log` (subject to access control) | `POLICY_LOG_URLS` / local `logs/` |

The bundle stores `replay.json` uncompressed; the outer zip already compresses.

### Bundle's inner `manifest.json`

Every bundle contains a `manifest.json` at the zip root describing its contents:

```json
{
  "ereq_id": "ereq_...",
  "status": "success",
  "include": ["results", "replay", "config", "game_logs", "player_logs"],
  "files": {
    "results": "results.json",
    "replay": "replay.json",
    "config": "config.json",
    "game_logs": { "stdout": "logs/game.stdout.log", "stderr": "logs/game.stderr.log" },
    "player_logs": { "0": "logs/policy_agent_0.log", "1": "logs/policy_agent_1.log" }
  }
}
```

`status` is `"success"` or `"failed"`; `include` echoes the tokens that the bundle was built with, after access-control filtering; consumers should read from `files` rather than hard-coding paths.

### Requesting a bundle

Three surfaces, identical bundles:

```bash
# CLI
uv run coworld bundle <ereq_id> --output ep.zip
uv run coworld bundle <ereq_id> --output ep.zip --include results,replay,config
```

```text
# Backend API
GET /v2/episodes/{ereq_id}/bundle?include=results,replay,player_logs
```

```python
# Library
from coworld.bundle import build_episode_bundle, BundleSource
bundle_bytes = build_episode_bundle(
    source=BundleSource.local(workspace_path) | BundleSource.hosted(ereq_id),
    include=["results", "replay", "config"],
)
```

### Access control

The bundling layer applies the same per-artifact authorization model the existing artifact endpoints use, plus one additional rule for player logs:

- `results`, `replay`, `config`, `error_info`, `game_logs`: anyone with episode access can include them.
- `player_logs`: by default, the bundle includes only the logs for player slots controlled by policy versions the requester owns. Softmax-internal requesters may receive all player logs.

If a requester asks for an `include` token they are not permitted to receive, the bundling layer silently omits that token. The returned `manifest.json`'s `include` field reflects what was actually delivered.

**Game authors:** game-container stdout and stderr are surfaced to anyone with episode access via the `game_logs` token. Do not write secrets to those streams.

---

## 7. The reporter role

Full contract: [`docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md). Local restatement plus repo-local notes: [`REPORTER_DESIGN.md`](./REPORTER_DESIGN.md).

### Where it lives in the manifest

`manifest.reporter[]`, with `type: "reporter"` on every entry. At least one entry required; Coworlds without a custom reporter may reference `softmax/default-reporter:latest`.

### Input / output

- **Input** (one env var): `COGAME_EPISODE_BUNDLE_URI` — URI of an episode-bundle zip (see [§6](#6-the-episode-bundle)). The reporter reads the zip, inspects the inner `manifest.json`, and processes the files it cares about.
- **Output** (one env var): `COGAME_REPORT_URI` — URI where the reporter writes its single output zip. The zip should contain a top-level `manifest.json` flagging the `render` target (one `.md` or `.html`) and the `event_log` (one Parquet with `(ts, player, key, value)` columns). All other files in the zip are free-form auxiliary assets.

### Execution

**On-demand.** The episode runner does not invoke reporters. The invoker — CLI command (planned: `coworld run-reporter`), hosted button, or automatic Column pipeline — is responsible for assembling the bundle, setting `COGAME_EPISODE_BUNDLE_URI` and `COGAME_REPORT_URI`, and waiting for the container to exit.

### Determinism

Not required, but preferred. Deterministic reporters enable caching and reproducible testing. LLM-based or otherwise non-deterministic reporters are valid.

---

## 8. The CLI surface

Full reference: [`CLI_README.md`](../../metta/packages/coworld/src/coworld/CLI_README.md).

### Local / package commands

```text
coworld download <id-or-name> [--output-dir ...]   # fetch manifest + image refs
coworld make-policy <starter-name> [-o dir]         # copy a starter policy template
coworld run-episode <manifest> [player images...]   # local episode (Docker)
coworld play <manifest> [player images...]          # local interactive (opens browser)
coworld certify <manifest>                          # smoke-test + validation
coworld upload-coworld <manifest>                   # publish a Coworld
coworld upload-policy <image> --name <name>         # publish a policy version
coworld submit <policy> --league <league_id>        # enter league
coworld list / show / images                        # inspect published coworlds/images
```

### Episode bundles

```text
coworld bundle <ereq_id> --output ep.zip
coworld bundle <ereq_id> --output ep.zip --include results,replay,config
```

### Tournament inspection (via Observatory API)

```text
coworld leagues / divisions / rounds / pools / results / memberships / submissions
coworld episodes / episode-stats / episode-results / episode-logs
coworld replays / replay-open
coworld hosted-game create / join
```

### Reporter invocation (planned)

`coworld run-reporter` is the planned reporter-runner subcommand; exact shape is still being settled. Same planned shape for `coworld run-grader`, `coworld run-diagnoser`. See [`docs/roles/reporter.md` § Execution](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md#execution).

---

## 9. Per-role-repo structure (spec 0045)

Per [`docs/specs/0045-coworld-role-repos.md`](../../metta/docs/specs/0045-coworld-role-repos.md), every role repo (including this one) follows a consistent layout:

```text
Metta-AI/<role>s/
  README.md
  CATALOG.yaml                # canonical list of implementations in this repo
  <role>s/                    # shared canonical implementations
    <impl-name>/
      README.md
      Dockerfile
      ...
  users/                      # contributor experiment subtree
    <handle>/
      <project>/
        README.md
        Dockerfile
        ...
  tools/                      # role-specific tools (optional)
```

### `CATALOG.yaml`

Each role repo ships a `CATALOG.yaml` at its repo root listing every implementation. Each entry:

| Field | Required? | Purpose |
| --- | --- | --- |
| `name` | required | Unique identifier within the repo (kebab-case). |
| `image` | required | Runtime Docker image reference. |
| `source` | required | Relative path from repo root (e.g. `reporters/paint_arena/paint_arena_summarizer`). |
| `source_url` | required | Absolute GitHub URL for the source. |
| `status` | required | One of `active`, `starter`, `experimental`, `archived`. |
| `target` | required | Target game or domain (e.g. `paint_arena`, `among_them`, or `*` for game-agnostic). |
| `owner` | required | Maintainer email or GitHub handle. |
| `description` | required | One-line summary. |
| `family` | optional | Style/family label (`symbolic`, `neural`, `cyborg`, etc.). |
| `since` | optional | First version of this repo in which the implementation appeared. |

**Authoritative:** an implementation exists in a role repo if and only if it has an entry in `CATALOG.yaml`. Source present on disk without a catalog entry is incomplete; catalog entries without source are broken.

### `users/<handle>/<project>/`

The contributor experiment subtree. Researchers and external collaborators can develop role implementations inside the role repo without merging into the canonical `<role>s/` tree.

### `tools/`

Optional, role-specific. For reporters, this might house repro/replay harnesses, fixtures, or benchmark scripts. Cross-role utilities live in `Metta-AI/coworld` or `Metta-AI/metta`, not here.

---

## 10. Tournament infrastructure (Observatory)

Reporters are produced and consumed in this stack:

- **App backend**: `app_backend/` in metta — Observatory FastAPI server (PostgreSQL via `alembic/`). Owns leagues, divisions, rounds, pools, memberships, submissions, episode requests, results, replay metadata. The bundling layer exposes `GET /v2/episodes/{ereq_id}/bundle` as the hosted bundle surface.
- **Frontend**: `web/` in metta (Observatory, softmax.com, gridworks workspaces).
- **Auth**: `softmax-cli` (in `packages/softmax-cli`) handles login. `coworld[auth]` extra pulls it in.

How reporter outputs reach Observatory surfaces (which API endpoints, which UI panel, which CLI commands surface them) is not yet documented as a canonical contract in metta — the role doc explicitly says "runtime pending". When this lands in metta, sync it back here.

---

## 11. Things that are easy to get wrong (gotchas)

1. **All six supporting-role arrays are required.** Even when the Coworld uses a default image for that role, the array must be declared with at least one entry. The manifest schema rejects missing arrays.
2. **`game` is a single object, not an array.** Identifying metadata (`name`, `version`, `description`, `owner`) lives on `game` itself, not on `game.runnable`.
3. **One image, many runnables.** Don't assume a separate image per role. One `paintarena` image can back the game, the player, and one or more reporters.
4. **`tokens` are runner-injected.** Authored configs (variants, certification) must omit `tokens`. The schema requires them at runtime; the runner adds them.
5. **Reporters are on-demand, not auto-fired.** A consumer assembles the bundle and invokes the reporter. The episode runner does not.
6. **Bundle access control is filter-then-deliver.** A requester asking for `player_logs` they don't own gets a bundle whose `manifest.json` omits those logs; the request doesn't fail. Check `manifest.include` before reading.
7. **Reporter output: `manifest.json`, not `render.txt`.** The canonical output zip's render manifest is JSON with structured fields (`reporter_id`, `render`, `event_log`), not a text file listing paths. Pre-canonical drafts and older example reporters used `render.txt`; that name is **not** the canonical contract.
8. **At most one `render` and at most one `event_log` per output.** The output `manifest.json` flags a single `.md` or `.html` for inline rendering and a single Parquet for the event log. Multiple auxiliary files are fine; only one of each gets the privileged role.
9. **`event_log` schema is fixed.** `(ts: int64, player: int64, key: string, value: string)`. `player = -1` for global events. Structured `value`s are JSON-encoded.
10. **Word collision with metta's training "reporters".** `metta/rl/training/{gradient,microbench,stats}_reporter.py` and `tests/devops/runners/reporters/` are unrelated. Don't conflate.
11. **Word collision with the daily tournament report.** `docs/specs/0038-daily-tournament-report.md` is a separate cron-job feature, not the Coworld role.
12. **CATALOG.yaml is the source of truth.** Adding a reporter to the repo without adding a catalog entry leaves it invisible to tooling; adding a catalog entry without a real source path is a broken entry.

---

## 12. Glossary

> Each term cites the most authoritative metta doc.

- **Coworld** — game + players + supporting runnables + manifest = the Softmax v2 tournament unit. [`COWORLD_README.md`](../../metta/packages/coworld/src/coworld/COWORLD_README.md).
- **Manifest** — the `coworld_manifest.json` file. Schema at `coworld_manifest_schema.json`; Pydantic source at `types.py`; field reference [`MANIFEST_README.md`](../../metta/packages/coworld/src/coworld/MANIFEST_README.md).
- **Role** — one of `game`, `player`, `commissioner`, `reporter`, `grader`, `diagnoser`, `optimizer`. [`docs/roles/OVERVIEW.md`](../../metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md).
- **Runnable** — image + optional `run` argv + optional public `env` + (for declared role runnables) `id` / `name` / `description` / optional `source_url`. The shared shape behind every role. [`MANIFEST_README.md` § Runnable Shape](../../metta/packages/coworld/src/coworld/MANIFEST_README.md#runnable-shape).
- **Slot** — a player position in an episode (0, 1, 2, …). The slot count is fixed by `len(tokens)` in the game config. [`GAME_RUNTIME_README.md`](../../metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md).
- **Token** — per-slot, per-episode secret string. Runner-generated; the game must reject invalid `(slot, token)` pairs.
- **Variant** — named preset game config. `CoworldVariant` in `types.py`.
- **Certification fixture** — small embedded `(game_config, players)` pair used by `coworld certify` and as the default for `coworld run-episode`.
- **Results** — JSON matching `game.results_schema`. Must include `scores`. Written to `COGAME_RESULTS_URI`.
- **Replay** — game-owned artifact written to `COGAME_SAVE_REPLAY_URI`. Replayed by running the game image with `COGAME_REPLAY_SERVER=1`.
- **Episode bundle** — single `.zip` containing one episode's artifacts (results, replay, config, optional logs, optional error_info), with a top-level `manifest.json`. Assembled on demand by the bundling layer. The input to every post-episode supporting runnable. [`EPISODE_BUNDLE_README.md`](../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md).
- **Bundling layer** — the seam between in-flight roles (which write per-URI artifacts) and post-episode roles (which read bundles). Assembles bundles on demand, applies access control, stores nothing of its own.
- **Reporter** — the role this repo holds implementations for. On-demand container that reads `COGAME_EPISODE_BUNDLE_URI` (a zip) and writes `COGAME_REPORT_URI` (a zip with `manifest.json` flagging `render` and `event_log`). [`docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md), [`REPORTER_DESIGN.md`](./REPORTER_DESIGN.md).
- **Grader** — emits a scalar score for how interesting/useful an episode was. Reads bundle, writes JSON with `{score, grader_id}` to `COGAME_GRADE_URI`. Status: reserved. [`docs/roles/grader.md`](../../metta/packages/coworld/src/coworld/docs/roles/grader.md).
- **Diagnoser** — evaluates a target policy against an episode. Reads bundle plus `COGAME_TARGET_POLICY_URI`, writes zip to `COGAME_DIAGNOSIS_URI`. Status: reserved (highly tentative). [`docs/roles/diagnoser.md`](../../metta/packages/coworld/src/coworld/docs/roles/diagnoser.md).
- **Optimizer** — long-running workbench for iterating on policies. Side effects (policy workspaces, candidate versions, evaluations) rather than a single output file. Canonical implementation: [`Metta-AI/optimizers`](https://github.com/Metta-AI/optimizers). Status: reserved. [`docs/roles/optimizer.md`](../../metta/packages/coworld/src/coworld/docs/roles/optimizer.md).
- **Commissioner** — round-orchestration role. Per-round WebSocket-served container that schedules episodes, collates results, decides division promotions. Status: contract defined, runtime pending. [`docs/roles/commissioner.md`](../../metta/packages/coworld/src/coworld/docs/roles/commissioner.md).
- **League** — top-level tournament container. Holds divisions.
- **Division** — competitive bracket within a league. Memberships graduate between divisions over time.
- **Round** — scheduled batch of episodes within a division. Drives the commissioner protocol.
- **Pool** — group of episodes within a round.
- **Membership** — a policy version's enrollment in a division.
- **Submission** — a policy version submitted to a league.
- **Policy version** — an immutable upload of a policy container. Created by `coworld upload-policy`.
- **Episode** — one game run. Inputs: manifest + game_config + players + tokens. Outputs: per-URI artifacts (results, replay, logs, config, optional error_info).
- **`COGAME_*` env vars** — game-side artifact URIs (`COGAME_CONFIG_URI`, `COGAME_RESULTS_URI`, `COGAME_SAVE_REPLAY_URI`, optional `COGAME_LOG_URI`) plus supporting-runnable I/O (`COGAME_EPISODE_BUNDLE_URI`, `COGAME_REPORT_URI`, `COGAME_GRADE_URI`, `COGAME_DIAGNOSIS_URI`, `COGAME_TARGET_POLICY_URI`).
- **`COWORLD_PLAYER_WS_URL`** — player-side websocket URL.
- **Observatory** — the public tournament platform. Backend in metta `app_backend/`, frontend in metta `web/`.

---

## 13. "Where do I look for X?" index

| Question | Start here |
| --- | --- |
| What is a Coworld, end to end? | [`COWORLD_README.md`](../../metta/packages/coworld/src/coworld/COWORLD_README.md) |
| Full artifact flow across roles? | [`docs/roles/OVERVIEW.md`](../../metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md) |
| What must a game container do? | [`GAME_RUNTIME_README.md`](../../metta/packages/coworld/src/coworld/GAME_RUNTIME_README.md) |
| What's in the manifest? | [`MANIFEST_README.md`](../../metta/packages/coworld/src/coworld/MANIFEST_README.md); Pydantic source `types.py` |
| What does a reporter do? | [`docs/roles/reporter.md`](../../metta/packages/coworld/src/coworld/docs/roles/reporter.md), [`REPORTER_DESIGN.md`](./REPORTER_DESIGN.md) |
| What's an episode bundle? | [`EPISODE_BUNDLE_README.md`](../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) |
| Per-role-repo structure? | [`docs/specs/0045-coworld-role-repos.md`](../../metta/docs/specs/0045-coworld-role-repos.md) |
| What's a real example manifest? | `worlds/paintarena/coworld_manifest_template.json` (the canonical worked example per metta `MANIFEST_README.md`). |
| What does a real game server look like? | `packages/coworld/src/coworld/examples/paintarena/game/server.py` |
| What does a real player look like? | `packages/coworld/src/coworld/examples/paintarena/player/player.py` |
| What does a real reporter look like? | `packages/coworld/src/coworld/examples/paintarena/reporter/` (note: pre-canonical contract; migration pending) |
| How does an episode run locally? | `packages/coworld/src/coworld/runner/runner.py` + [`RUNNER_README.md`](../../metta/packages/coworld/src/coworld/runner/RUNNER_README.md) |
| How does it run in production? | `packages/coworld/src/coworld/runner/kubernetes_runner.py` + [`KUBERNETES_RUNNER_README.md`](../../metta/packages/coworld/src/coworld/runner/KUBERNETES_RUNNER_README.md) |
| How is a Coworld certified? | `packages/coworld/src/coworld/certifier.py` |
| Commissioner protocol? | `packages/coworld/src/coworld/commissioner/protocol.py` (full request/response protocol) |
| How do I read/write artifact URIs? | `packages/coworld/src/coworld/runner/io.py` (`read_data`, `post_data`, `upload_data`) |
| What CLI commands exist? | [`CLI_README.md`](../../metta/packages/coworld/src/coworld/CLI_README.md) |
| How do I get a bundle? | `coworld bundle <ereq_id>` (CLI), `coworld.bundle.build_episode_bundle` (library), `GET /v2/episodes/{ereq}/bundle` (API). |
| What's the role-repo for my supporting role? | `Metta-AI/players` / `commissioners` / `reporters` / `graders` / `diagnosers` / `optimizers`. See spec 0045. |
| Where do tournament results/replays end up? | metta `app_backend/` (Observatory backend); read models in `coworld/api_client.py`. |
| Where's the daily report cron (not a Coworld reporter)? | metta `docs/specs/0038-daily-tournament-report.md` |
| Where are RL training "reporters" (not Coworld reporters)? | metta `metta/rl/training/{gradient,microbench,stats}_reporter.py`, `tests/devops/runners/reporters/` |
| What's in metta's CLAUDE.md? | `~/coding/metta/CLAUDE.md`, `~/coding/metta/AGENTS.md` |

---

## 14. Keep this file honest

Update this file when:

- A role's status changes in `COWORLD_README.md` § Role Status (e.g. reporter moves from `contract defined, runtime pending` to `live`).
- New `COGAME_*` env vars or new bundle tokens get added to the canonical docs.
- The manifest schema gains/loses fields in `types.py` and `MANIFEST_README.md`.
- New example Coworlds land in `packages/coworld/src/coworld/examples/`.
- The per-role-repo structure in spec 0045 changes (`CATALOG.yaml` schema, `users/` shape, etc.).
- The bundling layer or the supporting-runnable input/output env vars change.

This file is a map. Maps drift. Fix them.
