# guided_bot

Modular hybrid agent for Among Them with a fast scripted inner loop
(per-tick perceive → update → decide → act) and a slower asynchronous
LLM guidance loop that sets the active **mode** and its structured
parameters. Modes are the primary extensibility surface; adding one
is a new file plus one registry entry.

**Design doc:** [`DESIGN.md`](DESIGN.md). Load-bearing — read it before
editing.

## Status

**Phase 0 — scaffolding (this commit).** Compiles cleanly as CLI and
shared library; every decision returns no-op. Mode registry wired for
the full v0 enum (11 modes); belief state + directive + action intent
types all declared. LLM and guidance loop are stubs.

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffolding, type shapes, registry, no-op pipeline, FFI + Python wrapper | ✅ shipped |
| 1 | Perception (wire in modulabot's localize / sprite / task / voting parse) | not started |
| 2 | Per-mode strategy (start with `task_completing`, `pretending`, `hunting`) + action layer (A\*, momentum, task-hold) | not started |
| 3 | Guidance worker thread + `llm.nim` HTTP client (adapted from `bitworld/ais/claude.nim`) + meeting mode direct-control | not started |
| 4 | Trace writer end-to-end (manifest + events + decisions + modes + guidance + reflexes + snapshots) | not started |
| 5 | Fallback-only playability test; first submission | not started |

## Strategy

In one sentence: an LLM sets strategic intent (mode + params) on a slow
outer loop; a scripted inner loop runs modes whose decisions are a pure
function of the shared belief state and their own scratch state.

See DESIGN.md §5 (modes), §7 (meetings), §9 (fallback), §5.8 (reflexes).

## Directory layout

```
guided_bot/
  DESIGN.md                 # design doc (living)
  README.md                 # this file
  constants.nim             # local copies of BitWorld constants (phase 0)
  types.nim                 # Bot, Belief, Directive, ActionIntent, ModeName
  tuning.nim                # cross-cutting tunable knobs
  bot.nim                   # initBot, decideNextMask, pipeline
  belief.nim                # initBelief, updateBelief
  perception.nim            # phase-1 home for modulabot perception modules
  action.nim                # ActionIntent -> button mask
  mode_registry.nim         # mode lookup + default directive
  reflex.nim                # reflex evaluation (phase 2)
  guidance.nim              # worker-thread shell
  llm.nim                   # HTTP LLM client (phase 2)
  trace.nim                 # trace writer (phase 4)
  guided_bot.nim            # CLI entry + library gate
  modes/
    idle.nim               task_completing.nim      fear.nim
    investigating.nim      reporting.nim            pretending.nim
    hunting.nim            fleeing.nim              alibi_building.nim
    sabotage_watching.nim  meeting.nim
  ffi/lib.nim               # FFI exports (gated by -d:guidedBotLibrary)
  build_guided_bot.py       # on-demand Nim build helper
  cogames/
    amongthem_policy.py     # cogames MultiAgentPolicy wrapper
    ship.sh                 # dry-run / upload / ship convenience wrapper
    README.md
  test/smoke.nim            # phase-0 smoke test
```

## Building

Phase 0 has no external Nim dependencies — `nim c` works without nimby.

```sh
# CLI binary (release mode).
nim c -d:release --threads:on --mm:orc \
    -o:among_them/guided_bot/guided_bot \
    among_them/guided_bot/guided_bot.nim

# Shared library for cogames FFI.
nim c -d:release --opt:speed --app:lib -d:guidedBotLibrary \
    --threads:on --mm:orc \
    -o:among_them/guided_bot/libguidedbot.dylib \
    among_them/guided_bot/guided_bot.nim

# Or let the Python helper handle it on demand.
python3 among_them/guided_bot/build_guided_bot.py
```

## Smoke test

```sh
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/smoke.nim
```

Expected output: `OK`. Tests: `initBot` shape, `decideNextMask` returns
0 on a zero frame, default-directive routing (alive imposter →
`ModeHunting`, ghost override → `ModeTaskCompleting`).

## Running (phase 0)

The CLI entry point does not yet open a WebSocket to the game server;
that's a phase-2 deliverable (mirroring `modulabot/viewer/runner.nim`).
Phase 0 prints parsed flags and runs one decide call on a zero frame
so you can confirm the binary builds and the pipeline wires through.

```sh
among_them/guided_bot/guided_bot --port:2000 --name:gb0
```

## Submissions

See [`cogames/README.md`](cogames/README.md). **Don't submit phase 0**
— the bot is no-op; the dry-run will fail the cogames 10-step
validation gate ("Policy took no actions"), which is a correctly-
diagnosed empty bot, not a perception-timing issue. Wait until modes
produce real output (phase 2+).

## Submission log

| Date | Policy name | Season | Dry-run | Leaderboard |
|---|---|---|---|---|
| _none yet_ | | | | |

## Known gaps / next steps

1. **Wire perception** (phase 1). `perception.nim` is the single place
   to drop modulabot's localize/sprite/task/voting stack.
2. **Implement first real mode** (phase 2). Start with
   `task_completing` since it's both the crewmate default and the
   ghost default (DESIGN.md §5.7, §9.1). Its action layer needs A\* +
   momentum; phase-2 work lives mostly in `action.nim` + that one
   mode file.
3. **LLM worker** (phase 3). Adapt `bitworld/src/bitworld/ais/claude.nim`
   into `llm.nim`, wire the worker thread in `guidance.nim`, and gate
   it on `-d:guidedBotGuidance` until the HTTP dependency is bundled.
4. **Trace** (phase 4). `trace.nim` has stable signatures; fill the
   bodies per DESIGN.md §11.
5. **Fallback-only playability** (phase 5). DESIGN.md §9.2 — a full
   match with the LLM forcibly failing must pass validation, cast
   votes, and complete at least one task.
