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
