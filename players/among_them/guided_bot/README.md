# guided_bot

Modular hybrid agent for Among Them with a fast scripted inner loop
(per-tick perceive → update → decide → act) and a slower asynchronous
LLM guidance loop that sets the active **mode** and its structured
parameters. Modes are the primary extensibility surface; adding one
is a new file plus one registry entry.

**Design doc:** [`DESIGN.md`](DESIGN.md). Load-bearing — read it before
editing.

## Status

**Phase 1.3 — actor / body / ghost scanning (this commit).** Compiles
cleanly as CLI and shared library; every decision still returns no-op
(action layer is phase 2). Phase-1.0 frame primitives, 1.1 reference
data, and 1.2 camera localization are still in place; phase 1.3 ports
modulabot's actor scanning orchestration to pure Nim, sharing the
existing `mb_match_actor_sprite_all` and `mb_actor_color_index_all`
kernels in `among_them/common/perception_kernels/sprite_match.nim`
via direct relative-path imports. The bot pipeline now:

- Detects role (crewmate / imposter / ghost) from the HUD kill-button
  and ghost-icon sprites.
- Identifies self-colour via single-anchor crewmate colour vote at the
  player's known screen position.
- Scans for other crewmates, dead bodies, and ghosts using the
  vectorised all-anchors match kernel + greedy dedup.
- Stamps detected sprite exclusion zones into the ignore mask (for the
  benefit of phase 1.4 task-icon scanning and future localize
  refinement).
- Merges all results into the belief state (`SelfState.role`,
  `SelfState.colorIndex`, `PerceptionState.visibleCrewmates/Bodies/Ghosts`).

Scan cost: ~2 ms per gameplay frame (cold and warm) on the fixture set.
Interstitial frames short-circuit (0 cost).

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffolding, type shapes, registry, no-op pipeline, FFI + Python wrapper | done |
| 1.0 | Frame unpacking, interstitial detection, ignore-mask scaffolding, fixture tests | done |
| 1.1 | Perception reference data (palette, sprites, map/walk/wall, font, map.json) baked from the upstream `~/coding/bitworld` checkout (single source of truth) and embedded via `staticRead` | done |
| 1.2 | Camera localization (patch-hash global + local refit + spiral fallback). Reuses modulabot's perception kernels via direct `--path:` import | done |
| 1.3 | Actor / body / ghost scanning via `mb_match_actor_sprite_all` + `mb_actor_color_index_all`. Role + self-colour detection. Ignore-mask actor exclusions | done |
| 1.4 | Task-icon + radar-dot scanning via `mb_scan_task_icons` | next |
| 1.5 | ASCII OCR via `mb_best_glyph` + `mb_text_matches` | depends 1.1 |
| 1.6 | Voting-screen parse | depends 1.5 |
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
  perception.nim            # phase-1 perception orchestrator
  perception/
    data.nim                # phase 1.1 — palette, sprites, map, font (baked)
    frame.nim               # phase 1.0 — bit unpack + pixel helpers
    interstitial.nim        # phase 1.0 — black-pixel screen detector
    ignore.nim              # phase 1.0 — dynamic-pixel ignore mask
    geometry.nim            # phase 1.2 — camera / world coord math
    localize.nim            # phase 1.2 — camera localization orchestration
    actors.nim              # phase 1.3 — crewmate/body/ghost scan, role, self-colour
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

1. **Phase 1.4 — task-icon + radar-dot scan.** Wrap
   `common/perception_kernels/actors.nim`'s `mb_scan_task_icons`.
   Populate `PerceptionState.visibleTaskIcons` and the task-state
   machine in `Belief.tasks`. Stamp task-icon exclusions into the
   ignore mask.
2. **Self-colour recall.** `updateSelfColor` currently uses the scalar
   `matchesCrewmate` check at the known player anchor. On some frames
   the player sprite doesn't match cleanly (e.g. during walking
   transitions). A future improvement is to use the vectorised kernel
   in a small window around the player anchor, or to carry the last
   known colour forward when no match fires.
3. **Implement first real mode** (phase 2). Start with
   `task_completing` since it's both the crewmate default and the
   ghost default (DESIGN.md §5.7, §9.1). Its action layer needs A\* +
   momentum; phase-2 work lives mostly in `action.nim` + that one
   mode file.
4. **LLM worker** (phase 3). Adapt `bitworld/src/bitworld/ais/claude.nim`
   into `llm.nim`, wire the worker thread in `guidance.nim`, and gate
   it on `-d:guidedBotGuidance` until the HTTP dependency is bundled.
5. **Trace** (phase 4). `trace.nim` has stable signatures; fill the
   bodies per DESIGN.md §11.
6. **Fallback-only playability** (phase 5). DESIGN.md §9.2 — a full
   match with the LLM forcibly failing must pass validation, cast
   votes, and complete at least one task.
