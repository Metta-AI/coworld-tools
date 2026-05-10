# MISSION

> **Living document.** Expect drift. Re-read this file at the start of every
> session. Update it whenever the mission, scope, or working practices change.
> If you're touching strategy, directory layout, or submission workflow, touch
> this file too. Stale missions are worse than no mission.
>
> Last reviewed: 2026-05-10

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
- If two active agents share substantial code, extract it to a
  `<game>/common/` subdirectory and have each agent import from there.
  Don't reach into one agent's tree from another. Don't speculatively grow
  `common/` either — the bar is at least two real active consumers or a
  clearly documented migration need.
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

**As of 2026-05-10:**

- **Current active Among Them agent:** `among_them/guided_bot/`.
  Use guided_bot for development, tests, local matches, traces, and
  submissions unless James explicitly asks for a different agent.
- **Local modulabot is fully deprecated.** `among_them/modulabot/`
  remains only as historical/reference material. Do not inspect,
  modify, test, benchmark, ship, or otherwise work on it unless James
  explicitly asks for modulabot work in the current prompt.
- **Among Them observation path is pixels-only.** The tournament path
  provides `(4, 128, 128) uint8 kind=pixels`; guided_bot therefore owns
  localization, sprite matching, task recognition, self-colour
  identification, game-over classification, and voting-screen parsing.
- **guided_bot phase 0–6 core behavior is implemented.** The current
  bot has the full Nim perception pipeline, hierarchical waypoint
  navigation, six complete mode handlers (`task_completing`, `hunting`,
  `pretending`, `reporting`, `fleeing`, `meeting`), the four-reflex
  system, LLM guidance infrastructure, and structured tracing with
  optional `frames.bin` capture.
- **Self-colour identification is implemented.** Actor scanning probes
  the centered player sprite at game start and latches the learned
  colour for the round; voting parse can also teach the self slot/colour
  when actor scanning has not learned it yet.
- **Task lifecycle is tuned to server timing.** `TaskHoldTicks` is 74,
  `TaskConfirmWindowTicks` is 48, and `TaskIconMissCompleteTicks` is 4.
  Productivity summaries must stop at the first game-over event because
  a single live run can reset and continue after game-over.
- **Meeting/voting mechanics are live-verified.** Voting parse, phase
  detection, per-frame cursor updates, alive-slot merging, cursor
  pulse/release navigation, vote confirmation, and the self-vote guard
  work in live traces. The temporary no-LLM target votes for the next
  selectable live slot to the right so mechanics are testable.
- **Latest voting trace:** 8 guided_bot agents, 2 imposters, 600-tick
  kill cooldown, 600-tick vote timer, 16 tasks per crewmate, 90 seconds,
  seed 42, `--trace-level full`:
  `among_them/guided_bot/traces/voting_mechanics_20260510_8p2i_cd600_vote600_tasks16_livetarget_full`.
  Every living bot voted in meetings; the ghost did not.
- **Local live-test knobs exist.** Server-starting scripts support
  `--imposter-cooldown-ticks`, `--tasks-per-player`, and
  `--force-role {crewmate,imposter}` for focused live validation. Use
  `--trace-level full` when frame evidence is needed.

### Next

- **Vote strategy.** Replace the temporary "next selectable live slot to
  the right" target with evidence-based crew/imposter meeting policy.
  Imposters must never vote for themselves.
- **Chat emission.** `MeetingActSpeak` reaches `intent.chat`, but
  sending chat to the server still needs Nim buffer → C FFI export →
  Python WebSocket plumbing. See
  `among_them/guided_bot/MEETING_DESIGN.md`.
- **Imposter efficiency.** Baseline kill flow works, including repeated
  kills with shorter cooldowns, but seeking patrol, cover timing,
  killed-player memory, and partner coordination need strategy work.
  See `among_them/guided_bot/IMPOSTER_CRITIQUE.md` and `TODO.md`.
- **Ghost/body reflex cleanup.** Investigate the self-body flee loop and
  remaining ghost-state edge cases before optimizing imposter strategy.
- **Submission attempt** once a live Among Them season is accessible.
  Re-check `cogames season list` and `cogames season show` before any
  upload because season availability has changed before.

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
