# guided_bot / cogames submission

Entry point for the cogames tournament: `amongthem_policy.AmongThemPolicy`.

## Quick flow

```sh
# Dry-run (no secrets needed; runs on defaults)
SEASON=<active-season> ./ship.sh dry-run

# Ship with LLM enabled
ANTHROPIC_API_KEY=sk-ant-... SEASON=<active-season> \
    POLICY_NAME=$USER-guided-bot ./ship.sh ship
```

`ship.sh` runs from the `personal_cogs/` repo root so the `-f` includes
resolve correctly.

## What gets bundled

- `amongthem_policy.py` — the `AmongThemPolicy` class ctypes-loads
  `libguidedbot.{dylib,so,dll}` and routes `step_batch` through it.
- `among_them/guided_bot/` — full Nim source tree + `build_guided_bot.py`.
  The tournament image has Nim 2.2.4 + nimby pre-installed; the build
  helper compiles `libguidedbot` inside the worker on first use.

## Secrets

The LLM is an expected-present component (DESIGN.md §1 goal 5).
`ship.sh` reads `ANTHROPIC_API_KEY` from the environment and forwards
it as `--secret-env` to the cogames upload. If the key is missing, the
policy still loads and plays on defaults (see DESIGN.md §9) — useful
for dry-runs and for degraded operation if an API outage hits
mid-match.

See `metta/packages/cogames/POLICY_SECRETS.md` for how the key reaches
the policy subprocess at match time.

## Phase 0 status

This directory exists but should not be used for a real tournament
submission yet. The Nim side of the bot returns no-op for every
action. The CoGames dry-run will therefore fail the 10-step validation
gate with "Policy took no actions (all no-ops)" — which, per
`COGAMES.md` § validation gate, is the one documented case where
`--skip-validation` is appropriate (see `ship-skip-validation` in
`ship.sh`). But there's no point in shipping an empty bot; wait until
phase 1+ before using these scripts for anything other than smoke
tests.
