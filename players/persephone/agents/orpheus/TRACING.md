# Orpheus Tracing System Design

## Goals

1. **Post-mortem debugging** -- understand why the agent did what it did in a past game without re-running
2. **LLM evaluation** -- see exactly what prompts went in and what came out, correlate with outcomes
3. **Task analysis** -- how long each task ran, why it was replaced, what it achieved
4. **Extensibility** -- adding a new task type or event requires zero changes to the trace writer; the writer accepts arbitrary structured payloads
5. **Non-perturbing** -- tracing never crashes the agent; identical behavior with tracing on or off
6. **Opt-in** -- zero cost when disabled (env var not set)

## Output Layout

```
<ORPHEUS_TRACE_DIR>/<session_id>/
    manifest.json       # session metadata, config, rolled-up stats
    events.jsonl        # edge-triggered events (phase changes, identity, comms, etc.)
    decisions.jsonl     # one line per slow-loop LLM decision
    tasks.jsonl         # one line per task transition (what the fast loop executed)
    chat.jsonl          # LLM chat generation (prompts, responses, latency)
```

Session ID format: `<ISO8601-UTC>_<PID>` (e.g., `2026-05-04T170300Z_48291`).

### Why separate files (not one big JSONL)?

- **Grep-friendly** -- `cat decisions.jsonl` shows only strategy without noise
- **Different cadences** -- events are sparse (~10-50/game), decisions are ~1/2s, tasks are ~1/2s, chat is rare
- **Size control** -- chat.jsonl includes full LLM prompts/responses (large); the others are compact
- **Extensibility** -- adding a new stream (e.g., `perception.jsonl`) doesn't change existing parsers

## Configuration

| Env Variable | CLI Flag | Default | Description |
|---|---|---|---|
| `ORPHEUS_TRACE_DIR` | `--trace-dir` | None (disabled) | Root directory for trace output |
| `ORPHEUS_TRACE_LEVEL` | `--trace-level` | `full` | `events`, `decisions`, `full` |

Levels are cumulative:
- `events` -- only events.jsonl
- `decisions` -- events + decisions + tasks
- `full` -- all streams including chat (with full LLM prompts/responses)

When `ORPHEUS_TRACE_DIR` is not set, no trace writer is created and no I/O occurs.

## Record Schemas

### Common Fields (every record in every file)

```json
{
  "tick": 142,
  "wall_ms": 5921,
  "ts": "2026-05-04T17:03:05.921Z"
}
```

- `tick` -- agent's internal frame counter (from `belief.tick_count`)
- `wall_ms` -- milliseconds since session start (for relative timing)
- `ts` -- absolute ISO8601 timestamp (for cross-session correlation)

### events.jsonl

Edge-triggered state changes. A new event is emitted only when
something *transitions*, not every frame.

| Event Type | Trigger | Payload |
|---|---|---|
| `session_start` | Agent connects | `{name, url, provider, model, llm_interval}` |
| `identity` | Role reveal parsed | `{role, team, room, color, room_size}` |
| `phase_change` | GamePhase transitions | `{from, to}` |
| `view_change` | View transitions (debounced, 3+ frames stable) | `{from, to}` |
| `player_discovered` | New color in belief.players | `{color}` |
| `player_role_known` | Role/team revealed for a player | `{color, role, team, source}` |
| `chatroom_entered` | View becomes WHISPER | `{occupants}` |
| `chatroom_exited` | View leaves WHISPER | `{occupants, duration_ticks}` |
| `offer_received` | pending offer transitions to True | `{offer_type}` |
| `game_over` | Result parsed | `{winner, our_team, won}` |
| `session_end` | Agent disconnects/shuts down | `{reason, total_frames, total_decisions}` |

Extensibility: any code can call `tracer.event("my_new_type", {payload})`.
No registration needed.

### decisions.jsonl

One line per slow-loop LLM decision:

```json
{
  "tick": 142, "wall_ms": 5921, "ts": "...",
  "decision_num": 3,
  "task": "pursue_player",
  "params": {"target_color": 3},
  "reasoning": "Hades is nearby, need to initiate exchange",
  "latency_ms": 832,
  "context_summary": "R1 12s, playing, position=(45,62), 2 players nearby",
  "prev_task": "explore",
  "prev_task_duration_ticks": 48
}
```

### tasks.jsonl

One line per task transition (either from LLM decision or from
initial default):

```json
{
  "tick": 142, "wall_ms": 5921, "ts": "...",
  "from": "explore",
  "to": "pursue_player",
  "from_duration_ticks": 48,
  "from_duration_ms": 2004,
  "trigger": "llm_decision",
  "params": {"target_color": 3}
}
```

`trigger` values: `"llm_decision"`, `"initial"`, `"chat_complete"`
(future: reactive overrides could add `"reactive_override"`)

### chat.jsonl

One line per LLM chat generation (from `ChatAndObserveTask`):

```json
{
  "tick": 200, "wall_ms": 8400, "ts": "...",
  "direction": "outbound",
  "system_prompt": "You are chatting in a private chatroom...",
  "user_prompt": "You are: Hades (shades)\nChatroom occupants...",
  "response": "I AM HADES LETS TRADE",
  "latency_ms": 650,
  "occupants": [3, 14],
  "message_count_before": 2
}
```

