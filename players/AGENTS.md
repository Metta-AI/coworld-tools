# AGENTS.md

Workshop repo for Softmax [Alignment League Benchmark](https://www.softmax.com/alignmentleague)
agents. See `MISSION.md` for goals and `COGAMES.md` for the cogames framework
primer. **Both are living documents — re-read them at the start of every
session and update them when you notice drift.**

## Read first

In order:

1. `MISSION.md` — what we're doing, repo conventions, current focus.
2. `COGAMES.md` — cogames CLI workflow, season list, submission patterns,
   the 10-step validation gate.
3. `COGAMES_CLI.md` — full `cogames` CLI reference (regenerate when the CLI
   version changes).
4. The game-level `README.md` (e.g. `among_them/README.md`) and the agent-
   level `README.md` for whatever you're touching.

These files are the source of truth for workflow. This file only covers
things an agent needs before it can usefully read them.

## Layout

```
<game>/           # one directory per game (among_them/, cogs_vs_clips/, ...)
  README.md       # game-level conventions, binaries, local-run harness
  <agent>/        # one directory per agent; submission bundle root
    README.md     # strategy, status, leaderboard score, TODO
  scripts/        # per-game harnesses (play_local.py, debug_overlay.py, ...)
  tools/          # one-off helpers (asset dumpers, etc.)
```

Conventions (from `MISSION.md`):

- One agent per subdirectory. The agent dir is the `cogames ship -f`
  bundle root — everything the policy imports must live inside it.
- Shared code goes in `<game>/common/` **only once it exists**; don't
  speculatively build shared infra.
- Never commit built `.so` / `.dylib` / `.dll`. Platform-specific, rebuilt
  on demand.

## Environment

- Python **3.12**, isolated venv at `./.venv` with cogames + mettagrid +
  bitworld already installed. Activate, don't reinstall:
  `source .venv/bin/activate`.
- There is **no** `pyproject.toml`, `Makefile`, `pytest.ini`, or lockfile
  at the repo root. Don't add one without asking — this repo intentionally
  treats each agent dir as self-contained.
- Nim binaries for local Among Them runs are expected at
  `~/coding/bitworld/out/` (server `among_them`, filler bot `nottoodumb`).
  Override with `AMONG_THEM_BINARY=/path/to/binary`.
- Canonical prior art lives outside this repo — cite, don't copy unless
  needed:
  - `~/coding/bitworld/among_them/players/` — Nim bots, `modulabot/DESIGN.md`,
    `how_to_submit_to_cogames.md`, `how_to_make_a_bot.md`.
  - `~/coding/metta/packages/cogames/` — cogames package source.
  - `~/coding/metta/cogames-agents/` — Softmax's scripted baselines.

## Running things

All commands assume the repo root as cwd unless noted.

```bash
# Tests for modulabot (237 tests, ~18s, must be green)
PYTHONPATH=among_them .venv/bin/python -m unittest discover \
    -s among_them/modulabot/tests

# Run a single test module
PYTHONPATH=among_them .venv/bin/python -m unittest \
    among_them.modulabot.tests.test_voting -v

# Local Among Them episode against a real Nim server + nottoodumb fillers
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    --duration 20

# Same, but force imposter role for testing imposter-specific behavior
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    --duration 20 --force-role imposter --trace-dir /tmp/trace

# Connect to an existing server (replaces old play_live.py)
PYTHONPATH=among_them .venv/bin/python among_them/scripts/connect.py \
    --host 127.0.0.1 --port 2000

# All-agent match (replaces old play_eight.sh)
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_match.py

# Debug overlay window (replaces old play_debug.sh)
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_debug.py

# Visual debug overlay (renders perception output over raw frames)
PYTHONPATH=among_them .venv/bin/python among_them/scripts/debug_overlay.py \
    /tmp/mb_frames.npy --frame 150 --save /tmp/overlay.png

# Capture frames for offline analysis (replaces old capture_frames.py)
PYTHONPATH=among_them .venv/bin/python among_them/scripts/capture.py \
    --duration 20 --output /tmp/frames.npy
```

All play/connect scripts accept `-p modulabot.policy.AmongThemPolicy`
(default) to select the policy and `--policy-kwarg KEY=VALUE` for
constructor kwargs. Use `--help` on any script for the full flag list.

`cogames play` does **not** support Among Them — use `scripts/play_local.py`.
`cogames` commands that bundle policies (`ship`, `create-bundle`, `upload`)
must be run from the repo root so `-f <agent_dir>` resolves correctly.

## Among Them specifics (easy to miss)

- **Tournament observation is pixels only**: `(4, 128, 128) uint8
  kind=pixels` with the PICO-8 palette. The `STATE_FEATURES` structured-
  state layout exists **only** in the training harness, not in
  `BitWorldRunner`. Any serious bot needs its own localization, sprite
  matching, task recognition, and voting-screen parsing. See
  `among_them/modulabot/README.md` § "Reality check" and § "Perception
  status".
- **10-step validation gate**: `--skip-validation` is only appropriate for
  the exact "Policy took no actions (all no-ops)" failure. Any other
  dry-run error (Nim build, import, ABI mismatch, traceback) means fix
  the bug. Decision tree in `COGAMES.md`.
- **Modulabot trace writer** is opt-in and non-perturbing. Enable via
  `MODULABOT_TRACE_DIR=/tmp/modulabot_runs`
  `MODULABOT_TRACE_LEVEL=decisions` — see `among_them/modulabot/README.md`
  § "Tracing".

## Workflow expectations

- **Don't commit unless asked** (global rule; reiterated because this repo
  has no CI to catch regressions for you — tests are on you).
