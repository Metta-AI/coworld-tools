# MISSION

> **Living document.** Expect drift. Re-read this file at the start of every
> session. Update it whenever the mission, scope, or working practices change.
> If you're touching strategy, directory layout, or submission workflow, touch
> this file too. Stale missions are worse than no mission.
>
> Last reviewed: 2026-05-13

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

1. **Ship a working submission** to the active league/season for each game we
   care about. "Working" means: passes the relevant validation or smoke test,
   gets picked up by the tournament runner, and plays real matches without
   crashing. Among Them Daily now uses the v2 Coworld league flow; legacy
   `cogames` seasons are a separate surface.
2. **Win.** Climb the leaderboard. Beat the `starter` / `baseline` policies,
   then beat the top human/team submissions.
3. **Self-improve.** Where feasible, let agents learn across games — memory
   dumps, post-game analysis, cross-game priors in system prompts, offline
   training on episode replays.
4. **Stay honest about what works.** Keep a running log per agent of what
   beat what, what got ejected, and what regressed. No cargo-culting.

## Non-goals (for now)

- Not building the cogames/Coworld framework itself - that's Softmax's job, in
  `~/coding/metta/packages/cogames` and `~/coding/metta/packages/coworld`.
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
│       ├── cogames/        # legacy bundle submission wrapper, when used
│       └── coworld/        # Docker-image external-player submission wrapper
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
  have changed. For current Among Them, trust `uv run coworld --help`,
  `uv run coworld leagues`, and the latest `play_amongthem.md` over stale
  legacy `cogames` docs. **Update these files when you notice drift.**
- **Record submission results.** Every time you upload a policy, append a
  row to the agent's `README.md`: date, policy name, season, dry-run result,
  leaderboard score (fill in later). This is our only memory across
  sessions.
- **Dump game memory** where possible. For LLM-driven agents, save per-game
  episodic/strategic memory to JSON so we can synthesize learnings into
  future system prompts. (Pattern from `SMART_BOT_GUIDE.md`.)
- **Prefer current game-specific instructions and verify them live.** For
  Among Them, `https://softmax.com/play_amongthem.md` is the current public
  submission guide. The current Metta source guide uses `uv run coworld`,
  `Among Them Daily`, and Observatory v2; `cogames season list` is legacy
  and must not be used to decide Daily league status. Still verify commands
  with the live CLI/API, and record any guide/package drift in the relevant
  docs.

### Before shipping

- Validate every submission before spending a slot. For legacy bundle flows,
  dry-run with `ship.sh dry-run` or `cogames upload --dry-run`; for current
  Among Them Coworld submissions, build linux/amd64 with Docker, smoke-run
  `/bin/guided_bot --help`, and prefer `uv run coworld run-episode` against
  the downloaded `among_them` Coworld manifest when it is practical.
- Only use `--skip-validation` for the known "Policy took no actions (all
  no-ops)" failure mode on perception-based bots that need >10 frames to
  localize. Never use it to route around real bugs. See
  `COGAMES.md` § validation gate for the decision tree.
- Ship to the correct league/season. For current Among Them, verify
  `Among Them Daily` with `uv run coworld leagues` and submit through
  Coworld v2. For legacy bundle seasons, verify with
  `cogames season show <name>`. Limited-submission competitions should not
  get untested builds.

### When adding a new agent

1. Create `<game>/<agent>/` with a `README.md` stub: strategy, status, TODO.
2. Copy the closest working agent as a template; rename every identifier.
3. Get `cogames play` or the local equivalent working end-to-end *before*
   touching submission packaging.
4. Then add the relevant submission wrapper: `cogames/` for legacy Python
   bundles, or a Docker-image external-player path for current Among Them.
   See `COGAMES.md` § submission patterns.
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

**As of 2026-05-13:**

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
  work in live traces. The fallback vote target now uses role-aware
  evidence/alibi strategy: crew require suspicion evidence or SKIP,
  imposters avoid self/known teammates and blend into accusations.
- **Meeting chat plumbing is implemented.** `MeetingActSpeak` queues
  sanitized chat through the Nim action buffer, `guidedbot_take_chat`
  FFI export, Python `bitworld_chat_messages(agent_ids)` hook, and
  local `pack_chat_packet` runner path. The LLM client now prefers AWS
  Bedrock credentials (`CLAUDE_CODE_USE_BEDROCK=1` locally,
  `coworld upload-policy --use-bedrock` / `USE_BEDROCK=true` in Coworld
  v2) and falls back to direct Anthropic only when configured. Bedrock
  smoke and short live meeting validation are verified; prompt quality
  still needs tuning from longer traces.
- **Latest voting trace:** 8 guided_bot agents, 2 imposters, 600-tick
  kill cooldown, 600-tick vote timer, 16 tasks per crewmate, 90 seconds,
  seed 42, `--trace-level full`:
  `among_them/guided_bot/traces/voting_mechanics_20260510_8p2i_cd600_vote600_tasks16_livetarget_full`.
  Every living bot voted in meetings; the ghost did not.
- **Latest Bedrock meeting trace:** 8 guided_bot agents, 2 imposters,
  standard 1200-tick kill cooldown, 8 tasks per crewmate, 180 seconds,
  seed 42, `--trace-level decisions`:
  `among_them/guided_bot/traces/meeting_bedrock_20260511_8p2i_standard`.
  All manifests closed; roles detected; two meetings per bot; 358
  successful LLM responses, 89 meeting actions, 6 chat lines, 12 vote
  attempts, and zero LLM failures.
