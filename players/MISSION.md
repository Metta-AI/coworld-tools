# MISSION

> **Living document.** Expect drift. Re-read this file at the start of every
> session. Update it whenever the mission, scope, or working practices change.
> If you're touching strategy, directory layout, or submission workflow, touch
> this file too. Stale missions are worse than no mission.
>
> Last reviewed: 2026-05-04

---

## What we're doing

Build high-quality agents ("cogs") for the games in Softmax's [Alignment
League Benchmark][alb] (aka **cogames**), submit them to the public
leaderboards, and iterate until they win.

[alb]: https://www.softmax.com/alignmentleague

Concretely, this repo is a workshop for multiple agents across multiple games:

- Each **game** gets its own top-level directory (e.g. `among_them/`,
  `cogs_vs_clips/`, `four_score/`).
- Each **agent** lives in its own subdirectory under the game it plays
  (e.g. `among_them/nottoodumb/`, `cogs_vs_clips/role_specialist/`).
- Agents can be Python-only, Nim-backed via ctypes, trained neural-net
  checkpoints, or hybrid scripted+LLM. Pick whatever wins.

## Goals, in priority order

1. **Ship a working submission** to the active season for each game we care
   about. "Working" means: passes `cogames` validation (or intentionally
   `--skip-validation` for known no-op-startup failures), gets picked up by
   the tournament runner, and plays real matches without crashing.
2. **Win.** Climb the leaderboard. Beat the `starter` / `baseline` policies,
   then beat the top human/team submissions.
3. **Self-improve.** Where feasible, let agents learn across games — memory
   dumps, post-game analysis, cross-game priors in system prompts, offline
   training on episode replays.
4. **Stay honest about what works.** Keep a running log per agent of what
   beat what, what got ejected, and what regressed. No cargo-culting.

## Non-goals (for now)

- Not building the cogames framework itself — that's Softmax's job, in
  `~/coding/metta/packages/cogames`.
- Not inventing new games in this repo. If we want a new game, upstream it.
- Not chasing every season. Pick one or two at a time and commit.

## How this repo is organized

```
personal_cogs/
├── MISSION.md              # this file
├── COGAMES.md              # cogames package primer, submission workflow,
│                           # available games/seasons
├── <game_name>/
│   ├── README.md           # game-level notes, conventions, shared code
│   ├── common/             # code two or more agents under this game share
│   │   ├── README.md       # what's here and who consumes it
│   │   └── <subdir>/       # e.g. perception_kernels/, proto/, traces/
│   └── <agent_name>/
│       ├── README.md       # agent-specific notes: strategy, status, scores
│       ├── policy.py       # or nim sources + FFI wrapper, per pattern
│       ├── build_*.py      # if Nim-backed
│       └── cogames/        # submission-packaging subdir (ship.sh, etc.)
└── notes/                  # cross-cutting experiments, post-mortems
```

**Conventions:**

- One agent per directory. No monorepo-style shared `main.py` at the root.
- Each agent directory has a `README.md` that answers: what strategy, what's
  the current leaderboard score, what's known broken, what's next.
- If two agents share substantial code, extract it to a `<game>/common/`
  subdirectory and have each agent import from there. Don't reach into one
  agent's tree from another. Don't speculatively grow `common/` either —
  the bar is at least two real consumers (e.g. modulabot + guided_bot
  sharing `among_them/common/perception_kernels/`).
- Game-of-the-week work goes in the game's directory, not at the root.

## Working practices

These are layered on top of `~/.config/opencode/AGENTS.md`. The general rules
(plan first, ask before destructive actions, match project style, run tests,
push back on bad ideas, keep docs in sync with code, don't commit without
being asked) apply here too. What follows is mission-specific.

### Always

- **Start each session by re-reading `MISSION.md` and `COGAMES.md`.** They
  drift. The season you targeted last week may be gone. The CLI flags may
  have changed. Trust live `cogames --help` over these files, and **update
  these files when you notice drift.**
