# guided_bot

Modular hybrid agent for Among Them with a fast scripted inner loop
(per-tick perceive → update → decide → act) and a slower asynchronous
LLM guidance loop that sets the active **mode** and its structured
parameters. Modes are the primary extensibility surface; adding one
is a new file plus one registry entry.

**Design doc:** [`DESIGN.md`](DESIGN.md). Load-bearing — read it before
editing.

**Implementation plan:** [`IMPL_PLAN.md`](IMPL_PLAN.md). Phase 6+
roadmap based on a full mode audit (2026-05-01).

**Fix log:** [`FIX_PLAN.md`](FIX_PLAN.md). Diagnostic findings and
historical bug fixes.

## Status

**Orbit bug fixed — bot navigates and completes tasks.** The A\*
path-following oscillation bug that caused the bot to orbit ±5 px
indefinitely has been resolved (see changelog below). In a 30 s local
match the bot now reaches its target task station in ~137 ticks and
holds A for the remainder of the game. Localization locks reliably on
live gameplay frames (100% lock rate after the initial interstitial
window).

Phase 4 (structured trace writer), phase 3 (LLM guidance loop),
phase 2 (action layer + mode strategies), and phase 1 (full
perception pipeline) remain intact underneath. All eight test suites
pass; both CLI and library builds succeed.

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
| 2.0 | A\* pathfinding on walk mask + button-mask generation + stuck detection + jiggle + ghost steering | done |
| 2.1 | `task_completing` mode — task-icon-based target selection, A\* navigation, hold-A completion | done |
| 2.2 | `meeting` mode — vote-skip fallback (cursor-right to SKIP, press A) | done |
| 2.3 | Reflex system — 4 starter reflexes: body→reporting, body→fleeing, lone-crew→hunting, voting→meeting | done |
| 2.4 | `hunting` mode — preferred/opportunistic kill-strike + cover-behavior wander | done |
| 2.5 | `pretending` mode — walk-to-task loiter cycle for imposter cover | done |
| 2.6 | `reporting` mode — navigate to body, press A via DisciplineReport | done |
| 2.7 | `fleeing` mode — steer away from body for duration/distance | done |
| 3.1 | `snapshot.nim` — belief-state JSON rendering for LLM (DESIGN.md §8.3) | done |
| 3.2 | `llm.nim` — real Anthropic Messages API client (curly + jsony) | done |
| 3.3 | `guidance.nim` — worker thread + channels (snapshot→directive, meeting actions) | done |
| 3.4 | `bot.nim` — periodic/triggered snapshot submission + directive channel reads + TTL expiry | done |
| 3.5 | `modes/meeting.nim` — LLM-driven meeting behavior with chat, voting, and safety-net fallback | done |
| 3.6 | `prompts.nim` — system prompts for gameplay directives and meeting actions | done |
| 4 | Trace writer — structured JSONL output per DESIGN.md §11 | done |
| 5 | Fallback-only playability test; first submission | done |
| — | Orbit bug fix: PathLookahead 18→4, periodic replan, stall detector | done |
| — | Trace enhancement: decision records include mask + self position | done |
| 6.1 | `task_completing` hold lifecycle + completion detection + belief task state + radar checkout | done |
| 6.2 | `reporting` success detection + body-visibility check + approach/in-range timeouts | done |
| 6.3 | `meeting` cursor-aware vote navigation + timer fix + auto-vote delay (chat deferred) | done |
| 6.4 | `hunting` cover patrol + target memory + kill confirmation + KillStrikeRange bump | done |

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
  action.nim                # ActionIntent -> button mask (A*, stuck detect, jiggle)
  mode_registry.nim         # mode lookup + default directive
  reflex.nim                # reflex evaluation (edge-triggered mode switches)
  guidance.nim              # worker-thread + channels (phase 3)
  llm.nim                   # Anthropic Messages API client (curly + jsony, phase 3)
  snapshot.nim              # belief → JSON snapshot for the LLM (phase 3)
  prompts.nim               # system prompts for gameplay + meeting LLM calls (phase 3)
  trace.nim                 # trace writer (phase 4)
  nim.cfg                   # nimby package paths (curly, jsony, libcurl)
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
    fallback_test.nim       # phase-5 fallback-only playability
    test_action_table.py    # Python: BITWORLD_ACTION_MASKS ordering guard
    fixtures/               # raw frame dumps for the fixture tests
