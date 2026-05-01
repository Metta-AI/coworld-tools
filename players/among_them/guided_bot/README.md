# guided_bot

Modular hybrid agent for Among Them with a fast scripted inner loop
(per-tick perceive → update → decide → act) and a slower asynchronous
LLM guidance loop that sets the active **mode** and its structured
parameters. Modes are the primary extensibility surface; adding one
is a new file plus one registry entry.

**Design doc:** [`DESIGN.md`](DESIGN.md). Load-bearing — read it before
editing.

## Status

**Phase 1 complete — full perception pipeline.** Compiles cleanly as
CLI and shared library; every decision still returns no-op (action
layer is phase 2). The perception pipeline covers all six sub-phases:

- **1.0** Frame unpacking, interstitial detection, ignore-mask scaffolding.
- **1.1** Baked reference data (palette, sprites, map, font) via `staticRead`.
- **1.2** Camera localization (~1 ms cold, <1 ms warm).
- **1.3** Actor scanning — crewmates, bodies, ghosts, role, self-colour (~2 ms).
- **1.4** Task-icon + radar-dot scanning (~0.1 ms).
- **1.5** ASCII OCR — `textMatches`, `bestGlyph`, `findText`, interstitial
  banner classification (~12 ms for full-frame `findText` sweep).
- **1.6** Voting-screen parse — grid layout, slot parsing (alive/dead +
  colour), cursor/self-marker/vote-dot detection, SKIP text check,
  chat OCR with speaker attribution.

Total per-frame perception cost (gameplay): ~5 ms. Interstitial
classification: ~12 ms (banner OCR sweep). Voting parse: variable,
dominated by chat OCR line count.

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffolding, type shapes, registry, no-op pipeline, FFI + Python wrapper | done |
| 1.0 | Frame unpacking, interstitial detection, ignore-mask scaffolding, fixture tests | done |
| 1.1 | Perception reference data baked from upstream `~/coding/bitworld` checkout via `staticRead` | done |
| 1.2 | Camera localization (patch-hash global + local refit + spiral fallback) | done |
| 1.3 | Actor / body / ghost scanning + role + self-colour detection + ignore-mask exclusions | done |
| 1.4 | Task-icon scanning via `mb_scan_task_icons` + radar-dot scanning | done |
| 1.5 | ASCII OCR — `mb_best_glyph` + `mb_text_matches` + `findText` + interstitial classification | done |
| 1.6 | Voting-screen parse — grid layout, slot/cursor/vote-dot parsing, chat OCR + speaker attribution | done |
| 2 | Per-mode strategy (start with `task_completing`, `pretending`, `hunting`) + action layer (A\*, momentum, task-hold) | next |
| 3 | Guidance worker thread + `llm.nim` HTTP client + meeting mode direct-control | not started |
| 4 | Trace writer end-to-end | not started |
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
  perception.nim            # phase-1 perception orchestrator
  perception/
    data.nim                # phase 1.1 — palette, sprites, map, font (baked)
    frame.nim               # phase 1.0 — bit unpack + pixel helpers
    interstitial.nim        # phase 1.0 — black-pixel screen detector
    ignore.nim              # phase 1.0 — dynamic-pixel ignore mask
    geometry.nim            # phase 1.2 — camera / world coord math
    localize.nim            # phase 1.2 — camera localization orchestration
    actors.nim              # phase 1.3 — crewmate/body/ghost scan, role, self-colour
    tasks.nim               # phase 1.4 — task-icon scan (mb_scan_task_icons) + radar dots
    ocr.nim                 # phase 1.5 — pixel-font OCR (mb_best_glyph, textMatches, findText)
    voting.nim              # phase 1.6 — voting-screen parse (grid, slots, chat OCR)
    baked/                  # *.bin blobs (regen via tools/bake_assets.sh)
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
  tools/
    bake_assets.nim         # regenerate perception/baked/ from upstream bitworld
    bake_assets.sh          # wrapper that wires nim --path: flags
  cogames/
    amongthem_policy.py     # cogames MultiAgentPolicy wrapper
    ship.sh                 # dry-run / upload / ship convenience wrapper
    README.md
  test/
    smoke.nim               # phase-0 pipeline smoke test
    perception_test.nim     # phase-1.0 perception fixtures + end-to-end
    data_test.nim           # phase-1.1 baked-asset shape + parity
    localize_test.nim       # phase-1.2 camera-lock pinning + benchmark
    actors_test.nim         # phase-1.3 actor scan, role, self-colour, pipeline
    tasks_test.nim          # phase-1.4 task-icon scan, radar dots, pipeline
    ocr_voting_test.nim     # phase-1.5/1.6 OCR, voting parse, pipeline
    fixtures/               # raw frame dumps for the fixture tests
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