- **Append a submission log row** to the agent's `README.md` after every
  `cogames upload` / `ship`: date, policy name, season, dry-run result,
  leaderboard score. This is the only cross-session memory.
- **Update `MISSION.md` § Current focus** when priorities shift or you
  finish something big. Update `COGAMES.md` when the CLI drifts.
- **Trust live `cogames --help`** over any doc in this repo — and fix the
  doc when they disagree.
- **Ask before diverging from design documents.** When implementing a
  feature that has a design spec (e.g. `DESIGN.md`), follow the spec.
  If you encounter a case where the implementation should differ from
  the design in a non-trivial way — different data flow, dropped
  features, changed defaults that affect behavior, structural
  reorganization — **stop and ask** before coding the divergence.
  Trivial differences (naming conventions, internal helper structure)
  don't need approval. When in doubt, ask. After an approved
  divergence, update the design doc in the same change so it stays
  accurate.
- **Always validate with a live game after implementation.** After unit
  tests pass, run a live local match with tracing enabled and read the
  trace output to confirm the feature works end-to-end. Live games are
  the ultimate test. If the feature can't be verified via traces, flag
  that during planning and make sure the plan includes adding the
  necessary tracing first.

---

## Standard live test

A "standard live test" is the canonical end-to-end validation run for
Among Them agents. It exercises the full pipeline (perception →
belief → navigation → mode decision → action) under realistic
tournament conditions.

### Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Players | 8 | Tournament lobby size |
| Imposters | 2 | Tournament default |
| Kill cooldown | 1200 ticks (~50s) | Realistic; forces cover/patrol behavior between kills |
| Vote timer | 600 ticks (~25s) | Tournament default |
| Duration | 180s (3 min) | Long enough for multiple kill/meeting cycles |
| Seed | 42 (default) | Reproducible; known to produce both roles |
| Agents | All 8 slots filled by the policy under test | No filler bots; tests agent-vs-agent interaction |
| Trace level | `decisions` | Per-frame mode/mask/position + events + reflexes |

### Command

```sh
PYTHONPATH=among_them \
.venv/bin/python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --num-agents 8 \
    --duration 180 \
    --seed 42 \
    --trace-dir among_them/guided_bot/traces \
    --trace-level decisions
```

### What to check in traces