- **Record submission results.** Every time you upload a policy, append a
  row to the agent's `README.md`: date, policy name, season, dry-run result,
  leaderboard score (fill in later). This is our only memory across
  sessions.
- **Dump game memory** where possible. For LLM-driven agents, save per-game
  episodic/strategic memory to JSON so we can synthesize learnings into
  future system prompts. (Pattern from `SMART_BOT_GUIDE.md`.)
- **Prefer live CLI help** over this doc, `COGAMES.md`, or `softmax.com/play.md`
  when they disagree. Live CLI wins.

### Before shipping

- Dry-run every submission (`ship.sh dry-run` or `cogames upload --dry-run`).
- Only use `--skip-validation` for the known "Policy took no actions (all
  no-ops)" failure mode on perception-based bots that need >10 frames to
  localize. Never use it to route around real bugs. See
  `COGAMES.md` § validation gate for the decision tree.
- Ship to the correct season. Verify with `cogames season show <name>`.
  Freeplay seasons are safe for iteration; team/tournament seasons have
  limited submission slots — don't burn one on a bad build.

### When adding a new agent

1. Create `<game>/<agent>/` with a `README.md` stub: strategy, status, TODO.
2. Copy the closest working agent as a template; rename every identifier.
3. Get `cogames play` or the local equivalent working end-to-end *before*
   touching submission packaging.
4. Then add the `cogames/` submission subdir and a `ship.sh` (or the
   Python-only equivalent — see `COGAMES.md` § submission patterns).
5. Dry-run. Fix. Ship. Record.

### Self-improvement loop

The long-term ambition is agents that get better the more they play. Concretely:

- **Per-game dumps**: serialize the full memory (working + episodic +
  strategic) at game end to `<agent>/runs/<game_id>.json`.
- **Cross-game synthesis**: before launching, load the last N dumps and
  distill them into a compact "prior learnings" block injected into the
  system prompt.
- **Post-game analysis** (optional): run a more capable model over raw
  dumps to produce structured lessons ("killing in Electrical is risky",
  "aggressive accusers are often imposters").
- **Offline training** (where relevant): for neural-net policies, train on
  collected episode replays. `cogames` exposes episode artifacts via
  `cogames episode show / replay` and `cogames match-artifacts`.

None of this is required on day one. It's where we're heading.

## Current focus

> Update this section whenever priorities shift. Don't let it rot.

**As of 2026-05-04:**

- **Game of the week / primary target:** Among Them (BitWorld social
  deduction). The `among-them` season has disappeared from
  `cogames season list` — only `beta-cvc` and `beta-teams-tiny-fixed` are
  live right now. Confirm whether a new Among Them season is imminent,
  or repoint to CvC.
- **Among Them is pixels-only.** Empirically verified via
  `among_them/scripts/play_local.py`: the `BitWorldRunner` hands us a
  `(4, 128, 128) uint8 kind=pixels` observation. No structured state is
  available in the tournament path. Any winning bot must do its own map
  localization, sprite matching, task recognition, and voting-screen
  parsing — the same work the Nim modulabot does in ~4 kLOC.
- **Infrastructure:** first agent scaffolded at
  `among_them/modulabot/` — modular Python port of the Nim modulabot
  architecture.
- **Perception foundation complete + Nim-accelerated**: `data.py`,
  `geometry.py`, `frame.py`, `sprite_match.py`, `actors.py`,
  `localize.py`, `voting.py`, `ascii.py` all dispatch hot kernels
  through Nim ctypes bindings in `modulabot/nim_perception/`.
  `scan_all` runs in ~2.5 ms on gameplay frames (was ~8.6 ms numpy
  / ~400 ms scalar). Cold localize ~0.9 ms. Voting-chat OCR
  ~8.6 ms. **236 tests pass** (parity-pinned between Nim and
  numpy on the 275-frame fixture); visual debug overlay at
  `scripts/debug_overlay.py`; benchmark harness at
  `scripts/bench_perception.py`. Remaining known gap: walking-pose
  crewmate recall is lower than Nim's.
