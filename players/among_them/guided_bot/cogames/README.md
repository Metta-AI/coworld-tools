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

## Current status (phase 2)

The bot produces real non-NOOP actions from the first gameplay frame
(the `task_completing` default directive fires as soon as the
localizer locks). The cogames 10-step dry-run validation gate should
pass **without** `--skip-validation`. The LLM guidance loop (phase 3)
is not yet wired, so the bot plays on scripted defaults only — no
`ANTHROPIC_API_KEY` is required for dry-run or submission.

Once phase 3 ships, submissions with `--secret-env ANTHROPIC_API_KEY=...`
will enable the LLM strategic layer during matches.
