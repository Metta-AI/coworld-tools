# guided_bot

`guided_bot` is the active Among Them policy. Its supported execution surface is
Coworld only.

## Current Boundary

- Coworld image/CLI execution is the supported path.
- The legacy Python bundle path has been removed.
- The hosted-play shim has been removed.
- Local server scripts and raw run harnesses have been removed.
- The deprecated historical bot tree has been removed.

The remaining Nim code is the current policy implementation. Do not add local
Nim-server launchers or standalone run scripts around it. If we want a no-Nim
bot, that should be a deliberate rewrite rather than another compatibility
layer.

## Important Files

| Path | Purpose |
|---|---|
| `coworld/policy_player.py` | Coworld websocket entrypoint used by the policy image. |
| `coworld/amongthem_policy.py` | Thin Python adapter around the current guided_bot policy core. |
| `coworld/Dockerfile` | Coworld policy image definition. |
| `coworld/README.md` | Coworld build/upload/submit notes. |
| `bot.nim`, `modes/`, `perception/`, `ffi/` | Current guided_bot implementation. |

## Runtime Configuration

Coworld provides the player websocket through:

```text
COGAMES_ENGINE_WS_URL=ws://<game-service>:8080/player?slot=<slot>&token=<token>
```

The Coworld entrypoint also supports the generic JSON `coworld.player.v1`
adapter for older/local Coworld adapters. Raw BitWorld binary frames are used
when the first websocket message is binary.

## LLM Control

The intended default is:

```text
GUIDED_BOT_LLM_DISABLE=0
GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0
```

That allows the LLM to control meeting chat and votes while keeping gameplay
mode transitions on the symbolic/default/reflex path.

Useful Bedrock-related variables:

| Variable | Meaning |
|---|---|
| `USE_BEDROCK` | Enables Bedrock credentials supplied by Coworld. |
| `GUIDED_BOT_BEDROCK_MODEL` | Overrides the compiled default Bedrock model. |
| `GUIDED_BOT_LLM_DISABLE` | `1` disables LLM guidance entirely. |
| `GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES` | `1` allows LLM gameplay directives; default should remain `0`. |

## Tracing

Tracing is configured through environment variables or Coworld policy secrets:

| Variable | Meaning |
|---|---|
| `GUIDED_BOT_TRACE_DIR` | Trace destination. Use `stderr` for hosted Coworld logs. |
| `GUIDED_BOT_TRACE_LEVEL` | `off`, `events`, `decisions`, or `full`. |

When tracing is sent to `stderr`, hosted Coworld episode logs can capture the
JSONL trace lines. `perception.jsonl` is useful for summarized perception
diagnostics; raw frame dumps should stay out of hosted logs.

## Execution

Use `guided_bot/coworld/` as the runtime entrypoint. The repo-local UV project
at the Among Them root makes execution and inspection commands use:

```sh
uv run coworld ...
```

That UV project installs `coworld` as an editable path dependency from
`/Users/jamesboggs/coding/metta/packages/coworld`; do not use plain global
`coworld` when checking hosted status or running episodes for this workspace.

Do not reintroduce local launchers, legacy upload wrappers, hosted-play scripts,
or direct local-server commands.
