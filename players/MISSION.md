# MISSION

> **Living document.** Expect drift. Re-read this file at the start of every
> session. Update it whenever the mission, scope, or working practices change.
> If you're touching strategy, directory layout, or submission workflow, touch
> this file too. Stale missions are worse than no mission.
>
> Last reviewed: 2026-04-30

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
- If two agents share substantial code, extract it to a `<game>/common/` or
  `<game>/<family>/` subdir. Don't copy-paste identical Nim sources.
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

**As of 2026-04-30:**

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
  ~8.6 ms. 211 tests pass (15 parity-pinned between Nim and
  numpy); visual debug overlay at `scripts/debug_overlay.py`;
  benchmark harness at `scripts/bench_perception.py`. Remaining
  known gap: walking-pose crewmate recall is lower than Nim's.
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
- **Perception moved to Nim via ctypes** (this session). The hot
  pixel kernels (sprite matching, camera scoring, patch hashing,
  bulk patch-vote lookup, task-icon scanning, OCR glyph picks)
  now run as native code in `modulabot/nim_perception/`, dispatched
  through numpy fallbacks so `MODULABOT_DISABLE_NATIVE=1` still
  works. End-to-end `BotCore.step` gameplay p50: 9.0 ms → 2.6 ms
  (3.4×); cold localize 4.7 ms → 0.9 ms (5.2×); voting-chat OCR
  24.9 ms → 8.6 ms (2.9×). 211 tests pass, 15 of them parity-pins
  between Nim and numpy across the 275-frame fixture. See
  `modulabot/PERCEPTION_PERF_PLAN.md` for the phase-by-phase plan
  and results.

### Next

1. **Submission attempt** once a live season comes back. Dry-run
   the cogames ship command, confirm validation gate passes
   without `--skip-validation` (patrol fallback should emit a
   non-NOOP action on the first gameplay frame).
2. **Post-submission iteration** — stand up the trace-based outer
   loop (feed `events.jsonl` + `decisions.jsonl` into an LLM
   harness), start A/B'ing tuning constants, gather real-meeting
   captures to replace the synthetic voting frames in
   `test_voting.py` / `test_pixel_pipeline.py`.
3. **Known perception gaps**:
   - Walking-pose crewmate recall is still lower than the Nim bot's;
     try loosening the stable/body-pixel floors in
     `sprite_match.CREWMATE_MIN_*`.
   - `update_role` occasionally mis-fires IMPOSTER on crewmate
     frames (kill-button shaded match is loose). Tighter match
     budget or requiring the IMPS reveal would fix it.
   - Task-icon → task-index matching in
     `pixel_pipeline._populate_tasks_from_camera` uses a simple
     screen-distance check; under occlusion this may mis-attribute
     icons. Compare against the Nim `tasks.nim` approach if the
     task-pick policy starts getting confused.

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
