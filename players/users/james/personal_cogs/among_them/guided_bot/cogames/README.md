# guided_bot / legacy cogames bundle path

This directory is the older Python `MultiAgentPolicy` bundle wrapper:
`amongthem_policy.AmongThemPolicy` ctypes-loads guided_bot's Nim library and can
be uploaded with `cogames upload`.

Do **not** use this path for the current public Among Them Daily instructions.
The current guide at <https://softmax.com/play_amongthem.md> expects a
standalone linux/amd64 Docker image and a Docker-image-backed policy version.
Use [`../coworld/README.md`](../coworld/README.md) for that flow.

## When This Path Still Applies

Use `ship.sh` only for legacy cogames bundle experiments or if Softmax reopens a
Python-bundle Among Them season:

```sh
export SEASON=<active-season>
export POLICY_NAME=$USER-guided-bot-$(date +%Y%m%d-%H%M%S)

./ship.sh dry-run
./ship.sh ship

# Only for the known 10-step all-noop validator limitation.
./ship.sh ship-skip-validation
```

`ship.sh` runs from the `personal_cogs/` repo root so `-f` paths resolve
correctly. It uses `cogames upload --season` because historical `cogames ship`
did not expose the LLM credential flags guided_bot needed.

## What Gets Bundled

- `amongthem_policy.py` - the `AmongThemPolicy` class ctypes-loads
  `libguidedbot.{dylib,so,dll}` and routes `step_batch` through it.
- `among_them/guided_bot/` - Nim source tree plus `build_guided_bot.py`; the
  build helper compiles `libguidedbot` inside the worker on first use.
- `among_them/common/perception_kernels/` - shared pure-Nim perception kernels.
- `perception/baked/` - deterministic baked data loaded via `staticRead`.

## LLM Credentials

The legacy bundle path can request Bedrock via `--use-bedrock` and can pass
runtime secrets with `--secret-env`. The current public Docker-image Coworld
v2 flow has equivalent upload-time flags on `coworld upload-policy`:

```sh
uv run coworld upload-policy "$IMAGE" \
  --name "$POLICY_NAME" \
  --use-bedrock \
  --secret-env GUIDED_BOT_BEDROCK_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0
```

Without credentials, guided_bot still loads and plays with scripted fallbacks.
