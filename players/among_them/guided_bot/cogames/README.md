# guided_bot / cogames submission

Entry point for the cogames tournament: `amongthem_policy.AmongThemPolicy`.

## Quick flow

```sh
export SEASON=<active-season>
export POLICY_NAME=$USER-guided-bot-$(date +%Y%m%d-%H%M%S)

# Dry-run. By default this requests Bedrock access; the bot still has
# scripted fallbacks if the LLM is unavailable during validation.
./ship.sh dry-run

# If dry-run passes, ship with Bedrock LLM enabled.
./ship.sh ship

# If dry-run builds/runs cleanly but fails only the 10-step no-op gate,
# use the sanctioned skip-validation path.
./ship.sh ship-skip-validation

# Optional direct Anthropic fallback instead of Bedrock
USE_BEDROCK=0 ANTHROPIC_API_KEY=sk-ant-... ./ship.sh ship
```

`ship.sh` runs from the `personal_cogs/` repo root so the `-f` includes
resolve correctly.
The wrapper uses `cogames upload --season` because current `cogames ship`
does not expose LLM credential flags.

For the private daily Among Them flow, use the Coworld image path in
`../coworld/README.md` instead. The daily website expects a policy version
with a `container_image_id`; this zip/S3 upload path does not create one.

## What gets bundled

- `amongthem_policy.py` — the `AmongThemPolicy` class ctypes-loads
  `libguidedbot.{dylib,so,dll}` and routes `step_batch` through it.
- `among_them/guided_bot/` — full Nim source tree + `build_guided_bot.py`.
  The build helper installs Nim 2.2.4 when needed, syncs the package
  pins in `nimby.lock`, and compiles `libguidedbot` inside the worker
  on first use.
- `among_them/common/perception_kernels/` — shared pure-Nim perception
  kernels imported by guided_bot's localization, actor, task, and OCR
  modules.
- `perception/baked/` — deterministic baked data loaded via
  `staticRead`, including `nav_graph.json` and `nav_paths.bin`.
  `ship.sh` includes the whole `among_them/guided_bot` tree, so the
  navigation graph and path blob are already in the cogames bundle.

## LLM Credentials

The LLM is an expected-present component (DESIGN.md §1 goal 5).
`ship.sh` passes `--use-bedrock` by default, which asks cogames to run
the policy with Bedrock access (`USE_BEDROCK=true`). The Nim LLM client
then resolves AWS credentials from the policy environment, ECS task-role
metadata, or the local AWS CLI credential export path.

`ANTHROPIC_API_KEY` remains supported as a direct Anthropic fallback
when Bedrock is disabled with `USE_BEDROCK=0`. If no provider is
available, the policy still loads and plays on defaults (see DESIGN.md
§9), which is useful for dry-runs and degraded operation if an LLM
outage hits mid-match.

Current `cogames upload` requires `--llm-model` whenever an LLM provider
is configured. For Bedrock, `ship.sh` defaults to
`global.anthropic.claude-sonnet-4-5-20250929-v1:0`; for direct Anthropic
it defaults to `claude-sonnet-4-20250514`. `GUIDED_BOT_LLM_MODEL`,
`GUIDED_BOT_BEDROCK_MODEL`, and `GUIDED_BOT_ANTHROPIC_MODEL` override
those defaults and are forwarded as secret env vars when set so the
policy uses the same model that cogames registers.

## Current status

**Status:** Phase 6+ (mode completeness). The full pipeline works:
perception → belief → navigation → mode decision → LLM guidance
(through Bedrock by default, or direct Anthropic when configured).
Without an available provider, the bot runs on scripted defaults —
which is sufficient for dry-run validation and is how the bot plays
until the LLM responds.