After the match, each bot's trace lives in
`<trace_dir>/bot_N/<session>/`. Evaluate:

1. **Manifest finalized.** All `manifest.json` show `"closed": true`
   with a non-zero `end_tick` and a detected `role`.
2. **Role detection.** Every bot's manifest has `role` set to
   `"crewmate"` or `"imposter"` (not `"unknown"`). Should happen by
   t≈30-160 (interstitial OCR).
3. **Mode transitions.** `modes.jsonl` shows the bot left `idle` and
   entered a gameplay mode (`task_completing` for crew, `hunting` for
   imposter) shortly after role detection.
4. **Crewmate productivity.** Crewmate bots should complete ≥1 task
   per 3-minute match. Check `events.jsonl` for `task_completed`
   entries. Current baseline: 1-3 tasks per crewmate.
5. **Imposter agency.** Imposter bots should attempt kills
   (`kill_attempted` events), enter `fleeing` after body sightings
   (reflex fires), and cycle through `hunting`→`fleeing`→`hunting`.
6. **Localization.** `decisions.jsonl` should show `localized: true`
   within 200 ticks of game start. Sustained localization loss
   (>100 consecutive `localized: false` frames during gameplay)
   indicates a perception bug.
7. **Noop ratio.** Total `mask=0` frames should be <60% for crewmates,
   <80% for imposters. Higher indicates stuck/idle behavior.
8. **Meeting participation.** If bodies are reported and meetings
   occur, bots should have `meeting_started` events and enter
   `meeting` mode. (Known gap: meeting detection sometimes fails —
   see TODO.md.)
9. **Reflex firings.** Crewmates seeing bodies should trigger
   `body_newly_in_view_report`; imposters should trigger
   `body_newly_in_view_flee`. Check `reflexes.jsonl`.
10. **No crashes.** All 8 agents ran for the full duration (compare
    `end_tick` across bots — should be within ~40 ticks of each other,
    reflecting only connection-order stagger).

### Quick summary script

```sh
for i in $(seq 0 7); do
  session=$(ls among_them/guided_bot/traces/bot_$i/ | head -1)
  dir="among_them/guided_bot/traces/bot_$i/$session"
  python3 -c "
import json
m = json.load(open('$dir/manifest.json'))
print(f'Bot $i [{m.get(\"role\",\"?\")}] end_tick={m.get(\"end_tick\",0)}')
"
done
```

---

## Small live test

A quick-turnaround match for iterating on a single feature or
debugging. Fewer agents = faster startup, shorter logs, easier to
visually observe via the spectator WebSocket.

### Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Players | 4 | Small lobby; fast iteration |
| Imposters | 1 | Minimum for kill/meeting dynamics |
| Kill cooldown | 1200 ticks (~50s) | Same as tournament |
| Vote timer | 600 ticks (~25s) | Same as tournament |
| Duration | 180s (3 min) | Long enough for at least one kill cycle |
| Port | 2000 | Convention for local dev |
| Seed | 42 (default) | Reproducible |
| Agents | All 4 slots filled by the policy under test | No filler bots |
| Trace level | `decisions` | Per-frame mode/mask/position + events + reflexes |

### Command

```sh
PYTHONPATH=among_them \
.venv/bin/python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --num-agents 4 \
    --num-players 4 \
    --imposter-count 1 \
    --port 2000 \
    --duration 180 \
    --seed 42 \
    --trace-dir among_them/guided_bot/traces \
    --trace-level decisions
```

### Quick summary script

```sh
for i in $(seq 0 3); do
  session=$(ls among_them/guided_bot/traces/bot_$i/ | head -1)
  dir="among_them/guided_bot/traces/bot_$i/$session"
  python3 -c "
import json
m = json.load(open('$dir/manifest.json'))
print(f'Bot $i [{m.get(\"role\",\"?\")}] end_tick={m.get(\"end_tick\",0)}')
"
done
```

---

## Temporary verification notes

> Remove each item once its condition is resolved.

(None pending.)
