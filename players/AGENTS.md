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
# Tests for modulabot (236 tests, ~16s, must be green)
PYTHONPATH=among_them .venv/bin/python -m unittest discover \
    -s among_them/modulabot/tests

# Run a single test module
PYTHONPATH=among_them .venv/bin/python -m unittest \
    among_them.modulabot.tests.test_voting -v

# Local Among Them episode against a real Nim server + nottoodumb fillers
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    --duration 20

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
