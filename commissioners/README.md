# Commissioners

This repo is the implementation home for Coworld commissioner runnables. It ships its baseline structure (this README,
`CATALOG.yaml`, package metadata) plus the [default commissioner](commissioners/default/) — a reference round-robin
implementation.

> **New here? Start with the public Coworld docs.** The commissioner contract is defined in the public
> [`Metta-AI/coworld`](https://github.com/Metta-AI/coworld) package, not in this repo. If you need to know what a
> commissioner *is* or how the round protocol works, read these first:
>
> - **Commissioner role contract & round lifecycle** —
>   [`docs/roles/COMMISSIONER.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/roles/COMMISSIONER.md)
> - **What a Coworld is (roles + artifact flow)** —
>   [`docs/README.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/README.md)
> - **Protocol message models** —
>   [`commissioner/protocol.py`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py)

This repo must not redefine those contracts; it consumes them. The previous contents were stale scaffolding, including
an Among Them image that wrote a descriptor file instead of implementing the Coworld commissioner protocol. Do not
recreate descriptor-output contracts such as `COGAME_COMMISSIONER_OUTPUT_URI`; they are not part of the current
commissioner runtime.

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
| `CATALOG.yaml` | Canonical list of commissioner implementations this repo provides. |
| `pyproject.toml` | Python package metadata for shared tooling and tests. |
| `commissioners/default/` | The [default commissioner](commissioners/default/) — game-agnostic reference implementation. |
| `commissioners/<game>/<name>/` | Game-specific commissioner implementations (none yet). |

## Catalog

`CATALOG.yaml` is the source of truth for which commissioners this repo provides. Per `Metta-AI/metta` spec
`docs/specs/0045-coworld-role-repos.md`, an implementation exists in a role repo **if and only if** it has an entry in
`CATALOG.yaml`: source on disk without a catalog entry is incomplete, and a catalog entry without source is broken. Each
entry carries the `image` and `source_url` that get copied into a Coworld manifest's `commissioner[]` section. The file
documents the full entry schema inline. Today it lists one implementation, `default`.

## Source Of Truth

This repo must not redefine Coworld contracts; it consumes them. The contracts live in the **public**
[`Metta-AI/coworld`](https://github.com/Metta-AI/coworld) package — check it first:

| Need | Authoritative source (public) |
| --- | --- |
| Commissioner role contract and status | [`docs/roles/COMMISSIONER.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/roles/COMMISSIONER.md) |
| Protocol message models | [`commissioner/protocol.py`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py) |
| Coworld role model and artifact flow | [`docs/README.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/README.md) |
| Manifest semantics | [`docs/COWORLD_MANIFEST.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/COWORLD_MANIFEST.md) |
| Manifest Pydantic models | [`types.py`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/types.py) |
| Generated manifest JSON Schema | [`coworld_manifest_schema.json`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/coworld_manifest_schema.json) |
| Round decisions artifact | [`docs/artifacts/ROUND_DECISIONS.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/artifacts/ROUND_DECISIONS.md) |
| Results object feeding commissioner scores | [`docs/artifacts/RESULTS.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/artifacts/RESULTS.md) |
| Coworld docs map and validation commands | [`AGENTS.md`](https://github.com/Metta-AI/coworld/blob/main/AGENTS.md) |

A few references are **Metta-internal** (private `Metta-AI/metta`) and have no public mirror:

| Need | Metta-internal path |
| --- | --- |
| Role-repo structure and catalog expectations | `docs/specs/0045-coworld-role-repos.md` |
| In-process Among Them commissioner reference | `app_backend/src/metta/app_backend/v2/AMONGTHEM_COMMISSIONER.md` and `.../v2/commissioners.py` |
| Container WebSocket driver / default commissioner work (unmerged) | PR `Metta-AI/metta#12840` |

## Contract Snapshot

This is only an orientation summary of the
[commissioner role contract](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/roles/COMMISSIONER.md). If it
disagrees with the public Coworld package, Coworld wins.

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

The current protocol models (in
[`commissioner/protocol.py`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py)) name
the important shapes:

- `RoundStart`: round id and number, league config, divisions, active memberships, recent results, variants, and previous
  state;
- `EpisodeRequest`: commissioner-generated request id, variant id, ordered policy-version ids, optional seed, and tags;
- `EpisodeResult`: completed request id, extracted per-policy scores, and the full game results object;
- `RoundComplete`: per-division rankings, graduation changes, optional `round_display`, and optional next-round state.

The commissioner does not receive episode bundles in the protocol. Bundles are for post-episode roles such as reporters,
graders, and diagnosers. Commissioners consume the round-level `episode_result` / `episode_failed` stream.

## Manifest Expectations

Commissioners are declared in `coworld_manifest.json` under `commissioner[]` (see the
[manifest guide](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/COWORLD_MANIFEST.md)). The section is
optional in the current schema and marked future-required metadata in Metta. Every entry must use
`type: "commissioner"` and the normal runnable shape from `CoworldManifestRoleSpec`: `id`, `name`, `description`,
`image`, optional `run`, optional public `env`, and optional `source_url`.

`source_url` should point at the real implementation source, not a README-only placeholder. `coworld certify` checks
declared role image reachability and validates GitHub `source_url` paths for non-empty contents and a Dockerfile at that
path or an ancestor build root.

## Boundaries

Keep these boundaries intact:

- Runtime contracts, schemas, CLI behavior, tournament dispatch, and Observatory integration belong in
  `Metta-AI/metta`.
- This repo contains commissioner implementation source, implementation-specific tests, Dockerfiles, and implementation
  docs — one self-contained directory per commissioner.
- Role-specific tools can live here if they are only useful for commissioners.
- Cross-role tooling belongs in the Coworld package, not here.
- Game-specific runtime logic belongs with the game unless the code is genuinely commissioner scheduling/ranking logic.

## Adding A Commissioner

The [default commissioner](commissioners/default/) is the worked example to copy. For a new implementation:

1. Re-read the source-of-truth links above, especially the
   [role contract](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/roles/COMMISSIONER.md).
2. Implement the `/healthz` and `/round` WebSocket contract, not a file-output descriptor contract.
3. Add a Dockerfile for the runtime image.
4. Add implementation docs that describe scheduling policy, ranking policy, graduation policy, state shape, config, and
   local test commands.
5. Add tests for scheduling decisions, ranking decisions, state handling, and abort/failure paths.
6. Add a `CATALOG.yaml` entry. This is required, not optional: an implementation only "exists" in this repo once it is
   cataloged with an `image` and `source_url`.
7. Update the relevant Coworld manifest in Metta only after the implementation source, image, and source URL are real.

Note that the platform's container-driven commissioner runtime is still pending (the role is "contract defined, runtime
pending"), so an implementation here may be ahead of the platform that will eventually invoke it.