- **Trace writer shipped.** `modulabot/trace.py` emits session
  manifest + per-agent `events.jsonl` + `decisions.jsonl` when
  `trace_dir` / `MODULABOT_TRACE_DIR` is set. Non-perturbing
  (verified by parity tests). Phase-1 equivalent of the Nim
  `TRACING.md` spec; snapshots / per-round dirs / frames-dump deferred.
- **Camera localization shipped.** `modulabot/localize.py` ports
  `localize.nim` (patch-hash global search, local refit, spiral
  fallback). 100% lock rate on 144 real gameplay fixture frames;
  p95 wall time 0.07 ms warm / ~5 ms cold (first-frame patch
  search). Unblocks `scan_task_icons`, A\*, and the pixel pipeline.
- **ASCII OCR shipped.** `modulabot/ascii.py` ports
  `common/pixelfonts.nim` + `among_them/texts.nim`. Re-rendered
  `tiny5.aseprite` to PNG via `among_them/tools/dump_tiny5_font.nim`
  because the upstream font changed (variable-width marker-delimited
  format, no longer the fixed-grid `ascii.png`). Vectorised
  `find_text` (<2 ms worst-case sweep) and vectorised `best_glyph`
  (groups glyphs by scan width for one numpy pass per width).
- **Voting parser shipped.** `modulabot/voting.py` ports the parse
  half of `voting.nim` (grid layout, slot / cursor / self-marker /
  vote-dot parsing, chat OCR with speaker attribution, sus-colour
  detection). ~4 ms on an empty-chat voting frame, ~25 ms with 5
  chat lines. Decision half in `policies/voting.py` reads from the
  parse cache with role-aware target selection (imposter bandwagons
  on chat-sus; crewmate votes only on firsthand evidence).
- **A\* pathfinding shipped.** `modulabot/path.py` ports `path.nim`
  (walk-mask A\*, path lookahead, goal-distance helper with
  ghost-Manhattan fallback). Real skeld2 map: short paths
  1–2 ms, typical task paths 10–30 ms, cross-map worst-case
  ~90 ms. Pure Python; could be vectorised further if it becomes
  a per-frame bottleneck (expected case is once-per-goal-change,
  not per-tick).
- **Perception moved to Nim via ctypes**. The hot
  pixel kernels (sprite matching, camera scoring, patch hashing,
  bulk patch-vote lookup, task-icon scanning, OCR glyph picks)
  now run as native code in `modulabot/nim_perception/`, dispatched
  through numpy fallbacks so `MODULABOT_DISABLE_NATIVE=1` still
  works. End-to-end `BotCore.step` gameplay p50: 9.0 ms → 2.6 ms
  (3.4×); cold localize 4.7 ms → 0.9 ms (5.2×); voting-chat OCR
  24.9 ms → 8.6 ms (2.9×). All Nim paths parity-pinned vs. numpy
  across the 275-frame fixture. See
  `modulabot/PERCEPTION_PERF_PLAN.md` for the phase-by-phase plan
  and results.
- **`among_them/common/perception_kernels/` extracted.** The Nim
  perception kernels (`sprite_match.nim`, `localize.nim`, `actors.nim`,
  `ocr.nim`) used to live at `among_them/modulabot/nim_perception/src/`
  and guided_bot reached into modulabot's tree to import them. Now
  they live at `among_them/common/perception_kernels/` and both
  agents are clean consumers: modulabot's `lib.nim` + `build.py` add
  `--path:` to compile the FFI dylib; guided_bot uses
  `from "../../common/perception_kernels/X" as kX import nil`. New
  `among_them/common/README.md` documents the convention. Modulabot's
  full 236-test suite + guided_bot's four test suites all green
  post-move. MISSION.md's repo-layout convention now explicitly
  describes `<game>/common/`.
