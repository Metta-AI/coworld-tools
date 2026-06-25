# Inspecting Coworld Results

Use this as the Coworld-only result-inspection reference for guided_bot.

## Key IDs

| Entity | ID |
|---|---|
| Among Them Daily league | `league_494db37d-d046-4cba-a99a-536b1439262f` |
| Daily division | `div_334593c6-da90-4651-98c7-606573ea1474` |
| Among Them game | `game_8a1c0e5c-512b-4b01-86d2-8a152b4b5aa0` |

## Command Surface

After the repo-local UV project is added, run the public Coworld CLI from this
workspace:

```sh
uv run coworld results div_334593c6-da90-4651-98c7-606573ea1474
uv run coworld rounds -l league_494db37d-d046-4cba-a99a-536b1439262f --limit 5 --json
uv run coworld submissions --mine --json
uv run coworld memberships --mine --json
```

Do not use a local Metta checkout or removed repo scripts for result
inspection.

## Round Inspection

Get recent completed rounds:

```sh
uv run coworld rounds \
  -l league_494db37d-d046-4cba-a99a-536b1439262f \
  --status completed \
  --limit 5 \
  --json
```

Then inspect one round:

```sh
uv run coworld results ROUND_ID
uv run coworld episodes --mine -r ROUND_ID --limit 32 --json
```

## Episode Inspection

List and read our policy logs:

```sh
uv run coworld episode-logs EREQ_ID --mine --list
uv run coworld episode-logs EREQ_ID --mine
```

Download logs when stdout/stderr mixing makes interactive output hard to read:

```sh
uv run coworld episode-logs EREQ_ID --mine -d /tmp/guided_bot_logs
```

Read episode results:

```sh
uv run coworld episode-results EREQ_ID
```

Match the policy-agent slot from `episode-logs --mine --list` to the `PlayerN`
entry in `episode-results`.

## JSON Shapes

| Command | Expected shape |
|---|---|
| `submissions --mine --json` | array |
| `rounds -l LEAGUE --json` | object with `entries` |
| `episodes --mine -r ROUND --json` | array |
| `episode-results EREQ_ID` | object with parallel result arrays |
| `results DIV_ID` | object with ladder-style result data |

If these shapes drift, update this document when the repo-local UV Coworld
project is added.
