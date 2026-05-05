# Orpheus Agent

LLM-driven dual-loop agent for Persephone's Escape.

## Architecture

```
                    +------------------+
                    |   Slow Loop      |  (background thread, ~2s interval)
                    |                  |
                    |  BeliefSnapshot  |
                    |       |          |
                    |       v          |
                    |     LLM          |  (configurable provider/model)
                    |       |          |
                    |       v          |
                    |   TaskParams     |
                    +--------|---------+
                             |
                             | set_task()
                             v
+-------------------------------------------------------------------+
|                     Fast Loop (main thread, 24 FPS)                |
|                                                                   |
|  frame bytes --> parse_frame() --> belief.update() --> controller  |
|                  (perception)       (accumulate)     .tick()       |
|                                                        |          |
|                                                        v          |
|                                                   FrameAction     |
|                                                   (button mask    |
|                                                    + chat)        |
|                                                        |          |
|                                                        v          |
|                                                   WebSocket send  |
+-------------------------------------------------------------------+
```

**Fast loop** (every frame):
1. Receive 8192-byte frame from server
2. `parse_frame()` -- stateless pixel-to-symbol parser (perception module)
3. `belief.update()` -- accumulate into world model
4. `controller.tick()` -- active task produces a button mask
5. Send action to server

**Slow loop** (background thread, configurable interval):
1. `belief.snapshot()` -- thread-safe frozen copy of belief state
2. `make_decision()` -- serialize to prompt, call LLM, parse response
3. `controller.set_task()` -- swap in the new behavior

The key insight: the LLM reasons at the strategic level (which task to
pursue), while the fast loop handles frame-level execution (translating
the task into button presses). This decouples LLM latency (~1-2s) from
the game's 24 FPS tick rate.

The fast loop runs independently of the slow loop. If the LLM dies or
becomes unavailable, the fast loop continues executing the last assigned
task indefinitely.

**Exception: `chat_and_observe` blocks the fast loop.** When the active
task is `chat_and_observe`, the fast loop makes synchronous LLM calls to
generate chat messages. This is intentional -- the agent can't
meaningfully act while composing a message, and chat content must come
from the LLM. The fast loop resumes normal speed between chat turns
(while waiting for responses or during cooldown).

## Tasks

High-level behaviors the LLM can select:

| Task | Context | Description |
|------|---------|-------------|
| `idle` | any | Do nothing |
| `explore` | overworld | Wander to discover players |
| `move_to` | overworld | Move toward coordinates |
| `pursue_player` | overworld | Follow a player by minimap color |
| `open_chatroom` | overworld | Approach player + create/request chatroom |
| `offer_role_exchange` | chatroom | Execute R.OFFER menu sequence |
| `accept_role_exchange` | chatroom | Execute R.ACCPT menu sequence |
| `chat_and_observe` | chatroom | Block on LLM to generate chat, send, wait for response |
| `exit_chatroom` | chatroom | Leave via Select |
| `shout` | overworld | Send global chat message |
| `check_info` | overworld | Toggle info screen |

## Usage

```bash
# With stub LLM (no API key needed, for testing)
PYTHONPATH=. python agents/orpheus/policy.py --url ws://localhost:2500/player --name orpheus_1

# With Anthropic Claude
ANTHROPIC_API_KEY=sk-... python agents/orpheus/policy.py \
    --url ws://localhost:2500/player \
    --name orpheus_1 \
    --provider anthropic \
    --model claude-sonnet-4-20250514

# With OpenAI
OPENAI_API_KEY=sk-... python agents/orpheus/policy.py \
    --url ws://localhost:2500/player \
    --name orpheus_1 \
    --provider openai \
    --model gpt-4o-mini

# Via the universal runner (uses env vars for provider config)
ORPHEUS_LLM_PROVIDER=anthropic ORPHEUS_LLM_MODEL=claude-sonnet-4-20250514 \
    python run_agents.py orpheus
```

## Configuration

| Env Variable | CLI Flag | Default | Description |
|-------------|----------|---------|-------------|
| `ORPHEUS_LLM_PROVIDER` | `--provider` | `stub` | LLM provider |
| `ORPHEUS_LLM_MODEL` | `--model` | provider default | Model identifier |
| `ORPHEUS_LLM_INTERVAL` | `--llm-interval` | `2.0` | Seconds between LLM calls |
| `ORPHEUS_TRACE_DIR` | `--trace-dir` | None (disabled) | Trace output directory |
| `ORPHEUS_TRACE_LEVEL` | `--trace-level` | `full` | `events`, `decisions`, or `full` |
| `ORPHEUS_TRACE_META` | -- | -- | Comma-separated `key=value` metadata |
| `ANTHROPIC_API_KEY` | -- | -- | Required for `anthropic` provider |
| `OPENAI_API_KEY` | -- | -- | Required for `openai` provider |
| AWS credentials | -- | -- | Required for `bedrock` provider |

## File Structure

```
agents/orpheus/
  __init__.py        # Package marker
  policy.py          # Entry point, WebSocket loop, orchestration
  belief.py          # BeliefState accumulator (thread-safe)
  tasks.py           # Task definitions + controller
  llm.py             # LLM provider abstraction + decision function
  trace.py           # Opt-in JSONL tracing system
  TRACING.md         # Tracing system design spec
  README.md          # This file
```

## Tracing

Opt-in structured tracing for post-mortem debugging and LLM evaluation.
Enable via `ORPHEUS_TRACE_DIR`:

```bash
ORPHEUS_TRACE_DIR=/tmp/orpheus_traces python agents/orpheus/policy.py \
    --url ws://localhost:2500/player --name orpheus_1 --provider stub
```

Produces a session directory with JSONL files:

```
<trace_dir>/<session_id>/
    manifest.json     # Session metadata, identity, counters, result
    events.jsonl      # Edge-triggered events (phase, identity, players, chatroom)
    decisions.jsonl   # Slow-loop LLM decisions with context and latency
    tasks.jsonl       # Task transitions with duration tracking
    chat.jsonl        # LLM chat generation (prompts, responses)
```

Trace levels (cumulative): `events` < `decisions` < `full`.
Non-perturbing: I/O errors disable the stream, never crash the agent.
See [TRACING.md](TRACING.md) for the full design specification.

## Status

**Skeleton** -- the architecture is complete but task implementations
are minimal. Next steps:

- [ ] Smarter exploration (avoid revisiting areas)
- [ ] Obstacle-aware movement (pathfinding)
- [ ] Better LLM prompting (game strategy, team coordination)
- [ ] Event buffer for LLM context (what happened since last decision)
- [ ] Reactive overrides (auto-accept role exchange from teammate)
- [ ] Hostage select strategy (leader behavior)

## Submission Log

| Date | Provider/Model | Season | Dry-run | Score |
|------|---------------|--------|---------|-------|
| -- | -- | -- | -- | -- |
