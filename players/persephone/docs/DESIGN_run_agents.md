# Universal Agent Runner -- Design Report

## Goal

A single `run_agents.py` script at the project root that launches any
combination of registered agents against a Persephone server. Must
support agents written in any language, multiple instances of the same
agent, and clean lifecycle management.

---

## CLI Interface

```
python run_agents.py [OPTIONS] AGENT_SPEC [AGENT_SPEC ...]
```

### Agent Specs

Each `AGENT_SPEC` is either:
- `name` -- one instance of agent `name`
- `name:N` -- N instances of agent `name`

Bare names can be repeated: `baseline baseline` = `baseline:2`.

```bash
# One baseline agent
python run_agents.py baseline

# Three baseline agents
python run_agents.py baseline:3

# Mixed: 3 baselines + 1 custom agent
python run_agents.py baseline:3 my_agent

# Fill a 10-player game: 3 of ours, 7 filler bots
python run_agents.py my_agent:3 baseline:7
```

### Server Targeting

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `localhost` | Server hostname |
| `--port` | `2500` | Server port |
| `--url` | (built from host+port) | Full WebSocket URL override |

If `--url` is given, it takes precedence. Otherwise the URL is
constructed as `ws://{host}:{port}/player`.

### Other Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--name-prefix` | (agent id) | Override the player name prefix |
| `--list` | off | List registered agents and exit |
| `--log-dir DIR` | none | Write per-agent stdout to `DIR/{name}.log` |
| `--log-level LEVEL` | agent default | Forward Orpheus/Eurydice JSONL logging level to agents that support it |
| `--record-frames DIR` | none | Forward frame recording directory to Eurydice agents |
| `--quiet` | off | Suppress agent stdout on console (still logged if `--log-dir`) |

---

## Agent Registration

An agent is "registered" by having a directory under `agents/` that
contains a `policy.py` file:

```
agents/
  baseline/
    policy.py      <-- required entry point
    README.md      <-- optional
    ...
  my_agent/
    policy.py
    ...
```

The runner discovers agents by scanning `agents/*/policy.py`. The
directory name is the agent identifier used in CLI specs.

No manual registration step, no config file. Drop a folder with a
`policy.py` and it's available.

---

## The `policy.py` Contract

This is the core design decision. Each `policy.py` must be **runnable
as a script** with a standard CLI interface:

```
python agents/<id>/policy.py --url URL --name NAME [--kwargs JSON]
```

When invoked, it must:
1. Connect to the server at `URL` with player name `NAME`
2. Play until disconnected, game over, or interrupted (SIGINT/SIGTERM)
3. Exit cleanly on signal

### Why script-based (subprocess) rather than importable class

| Concern | Subprocess | In-process (class) |
|---------|------------|-------------------|
| **Multi-language** | policy.py for a TS agent just launches `npx tsx ...` | Only works for Python |
| **Crash isolation** | One agent crashing doesn't kill others | Exception in one thread/process can leak |
| **Simplicity** | `subprocess.Popen(["python", "policy.py", ...])` | Need multiprocessing or threading + import machinery |
| **State leakage** | Impossible (separate process) | Shared interpreter state can cause subtle bugs |
| **Debugging** | Can run any agent standalone: `python agents/X/policy.py --url ... --name ...` | Need the runner harness |
| **Overhead** | One Python process per agent (~10MB) | Lower memory, but irrelevant at our scale |

The subprocess model wins on every axis that matters for this project.
The in-process model only wins if we need sub-millisecond agent
coordination or shared GPU memory, neither of which applies.

### Minimal policy.py (TypeScript wrapper)

```python
#!/usr/bin/env python3
"""Baseline agent -- wraps upstream winner_bot.ts."""
from __future__ import annotations
import argparse, signal, subprocess, sys
from pathlib import Path

AGENT_ID = "baseline"
DESCRIPTION = "Upstream winner_bot.ts -- approach, whisper, role exchange"

_BOT_SCRIPT = Path.home() / "coding/bitworld/persephones_escape/bots/winner_bot.ts"
_BOT_DIR = _BOT_SCRIPT.parent.parent

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--name", required=True)
    args = p.parse_args()

    proc = subprocess.Popen(
        ["npx", "tsx", str(_BOT_SCRIPT), "--name", args.name, "--url", args.url],
        cwd=str(_BOT_DIR),
    )
    signal.signal(signal.SIGINT, lambda *_: proc.send_signal(signal.SIGINT))
    signal.signal(signal.SIGTERM, lambda *_: proc.terminate())
    return proc.wait()

if __name__ == "__main__":
    sys.exit(main())
```

### Minimal policy.py (native Python agent)