```

## Building

Phase 3 requires `curly`, `jsony`, and `libcurl` (via nimby). Package
paths are configured in `nim.cfg` in the guided_bot directory. The Nim
compiler picks this up automatically when building from the repo root
with `--path:among_them/guided_bot`.

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

# Phase 5 — fallback-only playability: validation gate (non-NOOP
# within 10 frames), mode transitions, no-crash full sequence,
# default-directive-source invariant.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/fallback_test.nim

# Python — action-table ordering guard. Verifies BITWORLD_ACTION_MASKS
# matches the canonical direction×modifier formula that ffi/lib.nim's
# TrainableMasks relies on.
PYTHONPATH=among_them .venv/bin/python -m unittest \
    among_them.guided_bot.test.test_action_table -v
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

## Running

The CLI entry point does not yet open a WebSocket to the game server
(the runner loop mirroring `modulabot/viewer/runner.nim` is a future
deliverable). Currently it prints parsed flags and runs one decide
call on a zero frame so you can confirm the binary builds and the
pipeline wires through.

```sh
among_them/guided_bot/guided_bot --port:2000 --name:gb0
```

For actual gameplay, use the cogames FFI path — `cogames/amongthem_policy.py`
loads the shared library and routes `step_batch` through it.

## Tracing

Structured trace output is opt-in via environment variables. When enabled,
the bot writes JSONL streams and a manifest to the trace directory. When
disabled (the default), every trace call is a nil-check early return with
near-zero cost.

```sh
# Enable tracing with decisions-level detail:
GUIDED_BOT_TRACE_DIR=/tmp/guided_bot_trace \
GUIDED_BOT_TRACE_LEVEL=decisions \
  among_them/guided_bot/guided_bot --port:2000

