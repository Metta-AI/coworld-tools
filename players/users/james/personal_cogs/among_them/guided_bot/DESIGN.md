# guided_bot Design

This design document reflects the Coworld-only cleanup.

## Runtime Boundary

- Coworld is the only supported execution surface.
- The legacy bundle path, hosted-play shim, local server scripts, and historical
  bot tree have been removed.
- The next command surface should be the repo-local UV project using public
  PyPI Coworld through `uv run coworld ...`.
- Meeting LLM control is allowed.
- LLM gameplay directives should remain disabled by default.

## Architecture

`guided_bot` is a pixel-observation policy with four layers:

1. `perception/` reads the 128x128 PICO-8 frame stack and updates raw percepts.
2. `belief.nim` merges percepts into persistent self, map, social, and meeting
   memory.
3. `mode_registry.nim`, `reflex.nim`, and `modes/` select and execute the
   symbolic mode.
4. `action.nim` turns mode intents into button masks and chat packets.

The Coworld bridge lives in `coworld/`:

- `policy_player.py` connects to the Coworld websocket.
- `amongthem_policy.py` adapts the current guided_bot policy core to the
  Coworld player loop.
- `Dockerfile` defines the policy image.

## Mode Ownership

| Mode | Primary doc | Implementation |
|---|---|---|
| idle | `IDLE_DESIGN.md` | `modes/idle.nim` |
| task completing | `TASK_COMPLETING_DESIGN.md` | `modes/task_completing.nim` |
| pretending | `PRETENDING_DESIGN.md` | `modes/pretending.nim` |
| hunting | `HUNTING_DESIGN.md` | `modes/hunting.nim` |
| fleeing | `FLEEING_DESIGN.md` | `modes/fleeing.nim` |
| reporting | `REPORTING_DESIGN.md` | `modes/reporting.nim` |
| meeting | `MEETING_DESIGN.md` | `modes/meeting.nim` |

High-level gameplay transitions outside meetings are symbolic. The LLM may
provide meeting chat and vote actions, but should not be allowed to steer
gameplay modes while `GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0`.

## Meeting LLM Contract

During meetings, the LLM receives structured snapshot evidence:

- phase and current mode;
- visible/current chat and recent deduplicated chat;
- voting screen state, including current slot-to-color mapping;
- per-player evidence ledger;
- role, alive/dead, vote, suspicion, alibi, and trust summaries.

The LLM can enqueue meeting actions:

- speak;
- vote;
- unvote;
- confirm vote;
- wait.

`modes/meeting.nim` remains the legality boundary. It guards self-votes, dead
targets, invalid targets, and known imposter teammates.

## Tracing

Tracing should be useful through Coworld logs. The preferred hosted setting is:

```text
GUIDED_BOT_TRACE_DIR=stderr
GUIDED_BOT_TRACE_LEVEL=full
```

Important streams:

- `events.jsonl`: high-level game, chat, vote, and meeting events.
- `modes.jsonl`: mode transitions.
- `decisions.jsonl`: button masks and per-tick decisions.
- `snapshots.jsonl`: LLM-facing snapshots.
- `guidance.jsonl`: LLM request/response and action lifecycle.
- `perception.jsonl`: summarized perception diagnostics.

Do not log raw frame dumps in hosted Coworld logs.

## Open Design Decision

The current policy implementation still uses a Nim core. If the project goal is
zero Nim builds, that should be a separate rewrite decision with a new design
doc and validation plan. This cleanup only removes obsolete run surfaces and
keeps Coworld as the sole runtime boundary.