```python
#!/usr/bin/env python3
"""Example Python-native agent."""
from __future__ import annotations
import argparse, struct, sys
import websocket  # or websockets

AGENT_ID = "my_agent"
DESCRIPTION = "Custom Python agent with strategic play"

def run(url: str, name: str) -> None:
    ws = websocket.WebSocket()
    ws.connect(f"{url}?name={name}")
    try:
        while True:
            frame = ws.recv()
            if len(frame) != 8192:
                continue
            mask = decide(frame)
            ws.send(struct.pack("BB", 0x00, mask), opcode=0x2)
    except (KeyboardInterrupt, websocket.WebSocketConnectionClosedException):
        pass
    finally:
        ws.close()

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--name", required=True)
    args = p.parse_args()
    run(args.url, args.name)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### Optional metadata

If `policy.py` defines module-level constants, the runner can read them
for `--list` output and logging:

```python
AGENT_ID = "baseline"         # defaults to directory name if absent
DESCRIPTION = "..."           # shown in --list output
```

The runner reads these by importing the module (not executing it).
Since `main()` is gated behind `if __name__ == "__main__"`, importing
is safe and side-effect-free.

---

## Runner Architecture

```
run_agents.py
  |
  |-- parse CLI args
  |-- resolve agent specs -> list of (agent_id, instance_number)
  |-- validate: agents/<id>/policy.py exists for each
  |-- generate unique names: {agent_id}_{instance} (e.g., baseline_1, baseline_2)
  |-- for each agent instance:
  |     launch: python agents/<id>/policy.py --url <url> --name <name>
  |     optionally tee stdout to log file
  |-- wait for all subprocesses
  |-- on SIGINT/SIGTERM: forward to all children, wait, exit
```

### Name Generation

Each instance gets a name: `{agent_id}_{N}` where N is a global
counter across all agents. With `baseline:3 my_agent:2`, the names
would be:

```
baseline_1, baseline_2, baseline_3, my_agent_4, my_agent_5
```

Using a global counter avoids name collisions when mixing agents. The
`--name-prefix` flag can override the agent_id portion if desired.

### Output Handling

By default, all agent stdout/stderr goes to the runner's terminal
(interleaved, prefixed with agent name). With `--log-dir`, each agent's
output goes to `{log_dir}/{name}.log` as well. With `--quiet`, console
output is suppressed but log files still written.

For console output, the runner reads each child's stdout line by line
and prefixes with `[{name}]`. This requires `stdout=PIPE` and a reader
thread per child (or asyncio). A simpler alternative: let children write
directly to the terminal (no prefixing, interleaved output). The
prefixing is nice but adds complexity.

**Recommendation**: Start with direct passthrough (no prefixing).
Children already print their own `[name]` prefixed output (the upstream
bots do this). Add prefixed/structured output later if needed.

---

## What Happened to `agents/baseline/run.py`

Replaced by `agents/baseline/policy.py` which conforms to the contract.
The old `run.py` has been deleted. Standalone invocation:

```
python agents/baseline/policy.py --url ws://localhost:2500/player --name test
```

---

## Filling Games with Bots

A 10-player game needs 10 connections. Common patterns:

```bash
# 3 of our agents + 7 filler bots
python run_agents.py my_agent:3 baseline:7

# All filler (for testing server/infra)
python run_agents.py baseline:10

# One of each agent we have
python run_agents.py baseline my_agent_v2 llm_agent
```

The upstream `bots.ts` (idle bots) and `smart_bots.ts` (random walk)
could also be wrapped as agents if we need dumber filler. But baseline
(winner_bot) is probably fine since it just does its own thing
without interfering with others' strategies.

---

## Future Extensions (not for now)

- **`--fill N`**: Auto-fill remaining slots with baseline agents to
  reach N total players. Requires knowing the config's player count.
- **`--repeat`**: Re-launch agents when the game resets to Lobby
  (for multi-game evaluation runs).
- **`--eval`**: Parse game-over logs after each game and print a
  summary (who won, which exchanges happened).
- **Agent-specific kwargs**: `python run_agents.py "my_agent:3:temperature=0.5"`
  or `--agent-config my_agent=config.json`.

These are natural extensions of the subprocess model and don't require
architectural changes.

---

## Open Questions

1. **Should `--list` import modules or just scan directories?**
   Importing gives access to `DESCRIPTION` metadata. Scanning is
   simpler and avoids import side-effects (though the contract says
   imports should be safe). Recommendation: import, with a try/except
   that falls back to directory name only.

2. **Should the runner wait for all agents or exit when the first one
   dies?** Recommendation: wait for all. If one crashes, print a
   warning but let others continue. Add `--fail-fast` later if needed.

3. **Should we mandate `--url` and `--name` as the only required CLI
   contract, or add optional standard flags?** For example,
   `--kwargs '{"temperature": 0.5}'` for passing agent-specific config.
   Recommendation: start with just `--url` and `--name`. Agents that
   need extra config can define their own flags; the runner passes
   `--url` and `--name` and nothing else. Extend later if a pattern
   emerges.

---

## Summary

The design is:
- **Runner**: `run_agents.py` at project root, takes `agent:count` specs
- **Contract**: `agents/<id>/policy.py`, runnable as
  `python policy.py --url URL --name NAME`
- **Mechanism**: Subprocess per agent instance, signals forwarded, output
  passthrough
- **Discovery**: Scan `agents/*/policy.py`, no registration needed
- **Multi-language**: policy.py can wrap any language's bot via subprocess
