# Reporter Design

> **Status:** v1 contract complete (D1–D10 resolved 2026-05-19). Living document — implementation work and any post-v1 questions will surface here.
> **Last meaningful update:** 2026-05-19 — Finalization pass: added executive summary, consolidated deferred ideas, reframed as v1 specification.
> **Companion docs:** [`COWORLD_REFERENCE.md`](./COWORLD_REFERENCE.md) for coworld background. The canonical reporter-author-facing runtime contract (`REPORTER_RUNTIME_README.md`) will live in metta at `packages/coworld/src/coworld/REPORTER_RUNTIME_README.md` when implementation lands.

This document records the v1 contract for the coworld **reporter** role and the deferred ideas that didn't make v1. The reporter role was declared in the coworld manifest schema before this work began but had no runtime contract, no example implementation, and no invocation site in the runner; this document is the design that gives it those things.

The structure: **executive summary** (one-screen TL;DR) → **goals and non-goals** → **hard constraints** (forced by existing infrastructure) → **adopted invariants and defaults** (v1 contract, decided across D1–D10) → **v1 contract reference** (the concrete shape an implementation reads off this doc) → **open questions** (placeholder for what surfaces during implementation) → **decisions log** (D1–D10, with rationale) → **deferred ideas** (what's explicitly not in v1, organized by theme) → **changelog**.

---

## Executive Summary

**A reporter is a process-style container declared in a coworld manifest under `reporter: [...]`.** When an episode completes successfully with valid artifacts, the runner invokes every declared reporter in parallel against those artifacts. Each reporter reads what it needs from env-supplied URIs, writes a single JSON envelope to its output URI, and exits.

### The v1 contract in one screen

| Aspect | v1 |
| --- | --- |
| **Trigger** | Per-episode, after game/player containers exit successfully and artifacts validate. (D1, D6) |
| **Lifecycle location** | Co-located with the episode runner (local Docker or hosted K8s). No separate dispatch in v1. (D6) |
| **Behavior contract** | Pure function of inputs; determinism preferred but not required. (D1) |
| **Inputs** | Standard env-supplied URIs (`COGAME_*`) for results, replay, optional logs, episode metadata, manifest; plus `COGAME_REPORTER_ID`. (D2, D4) |
| **Output** | Single JSON envelope `{version, artifacts: [{id, content_type, encoding?, content}]}` written to `COGAME_REPORT_OUTPUT_URI`. Empty `artifacts: []` allowed. (D3) |
| **First-class content types** | `text/markdown`, `text/plain`, `application/json`, `image/png` (base64). HTML stored but never inline-rendered. (D3) |
| **Multi-reporter** | All declared reporters run in parallel with isolated inputs/outputs/failures. Resource baseline 2 CPU + 2Gi each. (D4) |
| **Failure semantics** | Five-code taxonomy (`start_failed`, `nonzero_exit`, `timeout`, `missing_output`, `invalid_envelope`). One retry on `timeout` only. Per-reporter status records. Runner exit code orthogonal to reporter status. (D8) |
| **Certification** | `coworld certify` exercises every declared reporter end-to-end against the smoke episode using synthetic metadata; strict failure handling. (D5) |
| **Observatory** | Four new API endpoints per episode (list, detail, artifact-direct, logs). Inline rendering for first-class content types with Markdown artifact-id substitution. CLI parity: `coworld reports`, `coworld report-show`, `coworld report-download`. (D9) |
| **Manifest changes** | None. `CoworldDeclaredRoleSpec` stays as-is. Per-artifact schema declaration shelved. (D7) |
| **Naming** | All env vars under `COGAME_` prefix. Canonical doc: `REPORTER_RUNTIME_README.md`. (D10) |

### What's not in v1

See §9 (Deferred ideas) for the consolidated list. Highlights: per-round triggers, on-demand reruns, pipelining between reporters, per-artifact JSON Schema validation, per-reporter resource/timeout overrides, cross-episode aggregation in Observatory.

### Implementation footprint in metta

The v1 contract requires changes across four areas of the monorepo (see individual decisions for the source pointers):

- **`packages/coworld/`** — runner (both Docker and K8s variants), certifier, the new envelope schema, the canonical `REPORTER_RUNTIME_README.md` runtime contract.
- **`app_backend/`** — four new FastAPI routes + database storage for reporter status records + Alembic migration.
- **`web/observatory`** — new "Reports" panel on the episode view; per-content-type renderers; Markdown artifact-id substitution at render time.
- **`packages/coworld/src/coworld/tournament_cli.py`** — three new CLI commands paralleling existing tournament-inspection patterns; corresponding client model classes in `api_client.py`.

---

## 1. Problem statement

A coworld is a self-contained tournament unit — one game container, one or more player containers, a manifest. The manifest already permits each coworld to declare one or more **reporters**: containers whose job is to turn episode outputs (results, replay, logs) into reports — structured data, summaries, visualizations, or whatever a coworld author wants to produce post-episode.

Before this work, the platform treated declared reporters as inert metadata: certification verified their images were pullable, and nothing else happened. The v1 contract in this document makes reporters actually run, produce discoverable outputs, and gives third-party coworld authors a contract clear enough to build their own.

---

## 2. Goals

1. Define a **runtime contract** for the reporter role — process-style, per-episode trigger, reporters treated as pure functions of their inputs — coherent with and as simple as possible compared to the existing game and player contracts.
2. Ship at least one **reference reporter implementation** (paintarena is the natural target — spec 0043 already uses `paintarena-reporter` as its worked example).
3. Make declared reporters **actually execute** as part of the coworld lifecycle, not just get image-validated.
4. Persist reporter outputs so they are **discoverable from Observatory**.
5. Document the contract as a peer to `GAME_RUNTIME_README.md` — as a new `REPORTER_RUNTIME_README.md` in `packages/coworld/src/coworld/` (D10).
6. Extend `coworld certify` to actually invoke declared reporters against the smoke-test episode's artifacts and validate their outputs.

## 3. Non-goals

1. **Not a bidirectional protocol.** The commissioner already covers stateful round orchestration. Reporters should be simpler: consume artifacts, produce artifacts, exit. Going to a request/response protocol is a deliberate escalation, not the default.
2. **Not cross-coworld reporting.** Daily / platform-wide rollups are spec 0038's domain (the daily tournament report). A coworld reporter is scoped to its coworld.
3. **Not long-running services.** Spec 0043 explicitly directs non-game roles to be process-style "unless their role contract later requires networking" — we adopt that as a starting constraint.
4. **Not a replacement for the game's results file.** The game still writes its results JSON to `COGAME_RESULTS_URI`; reporters consume that, they don't replace it.
5. **Not a replay format definition.** Replay format remains game-owned. Reporters that need replay-format knowledge consume the same artifacts game-side replay viewers consume.
6. **No per-round trigger in v1.** Per-round reporters (summarizing across the episodes in a round) are a real future need but require artifact plumbing that doesn't exist yet (round episode set, commissioner round-display, etc.). Deferred to a future version with its own design pass. See decisions log entry **D1**.
7. **No on-demand trigger in v1.** With reporters required to be pure functions of their inputs (D1), a user-triggered "rerun" produces the same output as the original run unless we expose user-controllable knobs. There is no clear surface for such knobs in Observatory today, so on-demand is shelved (not actively deferred). Revisit if a concrete use case appears.

---

## 4. Hard constraints (from existing infrastructure)

These are forced by code that already exists. Violating one of these requires changing the metta repo.

1. **Manifest shape is fixed.** Each reporter entry must conform to `CoworldDeclaredRoleSpec` at `packages/coworld/src/coworld/types.py:35-36`: `id`, `name`, `description`, `image`, optional `run: list[str]`, optional `env: dict[str, str]`, `type: "reporter"`.
2. **`reporter` is an optional list, not a singleton.** The manifest field is `list[CoworldDeclaredRoleSpec]` defaulting to `[]` (`types.py:134`). The contract must work for zero, one, or many declared reporters.
3. **No Docker `command`/`args` split.** The public runnable API uses a single `run` array as the complete argv. If `run` is omitted, the image's default `ENTRYPOINT`/`CMD` is used (spec 0043 lines 88-90).
4. **`env` is for public, reproducible config only.** Secrets must come through a separate mechanism, parallel to how `coworld upload-policy --secret-env` works for player containers today (`COWORLD_README.md` "Upload And Inspect"; spec 0043 line 92).
5. **Image reachability is a certification requirement.** `certifier.py:186` already checks every declared role image. New runner integration must not regress that.
6. **I/O must work across `file://`, `http(s)://`, and presigned S3.** Local Docker uses `file://`; hosted K8s uses presigned HTTP URLs over S3. Use `packages/coworld/src/coworld/runner/io.py` (`read_data`, `post_data`, `upload_data`) — it already handles all three with retries on 429/5xx.
7. **Process-style by default.** Spec 0043 lines 93-95 directs non-game roles to be process containers: no ports, no health checks, no listening server. A reporter starts, does its work, exits.
8. **No regression of existing roles.** Whatever lifecycle hook gets added for reporters must not change the existing game/player episode lifecycle described in `GAME_RUNTIME_README.md:126-145`.

---

## 5. Adopted invariants and defaults

A mix of two kinds of items: **inherited conventions** from neighboring roles (loud, deliberate to diverge from) and **adopted invariants** decided in this design (marked with their decisions-log entry). Both are part of the v1 contract.

1. **Env-var-supplied URIs for I/O.** Games use `COGAME_CONFIG_URI`, `COGAME_RESULTS_URI`, `COGAME_SAVE_REPLAY_URI`, optional `COGAME_LOG_URI`. Players use `COGAMES_ENGINE_WS_URL`. Reporters should follow the same shape — input/output paths arrive through environment variables, the container reads/writes URIs (not fixed paths).
2. **`COGAME_*` env namespace.** Existing game-side variables use the `COGAME_` prefix. Reporter-specific variables should probably do the same (e.g. `COGAME_REPORT_OUTPUT_URI`) for discoverability, even though "report" isn't part of the literal game contract.
3. **Stateless containers; state on the platform.** Players reconnect, games survive disconnects, commissioner state is threaded by the platform. Reporters should not hold local state across invocations.
4. **One image, many roles.** Spec 0043 lines 13-14 explicitly endorses one `paintarena-runtime` image providing the game, player, and reporter via different `run` argv. The contract should make this comfortable (no requirements that force a separate image).
5. **No reporter-side schema declarations in the manifest.** *(Resolved 2026-05-19, D7.)* The game declares `config_schema` and `results_schema`; reporters deliberately do **not** have a parallel `output_schema`. Per D7, the D3 envelope schema is the only platform-level output validation, and per-artifact content shape is the author's responsibility. Future per-artifact schema declaration is left open and flexible (see §9 'Deferred ideas').
6. **Certification exercises the contract end-to-end.** `coworld certify` runs the game and players against the certification fixture. Whatever lifecycle reporters get should be exercised by certification too, not just declared.
7. **Reporters are pure functions of their inputs; determinism is preferred.** *(Decided 2026-05-18, D1.)* A reporter's only side effect must be writing to its declared output URI — no network calls beyond input/output URIs, no persistent state across runs, no behavior that depends on wall-clock time except via metadata explicitly supplied as input. Deterministic implementations (same input → byte-identical output) are strongly preferred for testability and reproducibility, but reporters with inherently non-deterministic logic (e.g. LLM-based analysis with sampling) are permitted as long as purity holds.
8. **Single trigger in v1: per-episode after artifacts land.** *(Decided 2026-05-18, D1.)* The runner invokes each declared reporter once per episode, after the game and player containers have exited and the game's results and replay artifacts have been written. Per-round and on-demand triggers are explicitly out of scope (see §3 items 6-7).
9. **Reporter input/output contract.** *(Decided 2026-05-18, D2; expanded 2026-05-19, D4.)* Each reporter invocation receives standard inputs via environment-variable URIs, mirroring the game contract. Standard inputs: results JSON (`COGAME_RESULTS_URI`), replay artifact (`COGAME_REPLAY_URI` — renamed from the game's `COGAME_SAVE_REPLAY_URI` for reporter-side clarity), optional logs (`COGAME_LOG_URI`, present iff the game's logging was enabled), platform-generated episode metadata JSON (`COGAME_EPISODE_METADATA_URI`; strawman shape in §7), the full coworld manifest (`COGAME_MANIFEST_URI`), and the reporter's own manifest id as a plain string (`COGAME_REPORTER_ID`, added by D4 to support the one-image-many-runnables pattern from spec 0043). Output: a single artifact written to `COGAME_REPORT_OUTPUT_URI` (URI is unique per `(episode_id, reporter_id)`; see D4). Reporters do not declare which inputs they want in v1 — the platform always sets all standard URIs and data transfer happens only when the reporter calls `read_data()`. Per-episode `tokens` are never exposed to reporters. Output envelope shape governed by D3 (item 10); per-artifact JSON Schema validation is shelved for v1 (D7).
10. **Output envelope contract.** *(Decided 2026-05-19, D3.)* Each reporter writes a single JSON envelope to `COGAME_REPORT_OUTPUT_URI`. Shape: `{ "version": "1", "artifacts": [ { "id", "content_type", ["encoding"], "content" }, ... ] }`. Per artifact: `id` unique within the envelope, `content_type` is an IANA media-type string, optional `encoding` defaults to native JSON embedding (must be `"base64"` for binary content types), `content` is JSON-native for text and JSON types (string for `text/*`, any JSON value for `application/json`) and a base64 string for binary. The `artifacts` array may be empty (signals "ran successfully, nothing to surface"); reporters must still write a valid envelope. First-class content types in v1: `text/markdown`, `text/plain`, `application/json`, `image/png` (base64). Other content types are permitted and stored opaquely. `text/html` is explicitly excluded from first-class rendering (XSS surface in Observatory). First artifact is the primary one by convention. No streaming; reporter buffers and writes once.
11. **Multi-reporter execution model.** *(Decided 2026-05-19, D4.)* When a coworld declares multiple reporters (`reporter: [r1, r2, ...]`), all of them run on every episode, in parallel, independently. Each reporter container receives its own `COGAME_REPORT_OUTPUT_URI` minted per `(episode_id, reporter_id)` and its own `COGAME_REPORTER_ID` env var carrying the manifest `id` of the runnable being invoked (needed when one image implements multiple reporter runnables per spec 0043). Reporters cannot read each other's outputs in v1 — no pipelining; pipeline-like work goes inside one reporter container. Failure of one reporter does not block or affect another (aggregate failure handling: D8). Each reporter is its own container with the same resource baseline as the game and player containers: 2 CPU + 2Gi memory (`GAME_RUNTIME_README.md:13-24`). Reporter `id`s must be unique within `reporter[]` (already enforced by the existing `_manifest_items_by_id` validation at `certifier.py:208-215`). Display order in logs and Observatory surfaces is the manifest declaration order; execution order is undefined. Zero reporters declared = the reporter step is a no-op.
12. **Certification exercises reporters end-to-end.** *(Decided 2026-05-19, D5.)* `coworld certify` invokes every declared reporter against the smoke episode's real artifacts after the existing certification flow runs (manifest validation, image reachability, smoke episode, results-schema validation, replay verification). The certifier synthesizes an episode metadata JSON (`episode_id: "ep_certify_<timestamp>"`, `variant_id: "certification"`, real timestamps from the smoke run, `players` derived from `manifest.certification.players[]` with `policy_version_id: null`, tournament fields all `null`, `tags: {"context": "certification"}`), mints a per-reporter `COGAME_REPORT_OUTPUT_URI` and `COGAME_REPORTER_ID`, then invokes reporters in parallel (D4) using the same launch infrastructure as the production runner. Each reporter must exit 0 within a per-reporter timeout (default 60s, matching the existing `certify_coworld` timeout) and write a valid envelope (D3). **Any reporter failing any check causes certification to fail** — intentional asymmetry with runtime, which tolerates flaky reporters (D4 isolates per-reporter failure). Per-artifact JSON Schema validation is shelved for v1 (D7); certification's structural hook is a no-op for v1. No automated purity/determinism check. No `--skip-reporters` flag in v1.
13. **Reporter execution location and CLI invocation.** *(Decided 2026-05-19, D6.)* Reporters run **co-located with the episode** inside the runner — in `runner/runner.py` they join the `coworld-local` Docker network alongside game and players; in `runner/kubernetes_runner.py` they are additional containers/pods within the same episode Job (exact K8s mechanism — sibling pods, separate Jobs, sidecars — is implementation detail, not part of the reporter contract). No separate dispatch system in v1. The reporter lifecycle fires whenever an episode completes with valid artifacts (game and players exited 0, results JSON validates against `game.results_schema`, replay artifact exists). Concrete CLI behavior: hosted production episodes → run reporters; `coworld run-episode` → run reporters; `coworld certify` → run reporters (per D5, strict failure handling); `coworld play` → run reporters *only* on natural episode completion (interrupts silently skip the reporter step); `coworld replay` and `COGAME_REPLAY_SERVER=1` replay mode → never run reporters (no new artifacts to consume). On episode failure or missing/invalid artifacts the reporter step is **skipped silently** — logged but not surfaced as error, since reporters can't operate on garbage and the episode result is the appropriate failure surface. No `--skip-reporters` flag in v1.
14. **Output schema declaration shelved for v1.** *(Decided 2026-05-19, D7.)* Reporter manifest entries do **not** declare output schemas in v1. `CoworldDeclaredRoleSpec` is unchanged. The D3 envelope schema is the only platform-level output validation; per-artifact content shape is the reporter author's responsibility. Reporter authors are **encouraged but not required** to validate their output internally (Pydantic, jsonschema, ad-hoc — whatever fits); platform does not enforce this. Certification (D5) validates envelope shape only; the structural hook for per-artifact validation exists but is a no-op in v1. Observatory renders artifacts by `content_type` alone. Future extension (e.g. an optional `artifacts: [...]` manifest field declaring per-artifact content types and schemas) is intentionally **left open and flexible** — design when concrete demand surfaces; do not anchor the future on today's strawman shape.
15. **Reporter failure semantics.** *(Decided 2026-05-19, D8.)* A reporter invocation is "failed" if any of: container fails to start (`start_failed`), exits non-zero (`nonzero_exit`), exceeds its per-reporter timeout (`timeout`, default 60s per D5), exits 0 but writes nothing (`missing_output`), or writes content that fails D3 envelope-schema validation (`invalid_envelope`). Otherwise it's "success" (including envelopes with empty `artifacts: []`). **Conditional retry: one retry on `timeout` only**, never on other failure modes; same inputs (D1 purity), freshly-minted `COGAME_REPORT_OUTPUT_URI`, no retry delay; applies uniformly to runtime and certification; no author-side opt-out in v1. The runner records a per-reporter status record for every invocation: on success the record carries the envelope; on failure it carries `failure_reason`, `failure_detail`, `exit_code` (when applicable), `duration_ms`, and captured stdout/stderr; when retries occurred a `previous_attempts: [...]` array preserves prior attempts. **Reporter status does not affect the runner's exit code** — episode success and reporter status are orthogonal dimensions. Status records land in the runner's workspace locally (under `reporter_outputs/<reporter_id>.*`) and in durable storage hosted (accessible via Observatory API per D9). Structured logs per outcome (info on success, warn on failure). No platform-injected failure envelopes — failed reporters yield status records, not synthetic envelopes. No partial-success salvage.
16. **Observatory API surface, frontend rendering, and CLI parity.** *(Decided 2026-05-19, D9.)* Reporter outputs are exposed via four new Observatory endpoints rooted at the episode: `GET /episodes/{id}/reports` (lightweight metadata-only list), `GET /episodes/{id}/reports/{reporter_id}` (full status record + envelope), `GET /episodes/{id}/reports/{reporter_id}/artifacts/{artifact_id}` (direct artifact access with proper `Content-Type` — server decodes base64 for binary content), and `GET /episodes/{id}/reports/{reporter_id}/logs` (captured stdout/stderr). Permissions and retention follow existing episode rules. Observatory's frontend renders first-class content types inline — Markdown (with artifact-id references rewritten to artifact-direct URLs at render time), plain text, JSON tree, PNG via `<img>` — and offers download-only for other content types. `text/html` is stored but never inline-rendered (per D3). Markdown artifact-id substitution lives in Observatory's renderer (not in the reporter) so reporters stay portable across deployment URLs. CLI parity in `packages/coworld/src/coworld/tournament_cli.py`: `coworld reports <episode-id> [--mine]`, `coworld report-show <episode-id> --reporter <reporter-id>`, `coworld report-download <episode-id> [--reporter ...] [--artifact ...] [--output ...]`. **No cross-episode aggregation, search, trends, webhooks, or pagination in v1.**
17. **Naming conventions ratified; canonical doc name fixed.** *(Decided 2026-05-19, D10.)* All reporter-side env vars use the `COGAME_` prefix (matching the game contract namespace) — `COGAME_RESULTS_URI`, `COGAME_REPLAY_URI`, `COGAME_LOG_URI`, `COGAME_EPISODE_METADATA_URI`, `COGAME_MANIFEST_URI`, `COGAME_REPORTER_ID`, `COGAME_REPORT_OUTPUT_URI`. The reporter-output env var carries the `OUTPUT` modifier to disambiguate write-destination from any future read-side report URI. Reporter `id` format in the manifest is a **recommendation** (lowercase with hyphens or underscores, matching existing player/variant id conventions) — only uniqueness within `reporter[]` is platform-enforced (per D4); no regex check. Canonical reporter-runtime contract document is **`REPORTER_RUNTIME_README.md`**, placed alongside `GAME_RUNTIME_README.md` in `packages/coworld/src/coworld/`. All other naming choices (envelope fields, failure codes, status record fields, API routes, CLI commands, workspace artifact paths) were settled in D2-D9 and are catalogued in D10 for reference.

---

## 6. Open questions

*All initial open questions resolved as of D10 (2026-05-19). See §8 for the full decisions log. New questions that surface during implementation or after v1 ships can be added here as they emerge — when a new question is filed, prefer the `§6.X 'Title'` reference format so cross-references survive future renumbering.*

---

## 7. v1 Contract reference

The concrete v1 contract shape. Every clause here is backed by a decision (D1–D10); see §8 for rationale. An implementer reading this section alongside the canonical (forthcoming) `REPORTER_RUNTIME_README.md` should have everything needed to ship.

A reporter is a process-style container declared in `coworld_manifest.json` under `reporter: [...]`. **Trigger:** per-episode, after the game and player containers have exited and the game's results and replay artifacts have been written (D1). **Purity:** each reporter is a pure function of its inputs — its only side effect is writing to its declared output URI; determinism is preferred but not required (D1). The runner starts each declared reporter with:

```bash
COGAME_RESULTS_URI=...           # R, always   — game results JSON (validates against game.results_schema)
COGAME_REPLAY_URI=...            # R, always   — game replay artifact (game-owned format)
COGAME_LOG_URI=...               # R, optional — episode logs (game + players); set iff game's COGAME_LOG_URI was set
COGAME_EPISODE_METADATA_URI=...  # R, always   — platform-generated JSON; strawman shape below
COGAME_MANIFEST_URI=...          # R, always   — the full coworld manifest JSON
COGAME_REPORTER_ID=...           # R, always   — this reporter's manifest id (D4)
COGAME_REPORT_OUTPUT_URI=...     # W, always   — where the reporter writes its JSON envelope; unique per (episode_id, reporter_id) (D3, D4)
```

Strawman shape of the episode metadata JSON at `COGAME_EPISODE_METADATA_URI`:

```jsonc
{
  "episode_id": "ep_...",
  "variant_id": "default",
  "started_at": "2026-05-18T10:23:45Z",
  "ended_at":   "2026-05-18T10:24:31Z",
  "duration_seconds": 46.2,
  "players": [
    {"slot": 0, "policy_version_id": "polver_...", "policy_name": "champion-v3"},
    {"slot": 1, "policy_version_id": "polver_...", "policy_name": "starter"}
  ],
  "league_id":   "league_...",   // null outside leagues (e.g. local certify / run-episode)
  "division_id": "div_...",      // null outside leagues
  "round_id":    "round_...",    // null outside tournament rounds
  "pool_id":     "pool_...",     // null outside tournament rounds
  "tags": { /* CoworldEpisodeJobSpec.episode_tags */ }
}
```

Per-episode `tokens` are explicitly excluded from anything a reporter sees.

Strawman shape of the reporter output envelope at `COGAME_REPORT_OUTPUT_URI` (D3):

```jsonc
{
  "version": "1",
  "artifacts": [
    {
      "id": "summary",
      "content_type": "text/markdown",
      "content": "# Episode Summary\n\nSlot 0 won by ..."
    },
    {
      "id": "stats",
      "content_type": "application/json",
      "content": { "scores": [42, 38], "ticks": 100, "winner_slot": 0 }
    },
    {
      "id": "heatmap",
      "content_type": "image/png",
      "encoding": "base64",
      "content": "iVBORw0KGgoAAAANS..."
    }
  ]
}
```

`artifacts` may be empty (`[]`) — that signals "ran, nothing to report" and is a valid envelope. First artifact is the primary one by convention. First-class content types in v1: `text/markdown`, `text/plain`, `application/json`, `image/png` (base64). `text/html` is excluded from first-class rendering.

The reporter:

1. Reads what it needs from the input URIs (using the same `runner/io.py` `read_data()` abstraction the game and runner already use).
2. Constructs a JSON envelope and writes it to `COGAME_REPORT_OUTPUT_URI` (D3).
3. Exits 0 on success.

The runner:

1. Runs all declared reporters in parallel **after the game and player containers exit successfully and the results/replay artifacts pass validation** (D4 + D6) — co-located in the same runner environment as the game and players. Each reporter container gets the standard env set, plus its own `COGAME_REPORTER_ID` and a unique `COGAME_REPORT_OUTPUT_URI` keyed on `(episode_id, reporter_id)`. Per-reporter resource baseline: 2 CPU + 2Gi memory. If episode validation fails or artifacts are missing, the reporter step is **skipped silently** — logged, not errored (D6).
2. Validates each reporter's output against the envelope schema (D3). Per-artifact JSON Schema validation is shelved for v1 (D7) — content shape inside artifacts is the author's responsibility.
3. Persists envelopes and surfaces their artifacts via `app_backend` per Observatory rendering rules (D9). Display order across multiple reporter outputs is the manifest declaration order.
4. Records per-reporter status for every invocation (D8): on success, the envelope; on failure, a status record with `failure_reason` (`start_failed` | `nonzero_exit` | `timeout` | `missing_output` | `invalid_envelope`), `failure_detail`, captured stdout/stderr, and a `previous_attempts` array if retries occurred. **One retry on `timeout` only** (D8). Reporter status does not affect the runner's exit code; episode success and reporter status are independent.

**CLI surface (D6):** The reporter lifecycle fires from hosted production episodes, `coworld run-episode`, `coworld play` (only on natural episode completion — interrupts silently skip), and `coworld certify`. It does **not** fire from `coworld replay` or `COGAME_REPLAY_SERVER=1` replay mode (no new artifacts to consume).

**Certification (D5):** `coworld certify` runs the same flow against the manifest's certification fixture, with two differences: (a) the episode metadata JSON is *synthesized* by the certifier with `variant_id: "certification"` and `tags: {"context": "certification"}`, since no real episode metadata exists; (b) failure handling is **strict** — any reporter exit non-zero or invalid envelope causes certification to fail, even though the runtime tolerates per-reporter failures (D4 vs. D5 asymmetry). Per-reporter timeout default: 60s.

---

## 8. Decisions log

Append-only record of decisions made and the reasoning. Date entries. Each decision gets a stable identifier (`D1`, `D2`, …) so it can be cited from elsewhere in the doc.

### D1 — v1 reporter cadence is per-episode; reporters are pure functions of their inputs

- **Date:** 2026-05-18
- **Resolves:** what was originally §6.1 "When does a reporter run?"

**Decision:**

1. v1 reporters run **per-episode only** — the runner invokes each declared reporter once per episode, after the game and player containers have exited and the game's results and replay artifacts have been written.
2. Each reporter must be a **pure function of its inputs**: its only permitted side effect is writing to its declared output URI. No external network calls beyond input/output URIs, no persistent state across runs, no behavior that depends on wall-clock time except via metadata explicitly passed as input.
3. **Determinism is strongly preferred** (same input → byte-identical output) but **not required**. Inherently non-deterministic reporters (e.g. LLM-based analysis with sampling) are permitted as long as purity holds.
4. Per-round triggers are **deferred** to a future version with its own design pass (see §3 item 6).
5. On-demand triggers are **shelved** (see §3 item 7) — with required purity and no user-controllable knobs, a "rerun" produces the same output as the original run. Revisit if a concrete use case emerges that justifies exposing knobs.

**Rationale:**

- The 80% case for reporters (episode summaries, derived stats, highlight extraction, results-to-Markdown formatting) is episode-scoped. Per-episode is where the value is concentrated.
- Per-round requires artifact plumbing that does not exist: the set of episodes in a round, the commissioner's round-display output, cross-episode aggregation conventions. Tackling that as part of v1 risks baking in assumptions about round context we don't yet understand.
- Purity decouples reporter behavior from execution context. It makes reporters testable, certification-friendly, safe to re-run, and trivially parallelizable.
- Determinism would be ideal but would exclude legitimate use cases (LLM-based reporters). Requiring it everywhere is more restrictive than the value justifies.
- On-demand reruns are not zero-value, but their value is mostly "use a newer reporter version on an old episode" — and that's better expressed as "rerun the certification flow against archived artifacts" than as a user-facing trigger with knobs.

**Consequences:**

- §2 goal 1, §3 items 6-7, §5 items 7-8, §7 working sketch updated to reflect this.
- A reporter MAY NOT: call external APIs not addressed by an input URI, write to anywhere outside its output URI, read environment variables not in its declared spec, depend on the host filesystem outside the input URIs.
- A reporter MAY: be slow, be non-deterministic, fail (failure semantics resolved by D8).
- Certification's relationship to purity is resolved by D5: no automated purity check; author discipline.
- Future per-round design must layer onto this contract without breaking it.

### D2 — Reporter input/output contract: standard inputs via env-supplied URIs

- **Date:** 2026-05-18
- **Resolves:** what was originally §6.2 (renumbered to §6.1 after D1) "What inputs does a reporter receive?"

**Decision:**

1. Every declared reporter receives the following on each per-episode invocation, all as environment-variable-supplied URIs resolvable via `runner/io.py`:

   | Variable | R/W | Always present? | Contents |
   | --- | --- | --- | --- |
   | `COGAME_RESULTS_URI` | R | Yes | The same URI the game wrote results JSON to. Validates against `game.results_schema`. |
   | `COGAME_REPLAY_URI` | R | Yes | The same artifact the game wrote (game env var was `COGAME_SAVE_REPLAY_URI`; renamed here for reporter-side clarity). Format is game-owned. |
   | `COGAME_LOG_URI` | R | Optional | Episode logs (game + players). Set iff the game was run with logging enabled. |
   | `COGAME_EPISODE_METADATA_URI` | R | Yes | Platform-generated JSON with `episode_id`, `variant_id`, `started_at`/`ended_at`/`duration_seconds`, `players` (slot → `policy_version_id` + `policy_name`), `league_id` / `division_id` / `round_id` / `pool_id` (nullable for non-tournament contexts), `tags`. **Excludes** per-episode `tokens`. Strawman shape in §7. |
   | `COGAME_MANIFEST_URI` | R | Yes | The full coworld manifest JSON. |
   | `COGAME_REPORT_OUTPUT_URI` | W | Yes | Where the reporter writes its single output artifact. |

2. **Env-supplied URIs only.** The platform does not interpolate URIs into the reporter's `run` argv. Reporter authors who want CLI-arg access wrap their own entrypoint.
3. **No opt-in declaration in v1.** Reporters do not declare which inputs they want; the platform always sets every standard env var. Data transfer happens only when the reporter calls `read_data()`, so unused inputs are essentially free.
4. **Episode metadata is its own JSON,** not a set of flat env vars. Lets the metadata structure evolve without expanding the env-var surface.
5. **Pass the full manifest,** not a pre-computed subset. Lets reporters dereference `variant_id`, read `results_schema`, and inspect the rest of the manifest if needed. (D7 subsequently shelved author-declared `output_schema`, so this benefit is now mostly about variant config and results-schema access.)
6. **Tokens are excluded** from everything a reporter sees. They are per-episode player↔game secrets and have no reporter use.

**Rationale:**

- Mirroring the game contract (env-supplied URIs, `runner/io.py` for all I/O) keeps the reporter contract simple and easy to learn for anyone already writing a coworld game or player.
- "Always set all URIs, transfer-on-read" is the simplest mental model and costs nothing for unread inputs.
- Manifest-side opt-in declarations are a real optimization but premature without a reporter actually paying a cost for unused inputs. Easy to add later as a non-breaking change (introduce an optional `inputs` field; default to "all standard").
- A standalone metadata JSON keeps env-var surface tight while letting metadata structure evolve.
- Renaming `COGAME_SAVE_REPLAY_URI` → `COGAME_REPLAY_URI` on the reporter side prevents authors from misreading the env var as a write destination.

**Consequences:**

- §5 item 9 added.
- §7 working sketch updated: env block reflects the renames and `COGAME_MANIFEST_URI`, plus the strawman metadata shape.
- §6.1 (input question) closed; §6.2-6.9 renumbered to §6.1-6.8.
- Per-reporter output isolation (separate output URIs when multiple reporters are declared) follows naturally — resolved by D4.
- Certification produces a synthetic episode metadata JSON during the smoke-test run (resolved by D5).

**Explicitly NOT decided (deferred):**

- Output format and content type — resolved by D3. Per-artifact JSON Schema validation shelved for v1 (D7); future extension intentionally left open.
- Whether games can expose custom intermediate artifacts to reporters. v1 answer: no — embed in `results.json` or in the replay.
- Whether episode metadata includes an Observatory deep-link URL. Defer until needed; hard to populate uniformly across hosted vs. local contexts.
- Per-input opt-in declarations. Revisit if a reporter pays a real cost for unused inputs.

### D3 — Reporter output is a single JSON envelope; content types declared per-artifact

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.3 (renumbered through D1/D2 to §6.1) "What does a reporter output?"

**Decision:**

1. Each reporter invocation writes **exactly one JSON envelope** to `COGAME_REPORT_OUTPUT_URI`. The envelope's shape is:

   ```jsonc
   {
     "version": "1",
     "artifacts": [
       { "id": "...", "content_type": "...", "encoding": "...", "content": ... }
     ]
   }
   ```

2. **Envelope fields:**
   - `version` (required, string): currently `"1"`. Forward-compat hook for envelope evolution.
   - `artifacts` (required, array, length ≥ 0): zero or more artifact records. Empty array is a valid envelope and signals "ran successfully, no output to surface."

3. **Per-artifact fields:**
   - `id` (required, string, unique within envelope): stable handle for cross-artifact references and Observatory display logic.
   - `content_type` (required, string): IANA media-type string.
   - `encoding` (optional, string): defaults to native JSON embedding. Must be `"base64"` for any binary content type.
   - `content` (required): type depends on `content_type` + `encoding`:
     - `text/markdown`, `text/plain` → JSON string.
     - `application/json` → any JSON value (object, array, primitive) — embedded natively, not stringified.
     - Binary content types (e.g. `image/png`) with `encoding: "base64"` → JSON string of base64-encoded bytes.

4. **First-class content types in v1** (platform commits to first-class rendering in Observatory):
   - `text/markdown`
   - `text/plain`
   - `application/json`
   - `image/png` (base64-encoded)

5. **Other content types are permitted** in the envelope but treated as opaque content. Stored and downloadable, not rendered inline. Promote individual types to first-class when concrete demand surfaces.

6. **`text/html` is explicitly excluded from first-class rendering.** Reporter-produced HTML in Observatory's domain is an XSS surface; sandboxed-iframe + CSP plumbing is out of scope for v1. Reporters wanting richness use Markdown.

7. **First artifact is the primary artifact by convention.** No separate `primary` flag.

8. **No streaming.** Reporter buffers in memory or a temp file and writes the entire envelope once via `runner/io.py` (`upload_data()` / `post_data()`).

9. **No formalized output size limit in v1.** Soft recommendation: keep envelopes under ~10MB. Base64 inflation (~33%) is a known cost for embedded binary; revisit if anyone hits practical issues.

10. **Reporters must always write a valid envelope before exit 0** (sharpens D1's "write to output URI" requirement). Empty `artifacts: []` is valid; missing or malformed envelope is a contract violation.

11. **Per-artifact JSON Schema validation** (against author-declared schemas) is **not part of D3**; subsequently resolved by D7 (shelved for v1; future extension intentionally left open).

**Rationale:**

- **Option C beats Option A on simplicity.** Option A (declared single content type per reporter manifest entry) would have required extending `CoworldDeclaredRoleSpec` in the metta repo with a new field and locked each reporter into one format per declaration. Option C requires zero manifest-schema changes and gives reporters per-invocation flexibility (one episode produces JSON stats, another produces a Markdown post-mortem) at the cost of wrapping output in two lines of JSON.
- **Multi-artifact comes for free under C.** Markdown summary + JSON stats + embedded heatmap PNG can all live in one envelope. Under A, multi-artifact would have been a deliberate future extension with a new manifest schema.
- **Native JSON embedding for `application/json` content** is more ergonomic than mandating stringified JSON: reporter authors include their dict/object directly. The polymorphic `content` type is unusual but trivially schema-validatable as a discriminated union keyed on `content_type`.
- **Base64 PNG is acceptable.** Compared to the alternative (multi-blob output convention with sibling files), base64 inside the envelope is simpler and uniform. The ~33% size inflation is acceptable for v1 expected sizes.
- **HTML exclusion is non-negotiable for v1.** Until Observatory has sandboxed-iframe + CSP infrastructure, accepting reporter-produced HTML for inline rendering is a vulnerability.

**Consequences:**

- §5 item 10 added.
- §5 item 9's tail sentence updated to reference D3 + §6.4 instead of the now-closed output question.
- §7 working sketch: env block annotation updated; envelope strawman added; reporter and runner behavior bullets updated to reflect the envelope.
- §6.1 (output question) closed; §6.2-6.8 renumbered to §6.1-6.7.
- The platform now owns one new schema: the reporter envelope schema (likely lives in `packages/coworld/src/coworld/reporter_envelope_schema.json` or as a Pydantic model in `types.py` when implementation lands in metta).
- The runner gains an envelope-validation step after each reporter exits.
- Observatory will need rendering support for the first-class content types — separate work item, tracked under D9.
- **No changes to the manifest schema required for v1.** The `reporter` section stays `list[CoworldDeclaredRoleSpec]` exactly as it is today.

**Explicitly NOT decided (deferred):**

- Per-artifact JSON Schema validation — shelved for v1 (D7); future extension intentionally left open and flexible.
- Whether `application/json` artifacts declare nested schemas inline in the envelope vs. by reference from the manifest. Both remain possible if/when D7's deferred extension is designed.
- Inter-artifact reference resolution in rendered Markdown — e.g. `![heatmap](heatmap)` substituting to the embedded PNG. The envelope enables this; the rendering machinery is governed by D9 (Observatory does the substitution to artifact-direct URLs at render time).
- Promotion of additional content types (SVG, CSV, etc.) to first-class. Add when demand is concrete.
- Output size limits beyond the soft ~10MB recommendation.
- When to advance the envelope to `"version": "2"`. v1 freezes at `"1"`.

### D4 — Multiple reporters: all run, in parallel, independent; `COGAME_REPORTER_ID` added

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.4 (renumbered through D1/D2/D3 to §6.1) "Multiple reporters per coworld"

**Decision:**

When a coworld declares more than one reporter, the v1 contract is:

1. **All declared reporters run on every episode.** No conditional invocation in v1. A reporter that wants to be conditional emits an empty `artifacts: []` envelope (per D3).
2. **Parallel execution.** D1 purity + D2 independent inputs + D3 independent outputs compose to mean there is no correctness dependency between reporters, so the runner invokes them concurrently. No formal concurrency cap.
3. **Independent — no pipelining in v1.** Reporters cannot consume each other's outputs. Pipeline-style work goes inside one reporter container.
4. **Output isolation.** Each reporter receives a unique `COGAME_REPORT_OUTPUT_URI` minted per `(episode_id, reporter_id)`. Reporters cannot infer or access each other's output URIs.
5. **New env var: `COGAME_REPORTER_ID`** (plain string, not a URI). Each reporter receives its own manifest `id`. Needed for the spec-0043 pattern where one image implements multiple runnables and the running process distinguishes "which reporter am I?" via this env var.
6. **Failure isolation.** A failure in reporter A does not prevent reporter B from running or affect its output. Aggregate failure handling — whether *any* reporter failure poisons the episode, whether the runner exits non-zero — is firmed up by D8 (per-reporter status records; runner exit code reflects episode success only).
7. **Resource allocation: 2 CPU + 2Gi memory per reporter container.** Matches `GAME_RUNTIME_README.md:13-24` baseline for game/player/replay. Per-reporter overrides in the manifest are deferred.
8. **Manifest validation: reporter `id`s must be unique within `reporter[]`.** Already enforced by the existing `_manifest_items_by_id` validation at `certifier.py:208-215` (which is generic across all role sections). No new code needed.
9. **Display order: manifest declaration order.** When logs or Observatory surface multiple reporter outputs, they appear in the order declared in the manifest. Execution order remains undefined (parallel).
10. **Zero reporters declared = the reporter step is a no-op.**

**Rationale:**

- Purity (D1), independent inputs (D2), and independent outputs (D3) compose into a contract where parallel-independent execution is the obvious default — there are no constraints to violate.
- Conditional invocation (only-run-for-variant-X, only-on-tier-Y) is expressible inside reporters via empty-envelope output (D3 makes `artifacts: []` valid). Pushing condition logic down into the manifest would add schema complexity for unclear benefit.
- Pipelining (B reads A's output) would add: dependency declarations, topological scheduling, cross-reporter failure semantics. The alternative — wrap both stages in one reporter — is operationally fine for the foreseeable use cases.
- `COGAME_REPORTER_ID` is a small expansion to D2's env set but unlocks the spec-0043 shared-image pattern, which is a real Softmax-recommended structure (the spec literally uses `paintarena-runtime` providing game + player + reporter via different `run` argv).
- Same resource baseline as game/player keeps the mental model consistent. If reporters turn out to be heavier (LLM-based, replay rendering) or lighter (text-only), per-reporter overrides are a non-breaking manifest extension we can add later.

**Consequences:**

- §5 item 9 amended to include `COGAME_REPORTER_ID` in the standard input set and note the per-`(episode_id, reporter_id)` output URI uniqueness.
- §5 item 11 added.
- §7 working sketch env block gains `COGAME_REPORTER_ID`; reporter and runner behavior bullets updated for parallel multi-reporter execution and per-reporter resource baseline.
- §6.1 (multi-reporter question) closed; §6.2-§6.7 renumbered to §6.1-§6.6.
- Stale `§6.X` cross-references in D2 and D3 cleaned up to reflect post-D4 numbering, with stable section titles appended so future renumbers don't break the references.
- Going forward, cross-references to open questions use the `§6.X 'Title'` format so they remain readable even if numbers shift.
- Runner implementation (in metta) must mint per-reporter output URIs keyed on `(episode_id, reporter_id)`, set `COGAME_REPORTER_ID` per container, and launch reporter containers/pods with the 2 CPU + 2Gi resource request.

**Explicitly NOT decided (deferred):**

- Per-reporter resource overrides in the manifest (e.g. a `resources: { cpu, memory }` field). Add when a real reporter needs different allocation; non-breaking extension.
- Concurrency cap on reporter parallelism. Add a cap if some coworld declares enough reporters to overwhelm the runner host or pod.
- Conditional invocation in the manifest (run-only-for-variant, run-only-on-tier-X, etc.). Empty-envelope output (D3) handles this case for now.
- Pipelining / dependencies between reporters. Open if a real chained use case appears.
- Whether reporters run during `coworld play` (interactive local play) — resolved by D6: yes, but only on natural episode completion; interrupts silently skip the reporter step. The `coworld certify` half was resolved by D5. The broader "which CLI commands fire the reporter lifecycle?" question is now fully resolved by D6. D4 committed only to "whenever the reporter lifecycle hook fires, all declared reporters fire."

### D5 — Certification exercises every declared reporter end-to-end

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.5 (renumbered through D1/D2/D3/D4 to §6.1) "Certification behavior"

**Decision:**

`coworld certify` (`packages/coworld/src/coworld/certifier.py`) is extended to actually invoke every declared reporter against the smoke episode's real artifacts, not just verify the reporter images are pullable.

1. **The existing certification flow is preserved.** Manifest parse + schema validation (`load_coworld_package`), image reachability for every declared role (`validate_image_references`), the smoke episode with the `manifest.certification` fixture, results-schema validation, and replay-artifact verification all run unchanged.
2. **After the smoke episode finishes, the certifier synthesizes an episode metadata JSON.** Concrete shape:

   ```jsonc
   {
     "episode_id": "ep_certify_<timestamp>",
     "variant_id": "certification",
     "started_at": "<smoke episode real start>",
     "ended_at":   "<smoke episode real end>",
     "duration_seconds": <real>,
     "players": [
       { "slot": 0, "policy_version_id": null, "policy_name": "<player_id from manifest.certification.players[0]>" }
       /* ... one per slot ... */
     ],
     "league_id": null,
     "division_id": null,
     "round_id": null,
     "pool_id": null,
     "tags": { "context": "certification" }
   }
   ```

   `variant_id: "certification"` is a marker — the manifest's `certification` fixture is not a named variant. `tags.context == "certification"` is the documented way for a reporter to detect smoke-test context if it wants to behave differently (e.g. skip expensive work).

3. **For each declared reporter, the certifier mints `COGAME_REPORTER_ID` and a unique `COGAME_REPORT_OUTPUT_URI`** keyed on `(synthetic episode_id, reporter_id)`, then invokes the reporter with the full D2 input set pointing at the smoke episode's real artifacts. Reporters run in parallel (D4) using the same launch infrastructure as the production runner.
4. **Each reporter must exit 0 within a per-reporter timeout (default 60s)** — matching `certify_coworld`'s existing `timeout_seconds=60.0` — **and must write a valid envelope** (D3 envelope-schema validation).
5. **Any reporter failing any check causes certification to fail.** This is **intentional asymmetry** with the runtime contract: D4 makes per-reporter runtime failures isolated and non-fatal, but certification is gating publication, so a failure here blocks the coworld from being certified.
6. **Resource allocation during certification matches D4 production:** 2 CPU + 2Gi memory per reporter container.
7. **Per-artifact JSON Schema validation is hooked through but its policy is governed by D7.** D5 firms up the *call sites*; D7 subsequently shelved the policy for v1, so the hook is a no-op until the deferred extension lands.
8. **No automated purity/determinism check in v1.** D1's purity requirement is enforced by author discipline; trying to verify it (run-twice-and-compare) collides with D1's "determinism preferred but not required."
9. **No `--skip-reporters` certification flag in v1.** Certification stays uniform. Add later if iteration speed becomes a real friction.
10. **Zero declared reporters = the reporter step in certification is a no-op,** same as the D4 runtime behavior.

**Rationale:**

- "Image is pullable" is a very weak guarantee. It misses bad entrypoints, missing dependencies, runtime crashes, malformed envelopes, and bogus content types — all real packaging failure modes that should never reach production.
- The existing certification pattern is end-to-end validation for the game and players. Reporters should match.
- The runtime/certification asymmetry on failure semantics (runtime tolerant, certify strict) is appropriate to the different stakes: a failure at runtime should not nuke a finished episode, but a failure at certify time should block publication. Different audiences, different cost-of-error.
- Per-artifact schema validation is a meaningful extension but properly belongs in its own decision; D5 firms up the call sites and D7 subsequently shelved the policy itself.
- Automating purity verification is hard and probably not worth it. Documentation + code review do the job.

**Consequences:**

- §5 item 12 added.
- §7 working sketch's closing certification paragraph expanded to reflect D5 (synthetic metadata, strict failure handling, per-reporter timeout).
- §6.1 (certification question) closed; §6.2-§6.6 renumbered to §6.1-§6.5.
- Stale `§6.X` cross-references in earlier entries swept and updated.
- Implementation work in metta: `certifier.py` gains a reporter-invocation step after `load_results()`; needs a synthetic-metadata builder; runs reporters with the same launch infra as `runner/runner.py`. The certifier's `CertificationResult` dataclass likely grows a `reporter_outputs: dict[str, JsonObject]` field so callers can inspect what each reporter produced during certify.
- The synthetic-metadata strawman in this decision becomes the *concrete contract* for what reporters see during certification — reporter authors can rely on `tags.context == "certification"` to detect smoke-test context.

**Explicitly NOT decided (deferred):**

- Per-reporter timeout override in the manifest (e.g. a `timeout_seconds` field per reporter declaration). Default 60s for now; add a manifest field when a reporter needs longer.
- `--skip-reporters` certification flag for fast iteration.
- Performance / SLA checks during certification (any reporter that exits 0 within timeout passes regardless of how close it got to the timeout).
- Whether `coworld run-episode` and `coworld play` also invoke reporters — resolved by D6 (yes for `run-episode`; yes for `play` only on natural completion). D5 committed only to the certification half.

### D6 — Reporter execution location and CLI invocation

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.6 (renumbered through D1/D2/D3/D4/D5 to §6.1) "Where does the reporter run?"

**Decision:**

This question had two intertwined halves: where do reporter containers physically execute, and which CLI commands fire the reporter lifecycle. D6 settles both.

**Part 1 — Physical execution location.** Reporters run **co-located with the episode** inside the runner:

1. In local Docker (`packages/coworld/src/coworld/runner/runner.py`), reporter containers join the `coworld-local` Docker network alongside game and player containers. The runner starts them after game and player containers exit successfully.
2. In hosted K8s (`runner/kubernetes_runner.py`), reporters are additional containers/pods within the same episode Job. The exact mechanism — sibling pods, separate Jobs triggered by the runner, sidecars — is implementation detail and **not part of the reporter contract**. Reporters see only env URIs.
3. **No separate dispatch system in v1.** Episode-runner ownership is sufficient given D1-D4 (per-episode, pure, env-supplied I/O, parallel per-episode). Separate dispatch is deferred until concrete need (on-demand reruns — shelved per D1; cross-episode reporters — deferred per D4).

**Part 2 — Which CLI commands fire the reporter lifecycle.** Unifying rule: **reporters fire wherever an episode completes with valid artifacts.**

| Command | Reporters fire? | Notes |
| --- | --- | --- |
| Hosted production episodes (league rounds) | **Yes** | Primary use case. D4 failure semantics: per-reporter isolated, non-fatal. |
| `coworld run-episode` (local Docker) | **Yes** | Local mirrors hosted. Same D4 failure semantics. |
| `coworld certify` | **Yes** (D5) | Strict failure: any reporter failure blocks certification. |
| `coworld play` (local interactive) | **Yes**, *iff* the episode completes naturally with all artifacts written | User-interrupt or incomplete artifacts → silently skip the reporter step. |
| `coworld replay` (viewing existing replays) | **No** | Not an episode; nothing to consume. |
| Hosted replay-server mode (`COGAME_REPLAY_SERVER=1`) | **No** | Same — replay mode produces no new artifacts. |

**The episode-completion gate.** The runner runs reporters only after:
- Game and player containers exited successfully.
- Results JSON exists at `COGAME_RESULTS_URI` and validates against `game.results_schema`.
- Replay artifact exists at `COGAME_SAVE_REPLAY_URI`.

If any of these fail, the reporter step is **skipped silently** — logged at info-level but not surfaced as an error. A reporter cannot do its job on missing/invalid inputs; the appropriate failure surface is the episode result itself, not a noisy reporter-step error.

**Sub-decisions:**

1. **Reporter step is owned by the runner** in both local and hosted modes — not a separate dispatch component.
2. **Order matters**: validate results/replay first, *then* invoke reporters. Reporters never see invalid artifacts.
3. **Silent skip on episode failure** (info-level log, not error).
4. **No `--skip-reporters` flag** in any CLI command in v1. Consistent with D5.
5. **K8s mechanism is implementation detail.** Sibling pods within the episode Job, separate Jobs triggered by the runner, or sidecar containers — all are valid implementation choices. The reporter sees only env URIs.

**Rationale:**

- Co-location reuses existing runner infrastructure; separate dispatch would require a new queue, worker pool, and artifact-ready signaling — disproportionate v1 cost for benefits we've explicitly deferred (on-demand reruns shelved per D1; cross-episode pending per D4).
- "Episode completes with valid artifacts" is the natural gate: it's already what the runner validates today, it precludes reporters seeing garbage, and it matches user expectations (interrupt = "I don't care about the output").
- `coworld play` running reporters on natural completion mirrors `coworld run-episode` and avoids inventing a "play mode skips reporters" exception. Authors using `play` for a final pre-publish sanity check benefit from reporters firing; iterators just Ctrl-C and skip the cost.
- Reverting to separate dispatch later is a non-breaking change for reporter authors: they still get env URIs and write envelopes; only the physical execution shifts.
- Silent skip on episode failure prevents noise. The episode failure itself is the loud signal; piling a "and reporters didn't run" error on top adds nothing.

**Consequences:**

- §5 item 13 added.
- §7 working sketch: runner behavior bullet 1 amended to include the episode-completion gate and the silent-skip-on-failure rule; new "CLI surface (D6)" paragraph added alongside the certification paragraph.
- §6.1 (where-does-it-run question) closed; §6.2-§6.5 renumbered to §6.1-§6.4.
- Stale `§6.X` cross-refs in D4 and D5 deferred-items swept and updated to mark D6 resolution.
- Implementation work in metta: both runner variants gain a "post-episode reporter step" gated on results-schema validation success and replay-artifact existence. K8s mechanism choice (sibling pods vs separate Jobs) is a deliberate implementation decision for the work to make. The runner is responsible for the silent-skip behavior on episode failure.

**Explicitly NOT decided (deferred):**

- Separate dispatch system for asynchronous / on-demand reporter execution. Revisit if D1's on-demand decision is reopened or D4's per-round design pass requires cross-episode reporters.
- The exact K8s mechanism (sibling pods, separate Jobs, sidecars). Implementation picks the best fit; the contract doesn't pin it.
- `--skip-reporters` flag for any local commands.
- Whether reporters can be manually triggered against archived artifacts (a kind of on-demand). Shelved per D1.

### D7 — Output schema declaration shelved for v1

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.7 (renumbered through D1/D2/D3/D4/D5/D6 to §6.1) "Output schema declaration"

**Decision:**

**No `output_schema` or per-artifact schema declaration field on reporter manifest entries in v1.** Concretely:

1. `CoworldDeclaredRoleSpec` in `packages/coworld/src/coworld/types.py` stays unchanged for reporters.
2. The D3 envelope schema is the only platform-level output validation. Per-artifact content shape is the reporter author's responsibility.
3. Certification (D5) validates envelope shape but not artifact content. The structural "hook" D5 mentioned for per-artifact schema validation is a no-op in v1.
4. **Reporter authors are encouraged (not required) to validate their output internally.** Pydantic, jsonschema, ad-hoc checks — whatever fits. The platform does not enforce this; the recommendation lives in reporter documentation (eventually `REPORTER_RUNTIME_README.md` when it lands in metta).
5. Observatory renders artifacts using `content_type` alone in v1. Typed rendering ("this is a stats object, draw a chart") is a future Observatory feature, not a v1 reporter-contract concern.
6. Reporters that want to document their output shape do so in their own README, sidecar docs, or source comments — not in the manifest.
7. **The future extension is intentionally left open and flexible.** Per-artifact schema declaration is a natural future extension (a plausible shape is an optional `artifacts: [...]` field on reporter manifest entries with `{id, content_type, schema?, required?}` per artifact, but this is a *sketch*, not a commitment). When concrete demand surfaces, design from scratch with the use cases that exist at the time — do not anchor on today's strawman.

**Rationale:**

- D3's envelope schema catches the most common author bugs (malformed envelope, missing content type, wrong artifact structure). The marginal value of per-artifact content validation in v1 is low.
- Static manifest schemas pull against D3's per-invocation flexibility (reporters can emit different artifact sets in different situations, success vs. error). Even partial declarations re-introduce rigidity D3 was designed to avoid.
- Reporter authors who want type-safety can implement it inside their reporter at trivial cost. The platform doesn't need to mediate.
- Downstream consumers can do their own typed parsing if they care. Most v1 consumers will be Observatory renderers using content_type.
- Manifest stays unchanged — consistent with D3's "no manifest-schema changes for v1" stance.
- Adding schemas later is a non-breaking change: an optional field defaulting to "no validation."

**Consequences:**

- §5 item 14 added.
- §5 items 9, 12 and §7 runner bullet 2 updated: previous "per-artifact JSON Schema validation remains open" forward-references replaced with "shelved for v1 per D7."
- §6.1 (output schema declaration question) closed; §6.2-§6.4 renumbered to §6.1-§6.3.
- Stale `§6.X` cross-references in D2, D3 swept and updated.
- Implementation work in metta: no manifest-schema change. Certifier's envelope-validation step is unchanged from D5; the structural per-artifact hook does not invoke schemas in v1.
- The "encouraged-but-not-required" stance on internal validation should be reflected in eventual reporter-author documentation (`REPORTER_RUNTIME_README.md` when it lands).

**Explicitly NOT decided (deferred, deliberately open):**

- Per-artifact JSON Schema declaration in the manifest. Shape is intentionally left open and flexible — when this lands, design from the use cases that exist at the time.
- Whether reporters should be required (vs. encouraged) to validate internally. v1 picks encouraged; revisit if author non-compliance becomes a real problem.
- Whether Observatory eventually does typed rendering of JSON artifacts. That's an Observatory design problem, not a reporter-contract one.

### D8 — Reporter failure semantics: 5-code taxonomy, conditional retry on timeout, status records

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.8 (renumbered through D1-D7 to §6.1) "Failure semantics"

**Decision:**

**Failure classification (5 codes):**

A reporter invocation is "failed" if any of the following:

| Condition | `failure_reason` code |
| --- | --- |
| Container fails to start (image pull error, bad `run` argv) | `start_failed` |
| Container exits non-zero | `nonzero_exit` |
| Container exceeds per-reporter timeout (60s default per D5) | `timeout` |
| Container exits 0 but the output URI has no content | `missing_output` |
| Output URI has content but fails D3 envelope-schema validation | `invalid_envelope` |

Otherwise = success. Exit 0 + valid envelope (including empty `artifacts: []`) = success.

**Conditional retry: timeout only.**

1. On `timeout` failure_reason, the runner retries the reporter **once** (up to 2 total attempts).
2. No retries for any other failure_reason — they fail immediately.
3. The retry uses the same inputs (D1 purity makes this safe) but a freshly-minted `COGAME_REPORT_OUTPUT_URI` (prevents partial envelope from the first attempt confusing the second).
4. No retry delay — the runner kicks off the second attempt immediately.
5. **Applies uniformly to runtime and certification.** A reporter that times out once but succeeds on retry passes both. Certification stays "strict" in the sense that *final* failure still blocks publication; it's just not stricter on the retry policy itself.
6. No author-side opt-out in v1. If retries become problematic (chronic flakiness doubling certification time), revisit.

**Status records.**

The runner produces one status record per reporter invocation:

```jsonc
{
  "reporter_id": "paintarena-summary",
  "status": "success" | "failure",
  "duration_ms": 1234,

  // when status == "success":
  "envelope": { /* D3 envelope */ },

  // when status == "failure":
  "failure_reason": "start_failed" | "nonzero_exit" | "timeout" | "missing_output" | "invalid_envelope",
  "failure_detail": "Exceeded 60s timeout",
  "exit_code": 1 | null,

  // present only when retries occurred:
  "previous_attempts": [
    { "failure_reason": "timeout", "failure_detail": "...", "duration_ms": 60000, "exit_code": null }
  ]
}
```

Container stdout/stderr are captured for every attempt (success or failure of the final attempt; logs of all attempts are kept).

**Runner exit code orthogonality.** The runner exits 0 if the episode itself succeeded (game + players + valid artifacts), regardless of reporter outcomes. Hosted scheduling and league rankings see episode success and reporter status as independent dimensions; consumers that care about reporter status query the status records.

**Storage:**

- **Local Docker**: status record + envelope + logs land in the runner's workspace under a `reporter_outputs/<reporter_id>.*` naming convention. Exact filenames are implementation detail.
- **Hosted K8s**: status records + envelopes + logs are uploaded to durable storage and exposed via Observatory API (per D9).

**Structured logging:** one structured log line per reporter outcome — info on success, warn on failure with the `failure_reason` and `failure_detail`. Independent of the persisted status record.

**No platform-injected failure envelopes.** Failed reporters yield status records, not synthetic envelopes masquerading as reporter output. Keeps the platform-output / reporter-output line clean.

**No partial-success salvage.** A reporter that writes some artifacts then crashes is `missing_output` or `invalid_envelope` depending on what landed. No attempt to recover partial state.

**Rationale:**

- The five-code taxonomy covers the failure modes the runner can actually detect distinctly today. Finer codes (e.g. `oom_killed`, `network_unreachable`) can be added later if they become consistently distinguishable.
- Retry-on-timeout-only matches the actual failure-mode pattern: timeouts often reflect transient externalities (LLM API slowness, network blip) while other failure modes typically reflect a real bug that retry won't fix. Retrying everything would mask real bugs; retrying nothing means transient flakiness blocks ops.
- A single retry (not N) is the right v1 default: enough to catch a flap, not enough to mask chronic problems. Easy to widen later if needed.
- Uniform retry policy across runtime and certification keeps the mental model simple. Certification stays strict in the sense that any final failure blocks publication; it doesn't need a stricter retry policy on top of that.
- Status records (not just logs) make reporter outcomes queryable in Observatory without log parsing. Logs are still emitted for real-time debugging.
- Runner exit-code orthogonality preserves existing hosted scheduling and league-ranking semantics, which only care about episode success.

**Consequences:**

- §5 item 15 added.
- §7 working sketch bullet 4 firmed up — was the last remaining "working hypothesis" line.
- §6.1 (failure semantics question) closed; §6.2-§6.3 renumbered to §6.1-§6.2.
- Stale `§6.X` cross-refs in §5 item 11 and D4 swept to use D8 directly.
- Implementation work in metta: both runner variants gain per-reporter status-record collection, retry-on-timeout logic, log capture for failed reporters, and (hosted) durable upload paths. The K8s runner's retry pattern is "delete and relaunch the failed container with a freshly-minted output URI." `EpisodeArtifacts` workspace structure gains a `reporter_outputs/` subdirectory.

**Explicitly NOT decided (deferred):**

- Per-reporter retry-policy overrides in the manifest (e.g. `retries: { on_timeout: 3, on_nonzero: 1 }`). v1 is default-and-uniform.
- Author-side opt-out from the timeout retry. Add when retries cause real friction.
- Additional `failure_reason` codes (e.g. `oom_killed`, `network_unreachable`) when they become consistently distinguishable.
- Per-reporter timeout overrides in the manifest. (Already deferred in D4/D5.)
- Whether the runner should emit metrics (Datadog/etc.) on reporter failure. Implementation detail; worth doing eventually.

### D9 — Observatory API surface, frontend rendering, and CLI parity

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.9 (renumbered through D1-D8 to §6.1) "Discovery and access from Observatory"

**Decision:**

**Observatory API endpoints (added to `app_backend`):**

Four new routes, all rooted at `/episodes/{episode_id}/reports`:

| Method + Path | Purpose | Response |
| --- | --- | --- |
| `GET /episodes/{episode_id}/reports` | List reporter outcomes for the episode | `{episode_id, reporters: [{reporter_id, status, duration_ms, artifact_count?, primary_artifact?, failure_reason?, has_previous_attempts}, ...]}` — lightweight metadata only, no envelope content |
| `GET /episodes/{episode_id}/reports/{reporter_id}` | Full status record + envelope for one reporter | The D8 status record verbatim (envelope inlined on success) |
| `GET /episodes/{episode_id}/reports/{reporter_id}/artifacts/{artifact_id}` | Direct artifact access with proper `Content-Type` (server decodes base64 for binary content types) | Raw artifact bytes |
| `GET /episodes/{episode_id}/reports/{reporter_id}/logs` | Captured stdout/stderr from all attempts | `text/plain` or `application/zip` for multi-attempt |

The list endpoint is **metadata-only** to keep responses fast when envelopes are large. The detail endpoint returns the full envelope inline. The **artifact-direct route** is load-bearing for inter-artifact references in rendered Markdown.

**Observatory frontend behavior.**

Episode page gains a **"Reports"** section listing declared reporters with status indicators (✓/✗). Per reporter:

- **Success**: primary artifact (first in the envelope per D3 convention) rendered inline; remaining artifacts shown as tabs or stacked below.
- **Failure**: `failure_reason` + `failure_detail` displayed, with a "View logs" link to the logs endpoint.

Rendering per first-class content type:

| `content_type` | Rendering |
| --- | --- |
| `text/markdown` | Rendered Markdown. Image/link references whose target is an artifact id are rewritten to the artifact-direct URL at render time. |
| `text/plain` | Preformatted text block. |
| `application/json` | Collapsible JSON tree. |
| `image/png` | `<img>` tag pointing at the artifact-direct URL. |
| Other | Download link only (per D3: opaque content). |

`text/html` is excluded from inline rendering (per D3) — stored and downloadable, never displayed inside Observatory's domain.

**CLI parity** (in `packages/coworld/src/coworld/tournament_cli.py`):

- `coworld reports <episode-id> [--mine]` — list reporter outcomes for an episode.
- `coworld report-show <episode-id> --reporter <reporter-id>` — print the full status record + envelope as JSON.
- `coworld report-download <episode-id> [--reporter <reporter-id>] [--artifact <artifact-id>] [--output <path>]` — download the envelope or a specific artifact in its native content type.

Pattern matches existing tournament-inspection commands (`coworld episode-results`, `coworld episode-logs`, `coworld replays`).

**Sub-decisions:**

1. **Episode-level access only in v1.** No cross-episode aggregation routes.
2. **Permissions and retention follow existing episode rules.** No reporter-specific access control or retention policy.
3. **No pagination on the list endpoint in v1.** Reporter counts per coworld are small.
4. **Markdown artifact-id substitution is Observatory's responsibility** (not the reporter's). Reporter authors write portable references like `![heatmap](heatmap)`; Observatory rewrites at render time. Pushing the substitution into reporters would couple them to specific Observatory deployment URLs.
5. **No webhooks / notifications** on reporter outcomes in v1. Pull-only API surface.
6. **Failed reporters' logs are accessible** via the logs endpoint regardless of `failure_reason`. Successful reporters' logs are also captured (existing runner convention) and accessible via the same endpoint.

**Rationale:**

- Four endpoints decompose cleanly: list for browsing, detail for full payload, artifact-direct for individual content with proper Content-Type, logs for debugging. Each has one purpose; none does too much.
- Artifact-direct routes (with server-side base64 decode + correct Content-Type) enable rich browser rendering — `<img src="…/artifacts/heatmap">` just works — without exposing the envelope JSON in image src URLs.
- Markdown artifact-id substitution belongs in Observatory because it depends on the host's URL structure. Pushing it into reporters would couple them to specific deployment URLs and break portability across production/staging/local.
- Deferring cross-episode aggregation, trends, and webhooks keeps v1 scope bounded. Each of those is a real feature with its own design considerations; better to ship the episode-level surface and add aggregation as concrete use cases emerge.
- CLI parity with the existing tournament-inspection pattern avoids surprise — anyone already using `coworld episode-results` will know where to look.

**Consequences:**

- §5 item 16 added.
- §7 working sketch bullet 3 updated to reference D9 directly.
- §6.1 (Observatory discovery question) closed; §6.2 renumbered to §6.1.
- Stale `§6.X` cross-refs in D3 consequences and deferred items, §5 item 15 (D8), and §7 swept to point at D9.
- Implementation work in metta `app_backend`: four new FastAPI routes, new database tables (or columns on existing `episodes` table) for reporter status records, base64-decoding artifact-direct route, log storage and serving. `app_backend/CLAUDE.md` and Alembic migrations are where this lands.
- Implementation work in `web/observatory` frontend: new "Reports" panel on the episode view, per-content-type renderers, Markdown artifact-id rewriting at render time.
- Implementation work in `coworld` CLI: three new commands in `tournament_cli.py` paralleling existing tournament-inspection patterns; new client model classes in `api_client.py` for the new endpoint responses.

**Explicitly NOT decided (deferred):**

- Cross-episode aggregation endpoints (`GET /leagues/{id}/reports?reporter_id=...`, `GET /divisions/{id}/reports?...`).
- Trend / time-series visualizations of `application/json` artifacts.
- Reporter-output embedding in non-Observatory surfaces (softmax.com landing pages, etc.).
- Webhooks / notifications on reporter outcomes.
- Diff / comparison views across episodes.
- API pagination for the list endpoint.
- Reporter-output search.

### D10 — Naming conventions ratified; canonical doc name fixed

- **Date:** 2026-05-19
- **Resolves:** what was originally §6.10 (renumbered through D1-D9 to §6.1) "Naming"

**Decision:**

D10 ratifies naming choices that were settled implicitly across D2-D9 and resolves the two pieces still open: the canonical doc name and the manifest reporter-id format.

**New decisions:**

1. **Canonical reporter-runtime contract document: `REPORTER_RUNTIME_README.md`**, placed alongside `GAME_RUNTIME_README.md` in `packages/coworld/src/coworld/`. Symmetrical with the existing game doc; discoverable in the same directory.

2. **Reporter `id` format in the manifest: recommendation, not constraint.**
   - Recommended convention: lowercase with hyphens or underscores (matching existing player and variant id conventions in the metta repo — e.g., `sweep-painter`, `default`).
   - Platform-enforced: **uniqueness** within `reporter[]` only (already enforced by `_manifest_items_by_id` per D4).
   - No regex check, no manifest-schema pattern. The recommendation lives in `REPORTER_RUNTIME_README.md`.

**Naming catalogue (ratifying D2-D9):**

| Category | Names | Source |
| --- | --- | --- |
| Env var prefix | `COGAME_` for all reporter-side env vars | D2 |
| Reporter-side reads | `COGAME_RESULTS_URI`, `COGAME_REPLAY_URI` (renamed from game's `COGAME_SAVE_REPLAY_URI`), `COGAME_LOG_URI`, `COGAME_EPISODE_METADATA_URI`, `COGAME_MANIFEST_URI` | D2 |
| Reporter id env var | `COGAME_REPORTER_ID` | D4 |
| Reporter write target | `COGAME_REPORT_OUTPUT_URI` (the `OUTPUT` modifier disambiguates write-destination from any future read-side report URI) | D2/D3 |
| Envelope fields | `version` (currently `"1"`), `artifacts: [{id, content_type, encoding?, content}]` | D3 |
| First-class content types | `text/markdown`, `text/plain`, `application/json`, `image/png` | D3 |
| Failure codes | `start_failed`, `nonzero_exit`, `timeout`, `missing_output`, `invalid_envelope` (snake_case) | D8 |
| Status record fields | `reporter_id`, `status`, `duration_ms`, `envelope`, `failure_reason`, `failure_detail`, `exit_code`, `previous_attempts` | D8 |
| Local workspace path | `reporter_outputs/<reporter_id>.*` | D8 |
| Synthetic certify metadata | `variant_id: "certification"`, `tags.context: "certification"` | D5 |
| API routes | `/episodes/{episode_id}/reports[/{reporter_id}[/artifacts/{artifact_id}\|/logs]]` | D9 |
| CLI commands | `coworld reports`, `coworld report-show`, `coworld report-download` | D9 |
| URI schemes | Same as game contract: `file://`, `http(s)://`, presigned S3 via `runner/io.py` | D2 |

**Rationale:**

- `REPORTER_RUNTIME_README.md` mirrors `GAME_RUNTIME_README.md` in name and location. Anyone who's read the game contract will find the reporter contract in the obvious adjacent file. Discoverability beats novelty.
- Recommendation-not-constraint for reporter ids matches how player ids and variant ids work in the existing manifest (`certifier.py:208-215`'s `_manifest_items_by_id` enforces uniqueness but no format). Adding a regex just for reporters would be inconsistent and add manifest complexity for no real problem.
- All other naming was implicitly settled in D2-D9. D10 catalogues them so a reader can audit naming choices in one place rather than re-reading nine decisions.

**Consequences:**

- §5 item 17 added.
- §6.1 (naming question) closed.
- §6 now has zero open questions. Section preamble updated to reflect that the v1 open-question slate is empty; new questions can be added there as they emerge.
- Implementation work: when the reporter contract lands in metta, `packages/coworld/src/coworld/REPORTER_RUNTIME_README.md` should be authored as the canonical runtime contract document, mirroring the structure of `GAME_RUNTIME_README.md`. The reporter-id naming recommendation should appear in that doc, not in the manifest schema.

**Explicitly NOT decided (deferred):**

- A formal manifest-schema validation pattern (regex) for reporter ids. v1 keeps the recommendation soft.
- An author-style guide for envelope artifact ids (`summary`, `stats`, `heatmap`, etc.). Authors free to name as they see fit; conventions can emerge organically and be added to `REPORTER_RUNTIME_README.md` over time.
- A naming registry for cross-coworld reporter conventions (e.g., "all coworlds should declare a reporter named `summary`"). Not a v1 concern.

---

## 9. Deferred ideas

This section consolidates the "Explicitly NOT decided" items from D1–D10 into thematic groups, so that v2+ design work has a single shopping list to draw from. Each item names the decision that surfaced it and, where applicable, the v1 workaround.

### 9.1 Triggering and execution model

- **Per-round triggers** (D1, §3 item 6). Reporters that summarize across the episodes in a round. Requires new artifact plumbing — round episode set, commissioner round-display output, cross-episode aggregation conventions. Needs its own design pass before implementing.
- **On-demand triggers** (D1, §3 item 7). User-triggered "rerun" against existing artifacts. **Shelved** (not actively deferred) because purity + idempotency makes reruns nominally no-ops. Revisit if user-controllable knobs become meaningful.
- **Pipelining between reporters** (D4). Reporter B consumes reporter A's output. Adds dependency declarations, topological scheduling, cross-reporter failure semantics. v1 workaround: wrap both stages inside one reporter container.
- **Conditional invocation in manifest** (D4). Reporters declaring "only run for variant X." v1 workaround: reporter emits empty `artifacts: []` envelope.
- **Separate dispatch system** (D6). Asynchronous reporter execution outside the runner — new queue, worker pool, artifact-ready signaling. Revisit if D1's on-demand decision is reopened, or if D4's per-round design needs cross-episode reporters.
- **Manual triggering against archived artifacts** (D6). Shelved per D1.

### 9.2 Manifest extensions

- **Per-reporter resource overrides** (D4). e.g., `resources: { cpu, memory }` on a reporter entry. Add when a real reporter needs different allocation than the 2 CPU + 2Gi baseline.
- **Per-reporter timeout overrides** (D5). e.g., `timeout_seconds: 120`. Add when a reporter genuinely needs longer than 60s.
- **Per-reporter retry-policy overrides** (D8). e.g., `retries: { on_timeout: 3 }`. Add when the default uniform policy causes real friction.
- **Author-side opt-out from timeout retry** (D8). Same family.
- **Per-input opt-in declarations** (D2). Reporters declaring which inputs they actually want (bandwidth optimization). Revisit when a reporter actually pays a real cost for unused inputs.
- **Per-artifact JSON Schema declaration** (D7). The biggest deferred manifest extension. Future shape intentionally left **open and flexible** — design from real use cases when concrete demand surfaces; do not anchor on D7's strawman.
- **Regex enforcement on reporter ids** (D10). v1 keeps the convention soft (uniqueness only).
- **Concurrency cap on reporter parallelism** (D4). Add if a coworld declares enough reporters to overwhelm a host or pod.

### 9.3 Envelope and content types

- **Additional first-class content types** (e.g., SVG, CSV) (D3). Promote when concrete demand surfaces.
- **Inline vs. by-reference JSON schemas in the envelope** (D3). Depends on D7's future extension.
- **Output size limits** beyond the ~10MB soft recommendation (D3).
- **Envelope `version: "2"`** (D3). v1 freezes at `"1"`.

### 9.4 Inputs and metadata

- **Custom intermediate artifacts from the game** (D2). Game-side exposure of non-results, non-replay artifacts to reporters. v1 workaround: embed in `results.json` or in the replay.
- **Observatory deep-link URL in episode metadata** (D2). Defer until needed — hard to populate uniformly across hosted vs. local contexts.

### 9.5 Operations and observability

- **`--skip-reporters` flag** in `coworld certify` (D5) and local commands (D6). Add when iteration speed becomes a real friction.
- **Performance / SLA checks** during certification (D5). v1 only verifies "exits within timeout"; no margin check.
- **Additional failure_reason codes** (`oom_killed`, `network_unreachable`, etc.) (D8). Add when they become consistently distinguishable from the v1 codes.
- **Metrics emission** (Datadog/etc.) on reporter failure (D8). Implementation detail worth doing eventually.

### 9.6 Observatory enhancements

- **Cross-episode aggregation endpoints** (`GET /leagues/{id}/reports?reporter_id=...`, `GET /divisions/{id}/reports?...`) (D9). The biggest deferred Observatory feature.
- **Trend / time-series visualizations** of `application/json` artifacts (D9).
- **Reporter-output embedding in non-Observatory surfaces** (softmax.com landing pages, etc.) (D9).
- **Webhooks / notifications** on reporter outcomes (D9). v1 is pull-only.
- **Diff / comparison views** across episodes (D9).
- **API pagination** for the list endpoint (D9).
- **Reporter-output search** (D9).
- **Typed rendering of JSON artifacts** (D7). e.g., recognize stats objects, render charts. Observatory design problem, not a reporter-contract concern.

### 9.7 Documentation and conventions

- **Author-style guide for envelope artifact ids** (`summary`, `stats`, `heatmap`, etc.) (D10). Conventions can emerge organically and land in `REPORTER_RUNTIME_README.md`.
- **Cross-coworld reporter naming registry** (e.g., "all coworlds should declare a reporter named `summary`") (D10).
- **Required-vs-encouraged stance on internal validation** (D7). v1 picks encouraged; revisit if author non-compliance is a real problem.

---

## 10. Changelog

- **2026-05-18** — Initial scaffold. Hard constraints, strong defaults, goals, non-goals, open questions, and a v1 working sketch. No decisions yet.
- **2026-05-18** — **D1** logged. v1 cadence is per-episode only; reporters are pure functions of their inputs, determinism preferred. Per-round deferred; on-demand shelved. §2 goal 1, §3 items 6-7, §5 items 7-8, §6 (former 6.1 closed, remaining renumbered), §7 updated.
- **2026-05-18** — **D2** logged. Reporter input/output contract: env-supplied URIs for results, replay, optional logs, episode metadata JSON, full manifest, and output. Renamed `COGAME_SAVE_REPLAY_URI` → `COGAME_REPLAY_URI` for reporter-side reads. No opt-in declarations in v1; tokens excluded. §5 item 9 added, §6 (former 6.1 closed, remaining renumbered to 6.1-6.8), §7 working sketch updated with new env block and strawman episode metadata shape.
- **2026-05-19** — **D3** logged. Reporter output is a single JSON envelope `{version, artifacts: [{id, content_type, [encoding], content}]}`. Per-invocation flexibility (no manifest field needed) and native multi-artifact. First-class content types in v1: `text/markdown`, `text/plain`, `application/json`, `image/png` (base64). HTML excluded. Empty `artifacts: []` permitted. No streaming. §5 item 10 added, §5 item 9 tail sentence updated, §6 (former 6.1 closed, remaining renumbered to 6.1-6.7), §7 working sketch gained an output-envelope strawman and updated reporter/runner behavior bullets.
- **2026-05-19** — **D4** logged. Multiple reporters: all run, in parallel, independent. Each reporter gets a unique output URI keyed on `(episode_id, reporter_id)` and its own `COGAME_REPORTER_ID` env var. Resource baseline 2 CPU + 2Gi per reporter; no manifest-side per-reporter overrides in v1; failure isolation per reporter. Display order = declaration order. §5 item 9 amended; §5 item 11 added; §6 (former 6.1 closed, remaining renumbered to 6.1-6.6); §7 working sketch env block + runner bullets updated. Stale `§6.X` refs in D2 and D3 cleaned up; cross-references to open questions now use the `§6.X 'Title'` form so they survive future renumbers.
- **2026-05-19** — **D5** logged. `coworld certify` now exercises every declared reporter end-to-end against the smoke episode's real artifacts plus a synthesized episode-metadata JSON (`variant_id: "certification"`, `tags: {"context": "certification"}`). Each reporter must exit 0 within a per-reporter timeout (default 60s) and write a valid envelope (D3). Any failure causes certification to fail — intentional asymmetry with the D4 runtime, which tolerates per-reporter failures. §5 item 12 added; §6 (former 6.1 closed, remaining renumbered to 6.1-6.5); §7 closing certification line expanded. Stale `§6.X` cross-refs in D2 and D4 deferred-items swept.
- **2026-05-19** — **D6** logged. Reporters run co-located with the episode inside the runner (both local Docker and hosted K8s); no separate dispatch in v1. The reporter lifecycle fires from hosted production episodes, `coworld run-episode`, `coworld certify`, and `coworld play` (only on natural completion). `coworld replay` and replay-server mode do not run reporters. Episode failure or missing/invalid artifacts → silent skip of the reporter step. §5 item 13 added; §6 (former 6.1 closed, remaining renumbered to 6.1-6.4); §7 runner bullet 1 amended with the episode-completion gate; new "CLI surface (D6)" paragraph added. Stale `§6.X` refs in D4 and D5 deferred-items swept.
- **2026-05-19** — **D7** logged. Output schema declaration is shelved for v1. No `output_schema` or per-artifact schema field on reporter manifest entries. The D3 envelope schema is the only platform-level output validation. Reporter authors are **encouraged but not required** to validate output internally. Future extension (per-artifact schemas via something like `artifacts: [{id, content_type, schema?}]`) is intentionally left open and flexible — designed when concrete demand surfaces, not pre-anchored on today's strawman. §5 item 14 added; §6 (former 6.1 closed, remaining renumbered to 6.1-6.3). Stale `§6.X` references in §5 items 9 and 12, §7 runner bullet 2, and D2/D3 deferred items swept.
- **2026-05-19** — **D8** logged. Failure semantics: 5-code taxonomy (`start_failed`, `nonzero_exit`, `timeout`, `missing_output`, `invalid_envelope`); **one retry on `timeout` only**, fresh output URI, uniform across runtime and certification; per-reporter status records with envelope on success / failure metadata + captured logs on failure; `previous_attempts` array when retries occurred; runner exit code reflects episode success only, orthogonal to reporter status; no platform-injected failure envelopes; no partial-success salvage. §5 item 15 added; §7 working sketch bullet 4 firmed up (last working hypothesis closed); §6 (former 6.1 closed, remaining renumbered to 6.1-6.2). Stale `§6.X` refs in §5 item 11 and D4 swept to point at D8 directly.
- **2026-05-19** — **D9** logged. Observatory exposes reporter outputs via four new API routes under each episode (list, detail, artifact-direct, logs). Frontend renders first-class content types inline (Markdown with artifact-id rewriting, plain text, JSON tree, PNG). HTML stored but never inline-rendered. Markdown artifact-id substitution is Observatory's responsibility (reporters stay portable). CLI parity: `coworld reports`, `coworld report-show`, `coworld report-download`. Cross-episode aggregation, search, trends, webhooks, and pagination explicitly deferred. §5 item 16 added; §7 working sketch bullet 3 updated; §6 (former 6.1 closed, §6.2 renumbered to §6.1). Stale `§6.X` refs in D3 and §5 item 15 swept to point at D9.
- **2026-05-19** — **D10** logged. Naming conventions ratified across D2-D9 and catalogued in one place. Canonical reporter-runtime contract document is `REPORTER_RUNTIME_README.md` (peer to `GAME_RUNTIME_README.md` in `packages/coworld/src/coworld/`). Reporter `id` format in the manifest is a recommendation (lowercase with hyphens or underscores) — only uniqueness is platform-enforced; no regex. §5 item 17 added; §6.1 closed; §6 now empty — preamble updated to note the v1 open-question slate is complete. **All initial open questions resolved.**
- **2026-05-19** — **Finalization pass.** Reframed status header and intro from design-conversation to v1 specification. Added unnumbered "Executive Summary" with one-screen contract table + implementation footprint. §1 problem statement past-tensed to match completed-design framing. §2/§3 retitled (removed "(initial)" qualifiers). §5 item 5 rewritten to reflect D7's "no schemas in manifest" decision instead of the original "open" framing. §7 retitled from "Working sketch" to "v1 Contract reference" and stripped of strawman framing. Stale `§6.X` forward-references in D1, D3, D5 swept to point at the resolving D-entries (D5, D7, D8) since the questions they reference were all subsequently closed. Added §9 "Deferred ideas" — consolidates the "Explicitly NOT decided" items from D1-D10 into seven thematic groups (triggering, manifest extensions, envelope, inputs, ops, Observatory, docs). Changelog moved to §10.
