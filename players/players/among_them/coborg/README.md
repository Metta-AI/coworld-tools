# coborg_among_them

A pure-Python Among Them agent built on the
[`players_lib.coborg`](../../../../src/players_lib/coborg/) two-loop
Cyborg runtime. This is the framework's **first concrete in-repo game client**.

> **Status (2026-05-13)**: Planning complete, implementation not started. The
> durable implementation plan is [`PLAN.md`](./PLAN.md). The next session
> should land P0 (scaffold + Coworld harness) as described in
> [PLAN §6](./PLAN.md#6-phasing) and [§11](./PLAN.md#11-first-week-sequence-start-here-in-the-new-session).

---

## What this is

`coborg_among_them` is a new BitWorld Among Them agent that:

- Runs **completely in Python** — no Nim toolchain in the runtime image, no
  `.so` produced from Nim. The Nim perception stack (~3.5k lines across
  `personal_cogs/among_them/{common,guided_bot}/perception*/`) is **ported
  to numpy** with parity tests against the Nim ground truth.
- Is **pixel-first**: parses BitWorld's 128×128 4-bit packed frame directly.
  A small, documented set of belief fields may be sourced from the structured
  state vector when pixels would be lossy (see PLAN §10 R5, D9).
- Plugs `perceive → update_belief → mode decide → action resolve` into
  `coborg.AgentRuntime`, with deterministic rule-based strategy producing
  validated `ModeDirective`s.
- Ships as a single Docker image consumed by the Coworld tournament runner
  (`coworld play …`); **stdout = protocol, stderr = logs/traces**.
- Caps scope at **P4: deterministic imposter-capable agent**. LLM strategy is
  explicitly deferred to a follow-on plan (PLAN §6 "Out of scope").

This is a **parallel experiment**. The production Daily-league submission
remains [`guided_bot`](https://github.com/) in
`~/coding/personal_cogs/among_them/guided_bot/`, which is not modified by
this work (PLAN D7).

## How it differs from the existing scripted policy

The sibling package
[`players.among_them.scripted`](../among_them/__init__.py)
(Softmax's `BitWorldAmongThemScoutPolicy` / `BitWorldAmongThemCyborgPolicy`)
is a screen-space scripted policy that implements the mettagrid
`AgentPolicy` interface directly. It is a useful reference for the BitWorld
state-vector layout and action constants, but it is **not** a coborg client
and does not perceive from pixels.

`coborg_among_them` is a separate, more ambitious agent that:

| | Scripted `among_them` (existing) | `coborg_among_them` (this package) |
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
              coworld/policy_player.py   (coworld.player.v1 bridge)
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
[`frameworks/coborg/docs/metta_cogames_framework/README.md`](../../../../../frameworks/coborg/docs/metta_cogames_framework/README.md)
for the full invariants and anti-patterns this agent must respect.

## Project layout (target end-state at P4)

The directory will fill out across P0–P4. See
[PLAN §4](./PLAN.md#4-project-layout-target-end-state-at-p4) for the full
tree. Headline subpackages:

- `perception/` — numpy port of the Nim perception stack, plus a parity
  harness (`perception/parity/`) that diffs Python output against Nim on a
  checked-in fixture set.
- `modes/` — symbolic modes (`idle`, `navigate_to`, `complete_task`,
  `meeting`, `speak`, `vote`, `report_body`, `kill_target`, `loiter`).
- `strategy/` — `rule_based.py` (deterministic) + `snapshot.py` reserved
  for the deferred LLM strategy.
- `coworld/` — `Dockerfile`, `entrypoint.sh`, `policy_player.py`
  (`coworld.player.v1` WebSocket bridge).
- `tests/` — unit, parity, mode-lifecycle, reflex, and a transcript-replay
  smoke test for the player bridge.

## How to run (planned)

> Not yet runnable. P0 lands the noop scaffold; the commands below are the
> P0 done-criteria from [PLAN §6](./PLAN.md#p0--scaffold--coworld-harness).

```bash
# 1. Download the Among Them coworld package (manifest + assets)
cd ~/coding/metta
uv run coworld download among_them --output-dir ./coworld

# 2. Build the player image
docker build -t coborg_among_them:dev \
  -f ~/coding/players/players/among_them/coborg/coworld/Dockerfile \
  ~/coding/players

# 3. Play locally — one image fills all 8 player slots
uv run coworld play ./coworld/coworld_manifest.json \
  --variant default \
  --timeout-seconds 120 \
  --no-open-browser \
  coborg_among_them:dev
```

A convenience wrapper at `scripts/play_local.sh` will land in P0.

## Scope

| Phase | Deliverable | Done criterion (summary) |
|---|---|---|
| P0 | Scaffold + Coworld harness | Noop agent completes a 120s `coworld play` run, traces on stderr |
| P1 | Perception port | Parity tests green vs Nim; <8 ms perception per tick |
| P2 | Crewmate | ≥3 tasks completed in a 120s match |
| P3 | Meetings & voting | Full meeting cycle with legal vote |
| P4 | Imposter | ≥1 kill on imposter-pinned seeds (50, 100) |
| (out) | LLM strategy, league submission, advanced social reasoning | Deferred |

## Key references

| Need | Path |
|---|---|
| **The plan** | [`./PLAN.md`](./PLAN.md) |
| Coborg framework code | `~/coding/players/src/players_lib/coborg/` |
| Coborg architecture doc | `…/coborg/docs/metta_cogames_framework/README.md` |
| Coborg toy example (assembly pattern to mirror) | `…/coborg/docs/metta_cogames_framework/examples/toy_grid_agent.py` |
| Existing scripted Among Them (state-vector reference) | `../__init__.py` |
| Current production bot (do **not** modify) | `~/coding/personal_cogs/among_them/guided_bot/` |
| Nim perception — shared kernels (port source) | `~/coding/personal_cogs/among_them/common/perception_kernels/` |
| Nim perception — bot-specific (port source) | `~/coding/personal_cogs/among_them/guided_bot/perception/` |
| Coworld player bridge to mirror | `~/coding/personal_cogs/among_them/guided_bot/coworld/policy_player.py` |
| Coworld runner (protocol authority) | `~/coding/metta/packages/coworld/src/coworld/runner/runner.py` |
| BitWorld Among Them game source (Nim) | `~/coding/bitworld/among_them/` |
| Coworld manifest (game constants) | `~/coding/bitworld/among_them/coworld_manifest.json` |

## Open items

1. **PLAN §12** — confirm D8 (numpy-first / numba-fallback perception),
   D9 (state-vector taps for lossy belief fields), the P4 stop point, and
   the Nim parity ground-truth strategy.
2. **PLAN §10 R1 — toolchain flake.** Root cause identified and resolved
   2026-05-13: stale `~/.nimby/nimbylock/` directory plus seven nimby
   cache entries missing their `.git`. `uv run coworld --help`,
   `uv run coworld download among_them`, and `uv run coworld play` (P0
   smoke) all succeed. See R1 in PLAN.md for recovery procedure if it
   recurs.