Also logs inbound messages for completeness:

```json
{
  "tick": 248, "wall_ms": 10400, "ts": "...",
  "direction": "inbound",
  "sender_color": 14,
  "text": "OK LETS DO IT",
  "is_system": false
}
```

### manifest.json

Written at session end (or periodically flushed):

```json
{
  "schema_version": 1,
  "session_id": "2026-05-04T170300Z_48291",
  "agent": "orpheus",
  "started_unix_ms": 1746374580000,
  "ended_unix_ms": 1746374625000,
  "ended_reason": "server_disconnect",
  "config": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "llm_interval": 2.0,
    "trace_level": "full"
  },
  "identity": {
    "role": "Hades",
    "team": "shades",
    "room": "underworld",
    "color": 3
  },
  "counters": {
    "total_frames": 708,
    "total_decisions": 7,
    "total_task_transitions": 8,
    "total_chats_sent": 3,
    "total_chats_received": 5,
    "phases_seen": ["lobby", "role_reveal", "playing", "game_over"]
  },
  "result": {
    "winner": "Shades",
    "won": true
  },
  "meta": {}
}
```

The `meta` field is for arbitrary key-value pairs from
`ORPHEUS_TRACE_META` (same pattern as modulabot).

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  TraceWriter                                            │
│                                                         │
│  .event(type, payload)     → events.jsonl               │
│  .decision(decision)       → decisions.jsonl            │
│  .task_transition(...)     → tasks.jsonl                │
│  .chat(direction, ...)     → chat.jsonl                 │
│                                                         │
│  Internal:                                              │
│  - Write-through (flush each line)                      │
│  - I/O errors → log warning + disable stream (no crash) │
│  - from_env() factory returns None when disabled        │
└─────────────────────────────────────────────────────────┘
         ▲                    ▲                  ▲
         │                    │                  │
    ┌────┘        ┌───────────┘          ┌───────┘
    │             │                      │
  policy.py    SlowLoop              ChatAndObserveTask
  (events)    (decisions,            (chat generation)
              task transitions)
```

### Integration Points

1. **policy.py** -- creates `TraceWriter` (or None) at startup, passes
   it to SlowLoop and TaskController
2. **SlowLoop._decide_once()** -- calls `tracer.decision(...)` after
   each LLM decision
3. **TaskController.set_task()** -- calls `tracer.task_transition(...)`
   on every swap
4. **ChatAndObserveTask._generate_chat()** -- calls `tracer.chat(...)`
   for each LLM chat call
5. **BeliefState.update()** -- calls `tracer.event(...)` for
   edge-triggered state changes (phase, identity, player discovery)

### Extensibility Contract

Adding a new task type requires **zero changes** to the trace writer.
The writer accepts:

```python
tracer.event("any_string", {"any": "dict"})
```

Adding a new trace stream (e.g., `perception.jsonl`) requires:
1. Add a new file handle in `TraceWriter.__init__`
2. Add a new public method (e.g., `tracer.perception(...)`)

Adding new fields to existing records requires no schema migration --
JSONL is schema-free.

### Non-Perturbing Guarantees

1. `TraceWriter.from_env()` returns `None` when disabled -- callers
   check `if self._tracer:` before calling
2. All I/O in try/except -- on failure, the stream is disabled and a
   warning is logged (once)
3. No allocations on the hot path when tracing is off (None check is a
   pointer comparison)
4. Trace writes are fire-and-forget -- no return values that could
   affect agent logic
5. The writer never reads agent state; it only receives what callers
   explicitly pass

### Buffering Strategy

- All streams: write-through (flush after each line). Volume is low
  enough that debuggability > throughput.
- Manifest: written once at session end (or on SIGTERM via atexit).
- No background thread for writes. Trace overhead is negligible
  compared to LLM latency and frame processing.

## Usage

```bash
# Enable full tracing
ORPHEUS_TRACE_DIR=/tmp/orpheus_traces python agents/orpheus/policy.py \
    --url ws://localhost:2500/player --name orpheus_1 --provider anthropic

# Events only (minimal overhead, no LLM prompt logging)
ORPHEUS_TRACE_DIR=/tmp/orpheus_traces ORPHEUS_TRACE_LEVEL=events \
    python agents/orpheus/policy.py ...

# With metadata tags (for experiment tracking)
ORPHEUS_TRACE_META=experiment=baseline,git_sha=abc1234 \
    ORPHEUS_TRACE_DIR=/tmp/orpheus_traces \
    python agents/orpheus/policy.py ...
```

## Future Extensions (not in initial implementation)

- **Perception stream** (`perception.jsonl`) -- log parsed
  FramePerception summaries at configurable cadence (every Nth frame)
- **Belief snapshots** -- periodic full belief state dumps for
  state-space analysis
- **Replay viewer** -- tool to reconstruct game timeline from trace
  files + captured frames
- **Diff-based compression** -- for high-frequency streams, emit only
  fields that changed
- **Remote trace sink** -- write to a socket/queue instead of local
  files (for distributed testing)
