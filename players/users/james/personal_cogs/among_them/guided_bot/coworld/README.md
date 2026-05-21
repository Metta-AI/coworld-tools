# guided_bot Coworld Image

This directory owns the Coworld runtime surface for guided_bot.

It contains the image entrypoint, the websocket player adapter, and operational
notes for uploading/submitting the policy image. It replaces the removed legacy
bundle, local server, and hosted-play paths.

## Runtime Contract

Coworld starts the image with:

```text
COGAMES_ENGINE_WS_URL=ws://<game-service>:8080/player?slot=<slot>&token=<token>
```

The raw Among Them player protocol is:

- receive binary websocket frames, one packed 128x128 4-bit screen per message
  (`8192` bytes);
- maintain the local 4-frame stack expected by the policy adapter;
- send one input packet per frame: packet kind `0`, then one button-mask byte.

`policy_player.py` also supports the generic JSON `coworld.player.v1` protocol
for Coworld adapters that send structured observations.

## Files

| Path | Purpose |
|---|---|
| `policy_player.py` | Websocket entrypoint used inside the policy image. |
| `amongthem_policy.py` | Python policy adapter used by `policy_player.py`. |
| `Dockerfile` | Coworld policy-image build definition. |
| `INSPECTING_RESULTS.md` | Coworld result and log inspection notes. |

## Command Surface

Run Coworld through the repo-local UV project at the Among Them root. This
workspace installs `coworld` as an editable path dependency from
`/Users/jamesboggs/coding/metta/packages/coworld`, so `uv run coworld ...`
uses the local Metta source checkout.

```sh
uv run coworld leagues
uv run coworld download among_them
uv run coworld play "$COWORLD_ID" "$IMAGE" --no-open-browser
uv run coworld run-episode "$COWORLD_ID" "$IMAGE"
uv run coworld upload-policy "$IMAGE" --name "$POLICY_NAME"
uv run coworld submit "$POLICY_NAME:v1" --league "$LEAGUE_ID"
```

`coworld download` writes to the cached layout
`./coworld/<coworld-id>/coworld_manifest.json` and prints the `<coworld-id>`
(e.g. `cow_4e26463b-a768-4db3-9aa9-2af8f3e009e7`) plus the suggested
`coworld play` command. Pass that bare id to `play` / `run-episode`, or use the
full `./coworld/<coworld-id>/coworld_manifest.json` path. Older `coworld`
releases wrote a flat `./coworld/coworld_manifest.json`; that layout is no
longer produced by the editable Metta source this workspace pins.

Do not use this repo's deleted local run scripts, the removed hosted-play shim,
or plain `coworld` from a global shell install. Use `uv run coworld ...` so the
editable Metta source declared by this workspace is selected.

`coworld play MANIFEST_URI [PLAYER_IMAGES]...` is the local-match replacement.
It runs the full manifest-defined match (for `among_them` v0.1.20 that is the
default 8-player variant: 10 000 ticks, 8 tasks per player, manifest-default
kill cooldown, vote timer, etc.). This is the command to use for any real
behavior observation: full-length self-play, watching meetings happen, seeing
kills and votes resolve, judging a policy change against a prior policy.

`coworld run-episode MANIFEST_URI [PLAYER_IMAGES]...` is the artifact-producing
validation command; add `-o DIR` to choose the output directory.

**`run-episode` is a short smoke test, not a behavior benchmark.** The runner
overrides the manifest's `config.json` with a stripped-down smoke
configuration (observed for `among_them` v0.1.20: `maxTicks=300`,
`tasksPerPlayer=1`, `startWaitTicks=0`, `gameOverTicks=1`, `roleRevealTicks=0`,
`voteTimerTicks=120` — and crucially `killCooldownTicks=900` is left
unchanged, which makes any imposter kill structurally impossible in a 300-tick
game). The episode finishes in ~5 seconds of game time and almost always
draws on time limit with zero kills. Use it to validate:

- the policy image starts and connects to the game server cleanly,
- the Coworld websocket adapter exchanges frames and actions without
  protocol errors,
- the stderr JSONL trace surface (`[trace:perception]`, `[trace:events]`,
  `[trace:modes]`, `[trace:decisions]`, `[trace:reflexes]`, `[trace:guidance]`)
  is reachable in `logs/policy_agent_N.txt`,
