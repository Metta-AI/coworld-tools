# Commissioners

This repo is the implementation home for Coworld commissioner runnables. It currently ships only its baseline structure
— this README, a `CATALOG.yaml`, and package metadata — and **no commissioner implementations yet**. There are no
runnable commissioner containers, examples, or templates in this checkout.

That is deliberate. The previous contents were stale scaffolding, including an Among Them image that wrote a descriptor
file instead of implementing the Coworld commissioner protocol. Do not recreate descriptor-output contracts such as
`COGAME_COMMISSIONER_OUTPUT_URI`; they are not part of the current commissioner runtime.

## Goal

A commissioner decides what happens inside a hosted league round:

- which episodes to schedule;
- which submitted policy versions play in each episode and in which slots;
- how completed episode scores become per-division rankings;
- which memberships move between divisions;
- what opaque commissioner state should be carried into the next round.

The commissioner is not the game, not a player, and not a post-episode artifact consumer. It is a per-round control-loop
role that tells the platform which episodes to run. The platform runs the game and player containers, captures episode
outputs, and routes completed episode results back to the commissioner.

## Current Status

The authoritative Metta docs currently mark the commissioner role as:

```text
contract defined, runtime pending
```

That means the protocol is written down and has in-process backend implementations, but the platform does not yet invoke
containerized commissioner runnables from this repo automatically. Until that changes in `Metta-AI/metta`, this repo
should not carry placeholder images that look deployable.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `README.md` | This orientation doc. |
| `CATALOG.yaml` | Canonical list of commissioner implementations this repo provides (currently empty). |
| `pyproject.toml` | Python package metadata for shared tooling and tests. |
| `commissioners/<game>/<name>/` | One directory per commissioner implementation (none yet). |

## Catalog

`CATALOG.yaml` is the source of truth for which commissioners this repo provides. Per `Metta-AI/metta` spec
`docs/specs/0045-coworld-role-repos.md`, an implementation exists in a role repo **if and only if** it has an entry in
`CATALOG.yaml`: source on disk without a catalog entry is incomplete, and a catalog entry without source is broken. Each
entry carries the `image` and `source_url` that get copied into a Coworld manifest's `commissioner[]` section. The
catalog is intentionally empty (`entries: []`) until the first real commissioner lands; the file documents the full
entry schema inline.

## Source Of Truth

This repo must not redefine Coworld contracts. Check `Metta-AI/metta` first, especially:

| Need | Authoritative Metta path |
| --- | --- |
| Commissioner role contract and status | `packages/coworld/src/coworld/docs/roles/COMMISSIONER.md` |
| Protocol message models | `packages/coworld/src/coworld/commissioner/protocol.py` |
| Coworld role model and artifact flow | `packages/coworld/src/coworld/docs/README.md` |
| Manifest semantics | `packages/coworld/src/coworld/docs/COWORLD_MANIFEST.md` |
| Manifest Pydantic models and generated schema source | `packages/coworld/src/coworld/types.py` |
| Round decisions artifact | `packages/coworld/src/coworld/docs/artifacts/ROUND_DECISIONS.md` |
| Results object feeding commissioner scores | `packages/coworld/src/coworld/docs/artifacts/RESULTS.md` |
| Role-repo structure and catalog expectations | `docs/specs/0045-coworld-role-repos.md` |
| Existing in-process Among Them reference | `app_backend/src/metta/app_backend/v2/AMONGTHEM_COMMISSIONER.md` and `app_backend/src/metta/app_backend/v2/commissioners.py` |

Also read `packages/coworld/AGENTS.md` before changing public Coworld behavior or docs in Metta. It points at the
current Coworld documentation map and validation commands.

## Contract Snapshot

This is only an orientation summary. If it disagrees with Metta, Metta wins.

A real commissioner container is expected to:

- listen on `0.0.0.0:8080`;
- serve `GET /healthz` with HTTP 200 when ready for the round WebSocket;
- serve `WEBSOCKET /round`;
- receive platform messages including `round_start`, `episodes_accepted`, `episodes_rejected`, `episode_result`,
  `episode_failed`, and `round_abort`;
- send commissioner messages including `schedule_episodes` and `round_complete`;
- close cleanly on `round_abort` without sending `round_complete`;
- finish the round by sending `round_complete` with per-division rankings, optional graduation changes, optional display
  data, and optional opaque state;
- keep cross-round memory only through the platform-provided `state` blob, which is limited to 10 MB.

The current protocol models name the important shapes:

- `RoundStart`: round id and number, league config, divisions, active memberships, recent results, variants, and previous
  state;
- `EpisodeRequest`: commissioner-generated request id, variant id, ordered policy-version ids, optional seed, and tags;
- `EpisodeResult`: completed request id, extracted per-policy scores, and the full game results object;
- `RoundComplete`: per-division rankings, graduation changes, optional `round_display`, and optional next-round state.

The commissioner does not receive episode bundles in the protocol. Bundles are for post-episode roles such as reporters,
graders, and diagnosers. Commissioners consume the round-level `episode_result` / `episode_failed` stream.

## Manifest Expectations

Commissioners are declared in `coworld_manifest.json` under `commissioner[]`. The section is optional in the current
schema and marked future-required metadata in Metta. Every entry must use `type: "commissioner"` and the normal runnable
shape from `CoworldManifestRoleSpec`: `id`, `name`, `description`, `image`, optional `run`, optional public `env`, and
optional `source_url`.

`source_url` should point at the real implementation source, not a README-only placeholder. `coworld certify` checks
declared role image reachability and validates GitHub `source_url` paths for non-empty contents and a Dockerfile at that
path or an ancestor build root.

## Boundaries

Keep these boundaries intact:

- Runtime contracts, schemas, CLI behavior, tournament dispatch, and Observatory integration belong in
  `Metta-AI/metta`.
- This repo should contain commissioner implementation source, implementation-specific tests, Dockerfiles, and
  implementation docs once real commissioner containers exist.
- Role-specific tools can live here if they are only useful for commissioners.
- Cross-role tooling belongs in the Coworld package, not here.
- Game-specific runtime logic belongs with the game unless the code is genuinely commissioner scheduling/ranking logic.

## Adding The First Real Commissioner

Before adding files here:

1. Re-read the Metta source-of-truth files above.
2. Confirm the containerized commissioner runtime is actually supported or explicitly accept that the implementation is
   ahead of the platform.
3. Implement the `/healthz` and `/round` WebSocket contract, not a file-output descriptor contract.
4. Add a Dockerfile for the runtime image.
5. Add implementation docs that describe scheduling policy, ranking policy, graduation policy, state shape, config, and
   local test commands.
6. Add tests for protocol parsing, scheduling decisions, ranking decisions, state persistence, and abort/failure paths.
7. Add a `CATALOG.yaml` entry. This is required, not optional: an implementation only "exists" in this repo once it is
   cataloged with an `image` and `source_url`.
8. Update the relevant Coworld manifest in Metta only after the implementation source, image, and source URL are real.

Until those conditions are met, prefer no implementation files over placeholders.