- **guided_bot phase 1 complete (1.0–1.6).** Full perception pipeline
  ported to pure Nim with shared kernel imports. Phase 1.0: frame
  unpacking, interstitial detection, ignore mask. Phase 1.1: baked
  reference data via `staticRead`. Phase 1.2: camera localization
  (~1 ms). Phase 1.3: actor scanning — crewmates, bodies, ghosts,
  role, self-colour (~2 ms). Phase 1.4: task-icon + radar-dot scanning
  (~0.1 ms). Phase 1.5: ASCII OCR — `textMatches`, `bestGlyph`,
  `findText`, interstitial banner classification (~12 ms for
  full-frame sweep). Phase 1.6: voting-screen parse — grid layout,
  slot parsing (alive/dead + colour), cursor/self-marker/vote-dot
  detection, SKIP text check, chat OCR with speaker attribution.
  All four shared kernel files consumed (`sprite_match.nim`,
  `localize.nim`, `actors.nim`, `ocr.nim`). Seven test suites pass
  (smoke, perception, data, localize, actors, tasks, ocr_voting).
  Library build size ~1.7 MB.
- **guided_bot phase 2 complete (2.0–2.7).** Full action layer and
  mode strategy. A\* pathfinding, discipline-aware button masks,
  stuck detection, jiggle, ghost straight-line steering. Six mode
  handlers (`task_completing`, `meeting`, `hunting`, `pretending`,
  `reporting`, `fleeing`) plus a four-reflex system (body→reporting,
  body→fleeing, lone-crew→hunting, voting→meeting). All 7 test
  suites pass. Library + CLI build green.