# Trace levels:
#   events     — events.jsonl only
#   decisions  — events + decisions + modes + reflexes + guidance
#   full       — all of the above + snapshots.jsonl + frames.bin
```

Output files per session (in `GUIDED_BOT_TRACE_DIR`):

| File | Level | Content |
|---|---|---|
| `manifest.json` | events | Round metadata, schema version, role, start/end ticks, outcome |
| `events.jsonl` | events | Game events: body_seen, meeting_started, role_revealed, chat_observed, game_over |
| `decisions.jsonl` | decisions | Per-frame mode, directive source, params, intent, final button mask, self position, localized flag |
| `modes.jsonl` | decisions | Mode transitions: entered/exited with duration |
| `reflexes.jsonl` | decisions | Reflex firings with trigger details |
| `guidance.jsonl` | decisions | LLM calls: snapshot_sent, llm_response, directive_published, llm_call_failed |
| `snapshots.jsonl` | full | Periodic full-belief JSON snapshots (~every 240 ticks) |
| `frames.bin` | full | Raw 128x128 frame bytes for replay |

See DESIGN.md §11 for the exact JSON schemas.

## Submissions

See [`cogames/README.md`](cogames/README.md). Phase 5 added fallback-only
playability: the bot emits non-NOOP actions from tick 1 on gameplay frames
(passes the cogames 10-step validation gate on fixture data). A Docker
dry-run against `beta-cvc` confirmed the FFI bundle loads and the Nim
library compiles; the `among-them` season returns 404 on API access
despite appearing in `cogames season list` (phantom entry as of
2026-05-01).

The `mettagrid.bitworld` import is now optional in `amongthem_policy.py`
(inline fallback constants) so the policy loads in Docker images that
only ship `mettagrid` without the `bitworld` extra.

## Submission log

| Date | Policy name | Season | Dry-run | Leaderboard |
|---|---|---|---|---|
| 2026-05-01 | jamesboggs-guided-bot-fallback-test | among-them | **blocked**: season 404 | — |
| 2026-05-01 | jamesboggs-guided-bot-dryrun | beta-cvc (fallback) | import fixed, Nim build attempted | — |

## Change log (recent)

**2026-05-01 — orbit bug fix + trace enhancements**

- **`action.nim`:** Fixed the A\* path-following oscillation bug.
  `PathLookahead` reduced from 18 to 4 so the waypoint stays on the
  A\* corridor through turns. Added periodic path recomputation every
  `ReplanIntervalTicks=24` (~1 s) and a stall detector that forces
  replan when distance to goal hasn't decreased in
  `StallProgressTicks=48` (~2 s). See DESIGN.md §6.3 for the full
  analysis.
- **`trace.nim` / `bot.nim`:** `logDecision` now includes the final
  button mask (`mask`), self position (`self_x`, `self_y`), and
  `localized` flag. The log call moved from before `applyIntent` to
  after so the mask is available.
- **`types.nim`:** `ActionState` gained three fields for
  replan/stall tracking: `lastReplanTick`, `bestGoalDist`,
  `bestGoalDistTick`.

**2026-05-01 — action-table fix + idle wander + compile-time guard**

- **`ffi/lib.nim`:** `TrainableMasks` reordered to match
  `mettagrid.bitworld.BITWORLD_ACTION_MASKS`. The old ordering
  (direction-first: noop/a/b/up/down/left/right/up+a/...) had 22 of
  27 entries misaligned with the Python-side table (direction+modifier:
  noop/a/b/up/up+a/up+b/down/...). This caused every non-trivial
  action the Nim bot produced to be garbled when sent to the game
  server. Compile-time assertion (`CanonicalMasks` + `static:` block)
  added to prevent future drift.
- **`test/test_action_table.py`:** Python-side guard that verifies
  `BITWORLD_ACTION_MASKS` itself follows the canonical
  direction×modifier formula.
- **`types.nim` / `action.nim` / `tuning.nim` / `modes/idle.nim`:**
  New `DisciplineWander` — raw directional movement without A\* or
  localization. Idle mode now cycles through cardinal directions on
  non-interstitial frames instead of returning noop. Helps the
  localizer see fresh map pixels and passes the cogames 10-step gate.
- **`DESIGN.md`:** §6.1 (`DisciplineWander`) and §6.2 (FFI
  action-index contract) added.

## Known gaps / next steps

See [`IMPL_PLAN.md`](IMPL_PLAN.md) for the full phase 6+ roadmap.

0. ~~**Task-completion detection missing.**~~ **DONE (phase 6.1).**
   Three-phase hold lifecycle (Navigate → Hold → Confirm),
   belief-layer task state with icon-miss counting and radar-dot
   checkout latching, tiered target selection, trace events.
1. **Imposter fallback not live-tested.** Hunting / pretending /
   fleeing defaults have not been verified against the orbit fix.
   Run an imposter-seeded local match and confirm kill-strike +
   cover behaviors work.
2. **Localization reliability (design-level).** The camera localization pipeline has
   three tiers: local refit (fast, ~0.1 ms), patch-hash vote (fast,
   ~5 ms), and spiral scan (capped at `SpiralMaxRadius=120` px,
   ~60 ms worst-case). The spiral cap was added in phase 5 to
   prevent ~11s hangs on non-matching frames. But the deeper problem
   is that the spiral fires at all — it means both faster tiers
   failed. Improvements to pursue:
   - **Pre-game / lobby frame rejection.** The interstitial detector
     only flags high-black-pixel-count frames. Lobby screens have
     coloured content and are NOT flagged, so the localizer wastes
     time on them. A lightweight classifier (e.g. dominant-colour
     histogram, known lobby-sprite check, or map-pixel sample
     agreement ratio) that gates `updateLocation` would eliminate
     these calls entirely.
   - **Patch index coverage.** `locateByPatches` should be the
     dominant cold-localize path — it runs in ~5 ms and uses
     spatial hashing to narrow candidates. If it's failing on real
     gameplay frames, the likely cause is ignore-mask over-coverage
     (too many patches marked invalid) or hash collisions in
     featureless regions. Auditing the patch validity rate on the
     fixture frames and loosening the ignore mask in the first few
     frames (before actor exclusions are populated) would help.
   - **Spiral seeding.** When the spiral does run, its seed position
     determines how quickly it converges. Currently it seeds from
     the last known camera or the button position. Seeding from
     the best patch-vote candidate (even if below the vote
     threshold) would centre the spiral closer to the truth.
2. **Pre-game frame detection.** The interstitial detector only flags
   high-black-pixel-count frames. Lobby/setup frames have colored
   content and are NOT flagged, so the localizer runs the spiral on
   them. Extending the detector to reject non-map frames would
   prevent wasted spiral calls.  (Overlaps with item 1.)
3. **Integration test with live LLM** (phase 3 follow-up). Run a full
   local match with `ANTHROPIC_API_KEY` set and verify the bot changes
   behavior mid-match based on LLM directives.
4. **Meeting cursor precision.** The meeting mode uses repeated
   CursorRight as a brute-force approach. A future improvement is to
   read the actual cursor position from the voting parse and navigate
   precisely to the target slot.
5. **Task-state machine.** The raw `IconMatch` / `RadarDotMatch` lists
   from phase 1.4 are consumed by `task_completing` for basic
   nearest-station selection, but there is no full task-state machine
   yet (icon->task assignment latching, icon-miss pruning, mandatory
   vs completed tracking). That's a quality-of-play improvement.
6. **Self-colour recall.** `updateSelfColor` currently uses the scalar
   `matchesCrewmate` check at the known player anchor. On some frames
   the player sprite doesn't match cleanly. A future improvement is to
   carry the last known colour forward when no match fires.
7. **Hunting target memory.** The hunting mode currently only pursues
   crewmates visible on the current frame. A short-term memory of
   last-seen positions would improve imposter behavior.
8. **A\* path caching.** The current implementation recomputes A\* from
   scratch on every goal change. Path segment caching or incremental
   repair could reduce worst-case latency.
9. **Prompt iteration.** The system prompts in `prompts.nim` are
   starting points. Iterate based on match performance.
10. **CurlPool reuse.** The LLM client creates a fresh CurlPool per
    call to sidestep GC-safety. A thread-local pool would avoid the
    per-call overhead (negligible at <1 Hz call rate, but cleaner).
