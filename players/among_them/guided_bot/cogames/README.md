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
- `perception/baked/` — deterministic baked data loaded via
  `staticRead`, including `nav_graph.json` and `nav_paths.bin`.
  `ship.sh` includes the whole `among_them/guided_bot` tree, so the
  navigation graph and path blob are already in the cogames bundle.

## Secrets

The LLM is an expected-present component (DESIGN.md §1 goal 5).
`ship.sh` reads `ANTHROPIC_API_KEY` from the environment and forwards
it as `--secret-env` to the cogames upload. If the key is missing, the
policy still loads and plays on defaults (see DESIGN.md §9) — useful
for dry-runs and for degraded operation if an API outage hits
mid-match.

See `metta/packages/cogames/POLICY_SECRETS.md` for how the key reaches
the policy subprocess at match time.

## Current status

**Status:** Phase 6+ (mode completeness). The full pipeline works:
perception → belief → navigation → mode decision → LLM guidance
(when `ANTHROPIC_API_KEY` is set). Without the key, the bot runs on
scripted defaults — which is sufficient for dry-run validation and is
how the bot actually plays in most tournament matches until the LLM
responds (~5s into the game).
