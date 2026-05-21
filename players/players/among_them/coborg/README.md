# coborg_among_them

A pure-Python Among Them agent built on the
[`players.player_sdk`](../../player_sdk/) two-loop Cyborg runtime (the
Coworld Player SDK). This is the SDK's **first concrete in-repo game client**.

> **Status (2026-05-19)**: **P0 scaffold landed.** Idle/noop agent wired
> end-to-end through the BitWorld `bitscreen_v1` WebSocket bridge; 17 tests
> green (`pytest players/among_them/coborg/tests`) including an in-process
> Coworld bridge smoke. Build + local-play scripts are in place. No
> perception, belief, or non-trivial modes yet. Next phase is P1
> (perception port from Nim to numpy) — see [`PLAN.md` §6](./PLAN.md#6-phasing).

---

## What this is

`coborg_among_them` is a new BitWorld Among Them agent that:

- Runs **completely in Python** — no Nim toolchain in the runtime image, no
  `.so` produced from Nim. The Nim perception stack (~3.5k lines across
  `personal_cogs/among_them/{common,guided_bot}/perception*/`) is being
  **ported to numpy** in P1, with parity tests against the Nim ground truth.
- Is **pixel-first**: parses BitWorld's 128×128 4-bit packed frame directly.
  A small, documented set of belief fields may be sourced from the structured
  state vector when pixels would be lossy (see PLAN §10 R5, D9).
- Plugs `perceive → update_belief → mode decide → action resolve` into
  `players.player_sdk.AgentRuntime`, with a deterministic rule-based strategy
  producing validated `ModeDirective`s.
- Ships as a single Docker image consumed by the Coworld tournament runner
  (`coworld play …`); **stdout = protocol channel, stderr = logs/traces**.
- Caps scope at **P4: deterministic imposter-capable agent**. LLM strategy is
  explicitly deferred to a follow-on plan (PLAN §6 "Out of scope").

This is a **parallel experiment**. The production Daily-league submission
remains `guided_bot` in `~/coding/personal_cogs/among_them/guided_bot/`,
which is not modified by this work (PLAN D7).

## How it differs from the other Among Them players in this repo

The `players/among_them/` tree currently holds three Among Them players:

- [`scripted/`](../scripted/__init__.py) — Softmax's
  `BitWorldAmongThemScoutPolicy` / `BitWorldAmongThemCyborgPolicy`. A
  screen-space scripted policy that implements the mettagrid `AgentPolicy`
  interface directly. Useful reference for the BitWorld state-vector layout
  and action constants. Not a coborg client; does not perceive from pixels.
- [`starter/`](../starter/README.md) — `ivotewell`, the canonical Nim
  starter player from BitWorld (vendored here so policy changes round-trip
  via PR review). Speaks `bitscreen_v1` directly from a Nim binary. Not a
  Python coborg client.
- `coborg/` (this package) — Python coborg agent. See table below for how
  it compares to the scripted policy above:

| | Scripted `among_them` | `coborg_among_them` (this package) |
|---|---|---|
| Architecture | flat `AgentPolicy.act()` | coborg two-loop (inner + strategy) |
| Perception | state vector | 128×128 pixel frame (numpy) |
| Strategy | inline rules | typed `ModeDirective`s via `Strategy` |
| Role support | (per existing impl) | crewmate + imposter (P2 + P4) |
| Tracing | none | coborg `TraceSink`/`MetricsSink` to stderr |

## Architecture (target)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Coworld runner (Docker, WebSocket on host.docker.internal:8080)         │
│  ws://…/player?slot=N&token=…   ↔   128×128 4-bit frame in / 7-bit mask out │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │
              coworld/policy_player.py   (bitscreen_v1 binary bridge)
                               │
┌──────────────────────────────▼───────────────────────────────────────────┐
│  AgentRuntime (per-tick, non-blocking)                                   │
│                                                                          │
│    perceive ──► update_belief ──► mode.decide ──► resolve_action         │
│       ▲                                                                  │
│       │                                  ┌────────────────────────────┐  │
│       │                                  │  Strategy runner (slower)  │  │
│       └── reflexes (priority-ordered) ◄──┤  belief snapshot → directive│  │
│                                          └────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

The strategy loop reads `BeliefSnapshot` (lock-protected, latest-wins) and
emits typed, validated `ModeDirective`s. The inner loop never blocks on
strategy; if no fresh directive is available, the runtime applies the
configured default. See
[`players/player_sdk/docs/metta_cogames_framework/README.md`](../../player_sdk/docs/metta_cogames_framework/README.md)
for the full invariants and anti-patterns this agent must respect.

## Project layout

Current state (P0 landed; subsequent phases fill out the gaps — see
[PLAN §4](./PLAN.md#4-project-layout-target-end-state-at-p4) for the target
tree at P4):

- `__init__.py`, `types.py`, `action.py`, `trace.py` — runtime assembly
  (`build_runtime`), typed data structures, action resolver, stderr
  trace/metrics sinks.
- `modes/idle.py` — the only P0 mode (emits noop).
- `strategy/rule_based.py` — placeholder strategy that always issues `idle`.
- `coworld/` — `Dockerfile`, `entrypoint.sh`, and `policy_player.py` (the
  `bitscreen_v1` binary WebSocket bridge).
- `scripts/play_local.sh` — convenience wrapper around `uv run coworld play`.
- `build.sh` — canonical builder; emits `coborg-among-them:dev` Docker image
  plus the `coworld_manifest.json` `player[]` snippet and
  `dist/coplayer_manifest.json`.
- `tests/` — unit tests for the action resolver, idle mode, trace sinks,
  the assembled runtime, and an in-process Coworld bridge smoke.

P1 adds `perception/` (numpy port of the Nim perception stack plus a parity
harness). P2–P3 add the rest of the mode set
(`navigate_to`, `complete_task`, `meeting`, `speak`, `vote`, `report_body`)
and the rule-based crewmate planner. P4 adds `kill_target` and `loiter`
plus role-aware strategy branching.

## How to run

The agent runs end-to-end today as an idle/noop player.

**Tests:**

```bash
uv run pytest players/among_them/coborg/tests
```

**Local Coworld play (one image fills all 8 slots):**

```bash
# Builds the image if missing, downloads the among_them coworld package
# if missing, then runs `uv run coworld play` with the P0 defaults.
players/among_them/coborg/scripts/play_local.sh
```

`play_local.sh` requires `docker`, `uv`, and a checkout of `Metta-AI/metta`
at `$METTA_REPO` (default `~/coding/metta`). It defaults to image tag
`coborg-among-them:dev` — the same tag `build.sh` produces — and self-builds
the image from the Dockerfile if it isn't already in the local Docker cache.
Pass a different tag as the first positional arg to override.

### Protocol note

The bridge ([`coworld/policy_player.py`](coworld/policy_player.py)) speaks the
binary [`bitscreen_v1`](https://github.com/Metta-AI/bitworld/blob/master/docs/bitscreen_v1.md)
wire protocol — NOT the JSON `coworld.player.v1`. This leaf therefore does
**not** use the SDK's
[`coworld_json_bridge`](../../player_sdk/coworld_json_bridge.py); that bridge
is for cogsguard-style JSON players.

## Scope

| Phase | Status | Deliverable | Done criterion (summary) |
|---|---|---|---|
| P0 | **Landed (2026-05-19)** | Scaffold + Coworld harness | Noop agent completes a 120s `coworld play` run, traces on stderr |
| P1 | Next | Perception port | Parity tests green vs Nim; <8 ms perception per tick |
| P2 | Planned | Crewmate | ≥3 tasks completed in a 120s match |
| P3 | Planned | Meetings & voting | Full meeting cycle with legal vote |
| P4 | Planned | Imposter | ≥1 kill on imposter-pinned seeds (50, 100) |
| (out) | Deferred | LLM strategy, league submission, advanced social reasoning | — |

## Key references

| Need | Path |
|---|---|
| **The plan** | [`./PLAN.md`](./PLAN.md) |
| **Design notes** | [`./DESIGN.md`](./DESIGN.md) |
| Player SDK framework code | `../../player_sdk/` |
| Player SDK architecture doc | [`../../player_sdk/docs/metta_cogames_framework/README.md`](../../player_sdk/docs/metta_cogames_framework/README.md) |
| Player SDK toy example (assembly pattern to mirror) | `../../player_sdk/docs/metta_cogames_framework/examples/toy_grid_agent.py` |
| Existing scripted Among Them (state-vector reference) | [`../scripted/__init__.py`](../scripted/__init__.py) |
| Nim starter player (sibling leaf) | [`../starter/README.md`](../starter/README.md) |
| Current production bot (do **not** modify) | `~/coding/personal_cogs/among_them/guided_bot/` |
| Nim perception — shared kernels (port source) | `~/coding/personal_cogs/among_them/common/perception_kernels/` |
| Nim perception — bot-specific (port source) | `~/coding/personal_cogs/among_them/guided_bot/perception/` |
| Coworld player bridge to mirror | `~/coding/personal_cogs/among_them/guided_bot/coworld/policy_player.py` |
| Coworld runner (protocol authority) | `~/coding/metta/packages/coworld/src/coworld/runner/runner.py` |
| BitWorld Among Them game source (Nim) | `~/coding/bitworld/among_them/` |
| Coworld manifest (game constants) | `~/coding/bitworld/among_them/coworld_manifest.json` |
| Coworld player-packaging contract | [`../../../docs/coworld-player-packaging.md`](../../../docs/coworld-player-packaging.md) |

## Open items

- **PLAN §12** — confirm D8 (numpy-first / numba-fallback perception),
  D9 (state-vector taps for lossy belief fields), the P4 stop point, and
  the Nim parity ground-truth strategy.