- `results.json`, `replay.json`, `replay.json.z`, and per-agent logs are
  produced under the chosen output directory.

Do **not** use `run-episode` to evaluate agent behavior. The smoke config
removes the conditions any non-trivial Among Them strategy depends on (long
horizon, multiple tasks, real kill window, real vote timer, real role-reveal
delay). For behavior evaluation use `coworld play` for a single full match,
or `coworld submit` against a league for a tournament-style judgment.

## LLM Defaults

The image should enable meeting LLM control while keeping gameplay directives
disabled:

```text
GUIDED_BOT_LLM_DISABLE=0
GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0
```

With Bedrock enabled, pass policy secrets through Coworld:

```sh
uv run coworld upload-policy "$IMAGE" \
  --name "$POLICY_NAME" \
  --use-bedrock \
  --secret-env GUIDED_BOT_BEDROCK_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0
```

## Tracing

For hosted diagnostics, prefer stderr JSONL:

```text
GUIDED_BOT_TRACE_DIR=stderr
GUIDED_BOT_TRACE_LEVEL=full
```

This captures event, decision, snapshot, mode, and perception diagnostics in
Coworld episode logs without dumping raw frame data.

## Submission Log

| Date | Policy version | League | Result |
|---|---|---|---|
| 2026-05-14 | `jamesboggs-guided-bot-coworld-20260514-092239:v1` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image uploaded and submitted; active champion placement recorded as `lpm_5324f856-8a27-49e7-84c7-3a7efd0e9cd2`. |
| 2026-05-18 | `jamesboggs-guided-bot-coworld-20260518-093152:v1` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image uploaded with `--use-bedrock` and Sonnet 4.5 Bedrock model; submission `sub_53d3b0d3-2ea5-439f-9979-1bc6aaac013d` accepted (status `pending`, placement runs asynchronously). First submission with the meeting-LLM-enabled / gameplay-symbolic boundary (`GUIDED_BOT_LLM_DISABLE=0`, `GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0`) and the slot↔color voting fix. Built against cached Coworld `among_them` v0.1.20; newer v0.1.24 not pulled (ghcr.io 403). |
| 2026-05-19 | `jamesboggs-guided-bot-coworld-20260519-094820:v1` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image uploaded with `--use-bedrock`; submission `sub_d0ad10c4-ad40-46ec-96cc-3e28785eb3fd` accepted (status `pending`). RCA of 2026-05-18 episode `ereq_7f106c8b` showed every meeting LLM call failing `no_key` because `resolveAwsCredentials` only knew ECS task-role + AWS CLI paths, but Coworld's `--use-bedrock` puts the pod under an EKS IRSA service account (`AWS_ROLE_ARN` + `AWS_WEB_IDENTITY_TOKEN_FILE`). Adds `fetchIrsaCredentials` (STS `AssumeRoleWithWebIdentity`) and a startup `llm_init` trace event summarizing provider selection + env presence so future failures self-diagnose. |
| 2026-05-21 | `jamesboggs-guided-bot-coworld-20260521-132827:v1` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image uploaded without `--use-bedrock`; submission `sub_a84f9a69-2ad7-4816-b8f6-e90f7ea9cf67` first placed as Qualifiers champion membership `lpm_fb38bbc7-7e38-4bf4-a115-ae8bd542fed0`, then promoted to active Dirt membership `lpm_44628f31-225e-4bd8-b117-8c89be2c585d` after qualifier round `round_f50c2673-05e2-4bde-99af-3a830811cf8c`. This version makes no-LLM meeting fallback vote after 96 ticks and lowers crew fallback evidence threshold to one visible vote dot, based on Wood logs where Bedrock meeting calls returned account-level 404s and prior fallback votes arrived around tick 360. |
| 2026-05-21 | `jamesboggs-guided-bot-coworld-20260519-094820:v2` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | Same linux/amd64 image as `20260521-132827`, uploaded without `--use-bedrock` under the existing Wood policy name to test whether a new policy version can update the active Wood entry. Submission `sub_e05ef4b8-ae54-409a-b158-f474d41a455e` accepted with policy version `be07d429-8573-4743-a88d-6f4ab348ba7c`; first placed as Qualifiers champion membership `lpm_a347d4f5-3329-4cb3-bdd7-0fce957fb9c6`, then promoted to active Dirt champion membership `lpm_88d5a76d-1e4c-42ff-8460-9596233223d1` after qualifier round `round_d49238ab-5eb5-4ad1-89ff-71128c276646`. It did not update the existing active Wood `v1` entry in place. |
| 2026-05-21 | `jamesboggs-guided-bot-coworld-20260519-094820:v3` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image uploaded without `--use-bedrock`; submission `sub_4d44f596-90a9-4f8b-829e-3e539ded24e4` accepted with policy version `37f3752c-67d4-4ea8-a4c2-a377d352d556`. It first placed as Qualifiers champion membership `lpm_c5f9bddf-0fb4-434e-acb3-27c489c63041`, then promoted to active Dirt champion membership `lpm_03e6b14a-1ec6-47c0-b817-5c5453e967e5` after qualifier round `round_141f78e1-6860-4366-b43f-01c7966f7ec4`. This version keeps the v2 meeting fallback changes and additionally marks confirmed kill targets dead in belief memory so imposters do not re-target victims when body detection lags. |
| 2026-05-21 | `jamesboggs-guided-bot-coworld-20260519-094820:v4` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image uploaded without `--use-bedrock`; submission `sub_d7ec482a-bd12-498b-844e-114ac47ba605` accepted with policy version `78f245c1-2c69-4255-9f25-85da99f88a40`. It was placed as active Qualifiers champion membership `lpm_1628d70b-c724-4dde-a766-528c8037ca56`, won qualifier round `round_2ee34e22-c2c0-4966-aca2-acc4754a096a` with score `76.32`, and qualified to active Dirt membership `lpm_c7ca8a47-a3fb-460a-8e99-c2b84dc48f8a` at `2026-05-21T22:00:28.894416Z`. This version keeps the v3 fallback-voting and kill-memory changes and adds post-task crew behavior: after enough confirmed completed tasks, crewmates stop wandering task targets, shadow visible crew, or press the emergency button only with strong accumulated body/evidence signals. |
| 2026-05-21 | `jamesboggs-guided-bot-coworld-20260519-094820:v5` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image uploaded without `--use-bedrock`; submission `sub_38f0d3f5-e5b2-4936-9749-5705e0986305` accepted with policy version `68b09089-8530-419b-b3d2-34d7607ca064` and placed as active Qualifiers champion membership `lpm_e72acfbc-68c7-4060-9cff-586f33d6046d` at `2026-05-21T21:57:18.849686Z`. It won qualifier round `round_31c7339f-1159-4189-8719-61f01ab6bcde` with score `73.46375` and qualified to active Dirt membership `lpm_4017df13-8ebc-4f67-9fd0-07ba46399ab6` at `2026-05-21T22:12:59.227876Z`. This version keeps the v4 post-task crew behavior and changes the crewmate body-report reflex from body-count edge detection to remembered-position unknown-body detection, so a different visible corpse can trigger reporting even when the visible body count stays stable. |
| 2026-05-21 | `jamesboggs-guided-bot-coworld-20260519-094820:v6` | Among Them Daily (`league_494db37d-d046-4cba-a99a-536b1439262f`) | linux/amd64 image `jamesboggs-guided-bot-coworld:20260521-150918` uploaded without `--use-bedrock`; submission `sub_eb0a17fb-af2f-45d1-9d86-231e7c202882` accepted with policy version `da69817e-a7b3-451f-abd5-42349bb92e37`. It placed as active Qualifiers champion membership `lpm_521bdf78-a490-4242-93d5-e18159fe617f`, won qualifier round `round_74dad60c-5aa8-4596-bd7c-586309cc7802` with score `76.98875`, and qualified to active Dirt champion membership `lpm_81baef05-07fa-43d9-a665-44ffb654fb6d` at `2026-05-21T22:25:18.001178Z`. This version keeps the v5 body-report behavior and changes diagonal stuck recovery so diagonal movement splits to one axis during jiggle windows instead of holding the blocked diagonal or emitting opposing direction buttons. |
