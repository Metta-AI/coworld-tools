# MISSION

> **Living document.** Expect drift. Re-read this file at the start of every
> session. Update it whenever the mission, scope, or working practices change.
> If you're touching strategy, directory layout, or submission workflow, touch
> this file too. Stale missions are worse than no mission.
>
> Last reviewed: 2026-05-01

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

**As of 2026-05-01:**

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

### Next

0. **Crewmate task-selection fix (Phases 0-4 + 6-7 complete, 2026-04-30
   to 2026-05-01).** Five-bug fix to the pixel-pipeline → crewmate
   flow: gated `arrow_visible` on radar match (Phase 1), gated
   `active` on assignment evidence (Phase 2), replaced the fake
   84-tick hold-completion timer with a server-confirmed
   hold→confirming state machine (Phase 3), batched minor cleanups
   (Phase 4), added icon-miss negative-evidence pruning so the bot
   learns which ~32 of 40 tasks aren't its (Phase 6), and flipped
   confirmation priority to icon-first to eliminate the ~22%
   sibling-completion false-positive rate that `task_progress` had
   (Phase 7). Plan + per-phase results at
   `among_them/modulabot/CREWMATE_TASK_FIX_PLAN.md`. Tests:
   **236/236 pass, 0 expected failures**. Comparison traces
   archived at `phase{0,1,2,3,7}_trace/`. Outstanding:
   half-implemented `TaskState` machine (filed as TODO in the plan).

1. **Submission attempt** once a live season comes back. Dry-run
   the cogames ship command, confirm validation gate passes
   without `--skip-validation`. The pixel pipeline emits
   non-NOOP actions on the first gameplay frame (task selection
   fires as soon as the localizer locks and any assignment
   evidence is visible).
2. **Post-submission iteration** — stand up the trace-based outer
   loop (feed `events.jsonl` + `decisions.jsonl` into an LLM
   harness), start A/B'ing tuning constants, gather real-meeting
   captures to replace the synthetic voting frames in
   `test_voting.py` / `test_pixel_pipeline.py`.
3. **Known gaps**:
   - **`TaskState` machine half-wired** in pixel mode (only
     `NOT_DOING` and `COMPLETED` populated; selection logic
     reads other flags directly). Filed as TODO in
     `among_them/modulabot/CREWMATE_TASK_FIX_PLAN.md § TaskState
     machine cleanup`. Doesn't affect correctness; cleanup
     estimated 1-2 hours.
   - **HUD task-list parsing not done.** Would replace the
     radar-dot inference path with ground-truth assignment
     reads. Filed as a follow-up in
     `among_them/modulabot/README.md § Future work`.
   - **Walking-pose crewmate recall** is still lower than the
     Nim bot's; try loosening the stable/body-pixel floors in
     `sprite_match.CREWMATE_MIN_*`.
   - `update_role` occasionally mis-fires IMPOSTER on crewmate
     frames (kill-button shaded match is loose). Tighter match
     budget or requiring the IMPS reveal would fix it.

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