- **guided_bot phase 3 complete (3.1–3.6).** LLM guidance loop wired
  end-to-end. `snapshot.nim` renders curated belief-state JSON for
  the LLM (DESIGN.md §8.3). `llm.nim` calls the Anthropic Messages
  API via curly+jsony (adapted from bitworld's `claude.nim`).
  `guidance.nim` runs a worker thread with three channels:
  snapshot→worker, directive→main, meeting-action→main.
  `bot.nim` submits snapshots periodically (every
  `GuidancePeriodTicks`) and on wake triggers (body seen, meeting
  started, reflex fired, directive expiring); reads directives
  non-blocking; handles TTL expiry. `modes/meeting.nim` pops LLM
  `MeetingAction` values from a queue (speak, vote, confirm_vote,
  unvote, wait) with a safety-net fallback that forces SKIP when
  the meeting timer nears expiry. `prompts.nim` holds system
  prompts for gameplay directives and meeting actions. Bot degrades
  gracefully with no API key or LLM failures — scripted defaults
  keep it playing. `nim.cfg` added for curly/jsony/libcurl package
  paths. All 7 test suites pass; library + CLI builds green.
- **guided_bot phase 4 complete.** Structured trace writer in
  `trace.nim` emits 7 JSONL streams + `manifest.json` + optional
  `frames.bin` per DESIGN.md §11. Opt-in via `GUIDED_BOT_TRACE_DIR`
  + `GUIDED_BOT_TRACE_LEVEL` env vars. When off, every `log*` call
  is a nil-check early return. Worker-thread trace events use a
  `Channel[string]` (pre-serialized JSON) drained by the main thread
  — no GC-safety issues. Call sites wired: `logDecision` in
  `decideNextMask`, `logModeEntered`/`logModeExited` in `switchMode`,
  `logReflexFired` in `reconcileDirective`, `logGameEvent` for
  body_seen/meeting_started/role_revealed/chat_observed/game_over
  (edge-detected in `decideNextMask`), `logGuidanceEvent` drained
  from `guidance.nim`'s `traceEventChan`, `logSnapshot` periodic at
  240 ticks, `logFrame` at `TraceFull`. `closeTrace` called from
  `destroyBot`. All 7 test suites pass; library + CLI builds green.

- **guided_bot phase 5 complete.** Fallback-only playability test and
  submission preparation. Key changes: (a) stale-default re-evaluation
  in `bot.nim:reconcileDirective` — when the bot is in ModeIdle on a
  default directive and the role is now known, it transitions to the
  appropriate gameplay mode (task_completing / hunting) immediately.
  This is the mechanism that passes the cogames 10-step validation
  gate. (b) A\* node limit (30K) in `action.nim:findPath` to prevent
  unbounded search on unreachable goals. (c) Fixture-replay fallback
  test (`test/fallback_test.nim`) — 8th test suite proving non-NOOP
  within 10 frames, mode transitions, no crash, no LLM directive
  leakage. (d) Docker-compatible `mettagrid.bitworld` import fallback
  in `amongthem_policy.py`. (e) `**kwargs` in policy `__init__` for
  script compatibility. All 8 test suites pass; library build green.
  **Blocker found:** spiral localization takes ~11s/frame on
  pre-game/lobby frames that don't match the map, reducing live-play
  throughput to ~2 fps (100% noop). Needs a spiral radius cap.
  **Season blocker:** `among-them` appears in `cogames season list`
  but returns 404 on API access.

- **guided_bot action-table fix + idle wander (2026-05-01).**
  `ffi/lib.nim:TrainableMasks` had 22/27 entries in wrong order
  (direction-first vs the canonical direction+modifier grouping in
  `mettagrid.bitworld.BITWORLD_ACTION_MASKS`). Every directional action
  the Nim bot produced was garbled when sent to the server. Fixed by
  reordering the table; added a compile-time assertion (`CanonicalMasks`
  + `static:` block) and a Python-side unit test
  (`test/test_action_table.py`) to prevent future drift. Also added
  `DisciplineWander` (raw direction buttons without A\*/localization)
  and rewired `ModeIdle` to emit movement on non-interstitial frames.

- **guided_bot orbit bug fix + trace enhancements (2026-05-01).**
  The A\* path-following logic had a compound bug that caused the bot
  to orbit in a ±5 px area indefinitely instead of reaching its goal.
  `PathLookahead=18` selected a waypoint 18 single-pixel A\* steps
  ahead; combined with ~2 px camera-localization jitter, the path
  trimming (drop steps within Manhattan distance ≤ 2) consumed steps
  unpredictably, placing the waypoint past corridor turns or behind
  walls. `steerButtons` then aimed straight at the off-axis waypoint,
  hit walls, and reversed — creating a stable orbit.
  **Fix (action.nim):** (a) `PathLookahead` reduced from 18 to 4 so
  the waypoint stays tightly on the A\* corridor through turns.
  (b) Periodic path recomputation every `ReplanIntervalTicks=24`
  (~1 s) so camera-noise drift in the path trimming self-corrects.
  (c) Stall detector: if Manhattan distance to goal hasn't decreased
  in `StallProgressTicks=48` (~2 s), force a replan.
  **Trace enhancement (trace.nim, bot.nim):** `logDecision` now
  includes the final button mask (`mask`), self position
  (`self_x`, `self_y`), and `localized` flag. The log call was moved
  to after `applyIntent` so the mask is available.
  **Result:** 30 s local match with seed 42 — bot navigates from
  spawn (564, 120) to task station (631, 60) in ~137 ticks. With
  phase 6.1's hold lifecycle, the bot now completes the task and
  moves to the next station (2-5 tasks per match). Previously the
  bot orbited at (574, 85) for the entire game.

- **guided_bot phase 6.1–6.4 (mode completeness, 2026-05-04).**
  Phase 6.1: `task_completing` hold lifecycle — 3-phase state machine
  (Navigate/Hold/Confirm), belief-layer task state with icon-miss
  counting and radar-dot checkout latching, tiered target selection,
  trace events. Bot completes 2-5 tasks per 30s match (was 0).
  Phase 6.2: `reporting` give-up — body-visibility check, approach
  timeout, in-range timeout.
  Phase 6.3: `meeting` cursor navigation + timer fix — position-aware
  shortest-path ring navigation, timer corrected from 1200→600 ticks,
  auto-vote SKIP after 360 ticks with no LLM action. Chat deferred.
  Phase 6.4: `hunting` cover patrol + kill confirmation — station-to-
  station rotation, 2s target memory, body+cooldown kill confirmation,
  KillStrikeRange 16→20.
  All 8 test suites pass; library builds green. Crewmate task
  completing live-verified. Imposter/meeting/reporting verification
  blocked on per-agent trace infrastructure (see IMPL_PLAN.md).

### Next

- **guided_bot phase 6 (mode completeness) in progress.** Phases
  6.1–6.4 complete: task-completion lifecycle, reporting give-up,
  meeting cursor/timer, hunting patrol + kill confirmation. See
  `guided_bot/IMPL_PLAN.md` for the full roadmap.
  Remaining: 6.5 (pretending fake A-press), 6.6 (fleeing cleanup),
  6.7 (reflex scope widening), then phase 7 (stub modes).
- **Live-verification infrastructure.** `play_local.py` and all
  server-starting scripts now support `--force-role {crewmate,imposter}`
  to pin the policy agent's role via the server's native `"slots"`
  config. The trace writer uses a per-instance monotonic counter in
  the session ID, so multiple writers in the same process (e.g.
  `play_match.py`) no longer collide. Remaining gap: `play_match.py`
  still constructs each policy with `num_agents=1`, so all writers
  use `agent_0/` — traces are now in separate session dirs but the
  agent index is always 0. Consider passing a unique agent label for
  clearer multi-agent trace navigation.
- **Meeting mode partially verified.** Cursor navigation and timer
  fix are structurally correct (compiles, tests pass) but no
  meetings have occurred in any local match to exercise the code.
  Next step: run `--force-role imposter` to generate kills and
  trigger meetings.
- **Chat emission deferred.** Requires Nim buffer → C FFI export →
  Python `bitworld_chat_messages()` pipeline. See
  `guided_bot/MEETING_DESIGN.md` §1.4.
- **Submission attempt** once a live Among Them season is accessible.
  The bot passes the 10-step validation gate. Season blocker:
  `among-them` returned 404 on API access as of 2026-05-01.
- ~~**Known modulabot bug:**~~ **Fixed.** modulabot previously pressed
  B for body reports (`crewmate.py:104`) but the server uses A
  (`sim.nim:2284`). Both crewmate and imposter self-report paths now
  correctly use `press_a_while`. The misleading docstring in
  `actions.py` has also been corrected.
- **Known gaps** (carried forward):
  - **HUD task-list parsing not done.** Would replace the
    radar-dot inference path with ground-truth assignment reads.
  - **Walking-pose crewmate recall** is still lower than the
    Nim bot's; try loosening the stable/body-pixel floors in
    `sprite_match.CREWMATE_MIN_*`.
  - `update_role` occasionally mis-fires IMPOSTER on crewmate
    frames (kill-button shaded match is loose).

## How to get unstuck

- `cogames docs` — the CLI ships its own documentation, usually fresher
  than any external doc.
- `cogames tutorial make-policy --amongthem -o policy.py` (or `--scripted`,
  `--trainable`) — generates a current starter template. Use the generated
  template as the source of truth for policy class contracts.
- `~/coding/metta/packages/cogames/` — the cogames source. Read
  `cli/submit.py` for the exact validation rules. Read `MISSION.md` in
  that package for the in-universe CvC briefing.
- `~/coding/metta/cogames-agents/` — Softmax's own scripted agents. Good
  prior art for registries, Nim integration, and teacher policies.
- `~/coding/bitworld/among_them/players/` — canonical Among Them bots,
  including the hybrid Nim + Python LLM sidecar pattern.
- Discord: `https://discord.gg/secret-hologenesis` (Softmax community).

## Ground truth

- **The code wins.** If an agent beats the leaderboard, its strategy is
  correct for that season, regardless of what this file says.
- **The CLI wins.** If this doc and `cogames --help` disagree, the CLI is
  right. Fix this doc.
- **Leaderboard wins.** Pretty strategies that don't score are folklore.
  The metric is the ranking.