## Tests

```sh
# Phase 0 smoke — pipeline shape, ghost override, default directives.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/smoke.nim

# Phase 1.0 — frame unpacking, interstitial detection, ignore mask,
# end-to-end perceive() + updateBelief() against fixture frames.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/perception_test.nim

# Phase 1.1 — palette / sprite / map / font shape, magic-number checks,
# parity pins against modulabot's source data.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/data_test.nim

# Phase 1.2 — camera math, patch index, fixture-pinned camera locks
# (matches modulabot ground truth), pipeline + reseed flow, smoke
# benchmark.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/localize_test.nim

# Phase 1.3 — actor scan (crewmates, bodies, ghosts), role + self-colour
# detection, ignore-mask actor exclusions, end-to-end bot pipeline,
# fixture sweep, smoke benchmark.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/actors_test.nim

# Phase 1.4 — task-icon scan (mb_scan_task_icons), radar-dot scan,
# imposter skip, ignore-mask task-icon exclusions, end-to-end bot
# pipeline, fixture sweep, smoke benchmark.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/tasks_test.nim

# Phase 1.5/1.6 — font packing, textMatches, bestGlyph, readRun,
# findText, classifyInterstitial, voting grid layout, end-to-end
# pipeline fixture sweep, smoke benchmarks.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/ocr_voting_test.nim
```

Each prints `OK` and exits 0 on success, or `FAIL: <label> ...` lines
plus a non-zero exit on a regression.

## Regenerating baked assets

`perception/baked/*.bin` are deterministic outputs of
`tools/bake_assets.nim` against the upstream bitworld checkout
(`~/coding/bitworld`, override with `BITWORLD_DIR`). The tool is Nim
so it can use the same `bitworld/aseprite` parser the live server
uses to render `skeld2.aseprite` and `tiny5.aseprite` — no Python
aseprite library required, and no risk of the modulabot snapshot
drifting from upstream.

Re-run when the upstream Among Them assets change:

```sh
among_them/guided_bot/tools/bake_assets.sh
# or override the source dir:
BITWORLD_DIR=/path/to/bitworld among_them/guided_bot/tools/bake_assets.sh
```

Requirements: `nim` + `nimby`-installed `pixie` and `zippy` (already
available on any machine that's built bitworld). The `guided_bot`
runtime binary itself does not depend on either.

Bump `BakeSchemaVersion` in both `tools/bake_assets.nim` and
`perception/data.nim` on any layout change so a stale baked dir
trips the compile-time shape asserts.

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

1. **Implement first real mode** (phase 2). Start with
   `task_completing` since it's both the crewmate default and the
   ghost default (DESIGN.md §5.7, §9.1). Its action layer needs A\* +
   momentum; phase-2 work lives mostly in `action.nim` + that one
   mode file.
2. **Task-state machine.** The raw `IconMatch` / `RadarDotMatch` lists
   from phase 1.4 are not yet consumed by a task-state machine
   (icon→task assignment, checkout latching, icon-miss pruning). That's
   policy-layer logic for phase 2.
3. **Self-colour recall.** `updateSelfColor` currently uses the scalar
   `matchesCrewmate` check at the known player anchor. On some frames
   the player sprite doesn't match cleanly. A future improvement is to
   carry the last known colour forward when no match fires.
4. **`classifyInterstitial` perf.** `findText` does a full-frame sweep
   (~12 ms) per banner. This could be optimized by restricting the Y
   search range to the known banner region or by implementing the numpy
   sliding-window approach in Nim. Not a bottleneck since it only runs
   on interstitial frames.
5. **LLM worker** (phase 3). Adapt `bitworld/src/bitworld/ais/claude.nim`
   into `llm.nim`, wire the worker thread in `guidance.nim`.
6. **Trace** (phase 4). `trace.nim` has stable signatures; fill the
   bodies per DESIGN.md §11.
7. **Fallback-only playability** (phase 5). DESIGN.md §9.2 — a full
   match with the LLM forcibly failing must pass validation, cast
   votes, and complete at least one task.
