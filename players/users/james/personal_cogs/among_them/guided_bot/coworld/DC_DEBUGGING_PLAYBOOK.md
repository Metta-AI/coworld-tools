# Coworld Debugging Playbook

This playbook is intentionally Coworld-only. The old hosted-play helper and
local server scripts have been removed.

## First Checks

Use the repo-local UV project once it exists:

```sh
uv run coworld submissions --mine --json
uv run coworld rounds -l league_494db37d-d046-4cba-a99a-536b1439262f --limit 5 --json
uv run coworld episodes --mine -r ROUND_ID --json
```

Do not fall back to local checkout tooling.

## Episode Logs

Find the policy-agent log for a specific episode:

```sh
uv run coworld episode-logs EREQ_ID --mine --list
uv run coworld episode-logs EREQ_ID --mine
```

For raw files:

```sh
uv run coworld episode-logs EREQ_ID --mine -d /tmp/guided_bot_logs
```

Expected guided_bot logs should include the Coworld websocket connection, trace
JSONL lines when tracing is enabled, and a clean websocket close. If tracing is
configured with `GUIDED_BOT_TRACE_DIR=stderr`, the hosted logs should contain
lines prefixed by trace stream names such as `events`, `decisions`, `modes`,
`snapshots`, and `perception`.

## Meeting Diagnostics

For meeting work, inspect:

- meeting-start events and mode transitions;
- `perception` diagnostics for voting-screen, chat-panel, and chat-line
  detection;
- snapshot/evidence trace lines for the LLM-facing meeting context;
- LLM guidance trace lines for requested chat/vote decisions;
- emitted chat packets and vote masks.

The intended default is `GUIDED_BOT_LLM_DISABLE=0` and
`GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0`: LLM meeting control on, LLM gameplay
directive control off.

## Common Failure Shapes

| Symptom | Check |
|---|---|
| No trace lines in episode logs | Confirm `GUIDED_BOT_TRACE_DIR=stderr` and a non-`off` `GUIDED_BOT_TRACE_LEVEL`. |
| Meeting observed but no vote/chat action | Check meeting mode entry, voting-screen parse diagnostics, and LLM guidance lifecycle logs. |
| LLM affects movement outside meetings | Confirm `GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0`. |
| Episode has no score for our slot | Compare `episode-logs --mine --list` with `episode-results`; some game slots may not map cleanly to score rows. |
| Upload succeeds but policy is not in the league | Check image, policy version, submission, and league membership separately. |

## What Not To Use

Do not reintroduce:

- local server startup scripts;
- raw frame-capture run scripts;
- hosted-play wrappers;
- legacy bundle upload helpers;
- direct Coworld CLI imports from a local Metta checkout.