- **Current Among Them public route is Coworld v2.** The current
  `play_amongthem.md` guide says to use a Metta checkout, `uv run coworld
  download among_them`, `uv run coworld run-episode`, `uv run coworld
  upload-policy`, and the **Among Them Daily** Observatory v2 league. Do
  not use `cogames season list` or `cogames submit` to evaluate or enter
  Among Them Daily.
- **2026-05-12 public upload used the wrong tournament surface.**
  `jamesboggs-guided-bot-public-20260512-152010:v1` was uploaded with
  image `img_c95d02c7-56ee-40a9-977f-b9d01a215de0` and policy id
  `de944167-b1ac-40d7-88ea-8c5495896795`, then submitted to the legacy
  `among-them`/`competition` surface. Coworld v2 shows no Among Them Daily
  submission for that policy version.
- **Prior Among Them Daily Coworld submission is placed.** Fresh linux/amd64
  Docker image `jamesboggs-guided-bot-coworld-20260511-142920:v1` was
  uploaded via the `crane` workaround after Docker 29 hit the ECR
  `HEAD` 403 path, then submitted to Among Them Daily as
  `sub_3cc0fa25-c436-4b46-a4a3-f2b1a06ebad1` and placed as
  `lpm_ed695228-4241-4c28-b16c-c9372462b133`. Do not reuse the older
  `20260511-120701` Coworld image tags; smoke checks found they lacked
  `/bin/guided_bot`.
- **Latest Among Them Daily Coworld submission is placed.**
  `jamesboggs-guided-bot-coworld-20260513-095131:v1` built and smoke-tested
  locally, including `coworld run-episode` against `among_them:0.1.11`.
  Standard `coworld upload-policy` again hit Docker 29's ECR manifest
  `HEAD` 403 path; the image was completed with the `crane` workaround as
  `img_b386faae-79ef-4f9e-81d9-32787588c736` with digest
  `sha256:4fd6d88da39c74186fc8a0d5aef954b32eceeeb5eda1b98a4ffa20d907b16c54`.
  Policy version id is `cdac788e-8ae0-4b07-81ca-8bd45a84ebad`; submission
  `sub_9414c5e8-1e44-461b-a497-51b59cfa32d5` is placed as active champion
  membership `lpm_290240c5-2eea-4648-b479-d428a22e43d2` in Daily division
  `div_334593c6-da90-4651-98c7-606573ea1474`.
- **Local live-test knobs exist.** Server-starting scripts support
  `--imposter-cooldown-ticks`, `--tasks-per-player`, and
  `--force-role {crewmate,imposter}` for focused live validation. Use
  `--trace-level full` when frame evidence is needed.

### Next

- **Monitor latest Coworld v2 rounds and results.** Poll `uv run coworld
  rounds --division div_334593c6-da90-4651-98c7-606573ea1474 --limit 10
  --json` and `uv run coworld results
  div_334593c6-da90-4651-98c7-606573ea1474 --json` after the next scheduled
  Among Them Daily round includes the new policy version.
- **LLM meeting tuning.** Tune the Bedrock meeting prompt/cadence from
  full-run `guidance.jsonl` and `events.jsonl`; current validation
  shows `meeting_action_received`, `chat_sent`, and `vote_attempted`
  sequencing before fallback, but chat quality and target rationale need
  review.
- **Imposter efficiency.** Baseline kill flow works, including repeated
  kills with shorter cooldowns, but seeking patrol, cover timing,
  killed-player memory, and partner coordination need strategy work.
  See `among_them/guided_bot/IMPOSTER_CRITIQUE.md` and `TODO.md`.
- **Ghost/body reflex cleanup.** Investigate the self-body flee loop and
  remaining ghost-state edge cases before optimizing imposter strategy.

## How to get unstuck

- `uv run coworld --help`, `uv run coworld leagues`, and
  `uv run coworld submissions` from `~/coding/metta` - current Among Them
  Daily v2 operations.
- `cogames docs` — the legacy CLI ships its own documentation, usually fresher
  than any external doc.
- `cogames tutorial make-policy --amongthem -o policy.py` (or `--scripted`,
  `--trainable`) — generates a current starter template. Use the generated
  template as the source of truth for policy class contracts.
- `~/coding/metta/packages/cogames/` — the cogames source. Read
  `cli/submit.py` for the exact validation rules. Read `MISSION.md` in
  that package for the in-universe CvC briefing.
- `~/coding/metta/packages/coworld/` - the Coworld v2 CLI/source used by
  Among Them Daily Docker-image uploads, league submission, episodes, logs,
  and standings.
- `~/coding/metta/cogames-agents/` — Softmax's own scripted agents. Good
  prior art for registries, Nim integration, and teacher policies.
- `~/coding/bitworld/among_them/players/` — canonical Among Them bots,
  including the hybrid Nim + Python LLM sidecar pattern.
- Discord: `https://discord.gg/secret-hologenesis` (Softmax community).

## Ground truth

- **The code wins.** If an agent beats the leaderboard, its strategy is
  correct for that season, regardless of what this file says.
- **The CLI wins.** If this doc and live `coworld --help` / `cogames --help`
  disagree, the live CLI for the relevant tournament surface is right. Fix
  this doc.
- **Leaderboard wins.** Pretty strategies that don't score are folklore.
  The metric is the ranking.
