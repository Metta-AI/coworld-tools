# Persephone Agent Workshop

Building and testing agents for **Persephone's Escape**, a digital Two
Rooms and a Boom variant from the
[bitworld](~/coding/bitworld/persephones_escape/) engine.

Agents connect to the game server via WebSocket, receive 128x128 4-bit
pixel frames at 24 FPS, and send button-mask + chat-text packets. There
is no structured state API -- everything must be extracted from pixels.

## Reference Documents

### [RULEBOOK.md](RULEBOOK.md) -- Game Rules

Complete rules for Persephone's Escape. Two teams (Shades and Nymphs,
5 players each in the default 10-player config) are split across two
disjoint rooms (Underworld and Mortal Realm). Over three 15-second
rounds, players communicate in private chatrooms and global room chat to
discover identities. Between rounds, room leaders select hostages to swap
between rooms. Victory requires the team's key role pair to complete a
mutual role exchange (R.OFFER + R.ACCPT) inside a chatroom -- the only
mechanic that counts toward the win condition. If Hades and Persephone
end in the same room, Shades get tiebreaker priority; otherwise Nymphs
do. If neither team's key pair exchanged, nobody wins. Players may lie
in chat but mechanically revealed information is always truthful.

### [GAME_API.md](GAME_API.md) -- Technical API Reference

Everything needed to build an agent. The server is a TypeScript
WebSocket app (`tsx server.ts --port=8080`). Agents connect to
`ws://HOST:PORT/player?name=NAME` and receive 8192-byte binary frames
(two 4-bit PICO-8 palette pixels packed per byte). Input is a 2-byte
button packet (7-bit mask: up/down/left/right/select/A/B) plus optional
ASCII chat packets. The doc covers frame layout for every view
(overworld with minimap and fog of war, whisper rooms, global chat, info
screen, role reveal, hostage exchange), phase detection from pixel
patterns, the full chatroom menu structure with button sequences, OCR
details (3x5 font, all characters distinct), and agent architecture
patterns (task-list + event-buffer approach from the reference LLM bot).
Key gotcha: the standard 27-action bitworld space omits Select, which
gates global chat access, usurp voting, and hostage commit -- direct
WebSocket agents should use the full 7-button mask.

### [AGENT_DESIGN_NOTES.md](AGENT_DESIGN_NOTES.md) -- Institutional Knowledge

Accumulated technical and strategic insights from building and testing
agents. Updated as we learn what works, what fails, and why. Consult
this before starting new agent work.

## Scripts

### `run_agents.py` -- Universal Agent Runner

Launches any combination of registered agents against a game server.
Agents are discovered automatically from `agents/*/policy.py`.

```bash
python run_agents.py baseline              # one baseline agent
python run_agents.py baseline:3            # three instances
python run_agents.py baseline:3 my_agent   # mixed
python run_agents.py --list                # show registered agents
python run_agents.py --port 9090 baseline:6
```

Each agent instance runs as a separate subprocess with a unique name.
Output is prefixed with `[name]`. Use `--log-dir` to write per-agent
logs and `--quiet` to suppress console output.

### `scripts/launch_server.py` -- Server Launcher

Wraps the upstream Persephone server with ergonomic defaults (port 2500,
random seed with printback, inline JSON config with deep-merge, log
routing, quiet mode). See [GAME_API.md](GAME_API.md) for full flag
reference.

```bash
python scripts/launch_server.py                          # defaults
python scripts/launch_server.py --config simple --seed 42 --quiet
python scripts/launch_server.py --config-json '{"obstacleCount": 0}'
```

### `scripts/capture.py` -- Frame Capture Client

Connects to a game server via WebSocket, records all frames to `.npy`,
and writes per-frame metadata (detected view, tick, wall time) to
`.jsonl`. Optionally auto-launches the server and filler bots.

```bash
# Passive capture against a running server
python scripts/capture.py --duration 30 --output /tmp/capture

# Auto-launch server with fillers
python scripts/capture.py --launch-server --seed 42 --fillers 9 \
    --duration 45 --output /tmp/capture

# With a scripted policy (press B at tick 510)
python scripts/capture.py --launch-server --seed 42 --fillers 9 \
    --duration 25 --policy "0x40 if tick == 510 else 0x00" \
    --output /tmp/capture
```

### `scripts/view_timeline.py` -- View Timeline Viewer

Summarizes view transitions from a capture metadata file.

```bash
python scripts/view_timeline.py /tmp/capture.jsonl --counts
```

### `scripts/extract_fixture.py` -- Fixture Extractor

Extracts a single frame from a capture as a test fixture pair (`.npy` +
`.json` with draft assertions from `parse_frame()`).

```bash
python scripts/extract_fixture.py --input /tmp/capture.npy \
    --tick 200 --name role_reveal_shades --seed 42
```

### `scripts/render_frame.py` -- Frame Renderer

Renders a `.npy` frame to PNG using the PICO-8 palette for visual
inspection.

```bash
python scripts/render_frame.py tests/fixtures/playing_round1.npy \
    --scale 4 -o /tmp/frame.png
```

## Writing a New Agent

Create a directory under `agents/` with a `policy.py` file:

```
agents/my_agent/
  policy.py      # required -- must accept --url and --name
  README.md      # optional
```

The `policy.py` contract:
- Runnable as `python agents/my_agent/policy.py --url URL --name NAME`
- Connects to the server, plays until disconnected or interrupted
- Exits cleanly on SIGINT/SIGTERM
- Optional module-level `AGENT_ID` and `DESCRIPTION` constants for
  metadata (shown by `run_agents.py --list`)

### Perception Module

Python agents can use the shared `perception/` module for frame parsing:

```python
from perception import parse_frame
from perception.types import View

result = parse_frame(raw_frame_bytes)
if result.view == View.PLAYING:
    for dot in result.overworld.minimap_dots:
        print(f"Player at ({dot.world_x}, {dot.world_y})")
```

Stateless, single-frame-in / symbolic-out. Handles all game views:
lobby, role reveal, playing, hostage select, leader summit, hostage
exchange, whisper (private chatroom), global chat (shout), info screen,
waiting entry, reveal, and game over. See
[docs/DESIGN_perception.md](docs/DESIGN_perception.md) for the full
design and `perception/types.py` for output dataclass definitions.

#### Testing the Perception Module

The perception module has a live-frame integration test suite. Fixtures
are real frames captured from a running game server, stored in
`tests/fixtures/`. Run with:

```bash
PYTHONPATH=persephone .venv/bin/python -m pytest persephone/tests/ -v
```

To capture new frames and add fixtures:

```bash
# Capture frames from a live game
.venv/bin/python persephone/scripts/capture.py \
    --launch-server --seed 42 --fillers 9 --duration 30 \
    --output /tmp/capture

# View the timeline of detected views
.venv/bin/python persephone/scripts/view_timeline.py /tmp/capture.jsonl

# Extract a specific frame as a test fixture
.venv/bin/python persephone/scripts/extract_fixture.py \
    --input /tmp/capture.npy --tick 200 --name my_fixture

# Render a frame to PNG for visual inspection
.venv/bin/python persephone/scripts/render_frame.py \
    persephone/tests/fixtures/my_fixture.npy --scale 4 -o /tmp/frame.png
```

## Agents

### [baseline](agents/baseline/)

**Description**: Thin wrapper around the upstream `winner_bot.ts` from
the bitworld repo. Hardcoded policy: approach nearest player, open
chatroom, offer role exchange to everyone, accept all offers. No
strategy, no deception, no team awareness. Uses the full upstream
frame-parsing pipeline (minimap, phase detection, position estimation,
chatroom status). Serves as the reference baseline for comparison.

**Results**: *No test results yet.*

### [orpheus](agents/orpheus/)

**Description**: LLM-driven dual-loop agent. A fast loop (24 FPS)
handles perceive -> update belief -> act, where the action depends on
the currently active "task." A separate, slower background loop queries
an LLM with the belief state to set which task the fast loop executes.
Tasks are coarse-grained multi-frame behaviors (explore, pursue player,
open chatroom, execute menu sequences, etc.) so the LLM reasons at
the strategic level while the fast loop handles frame-level execution.
The `chat_and_observe` task blocks the fast loop to synchronously
generate chat via LLM. Includes a full JSONL tracing system for
post-mortem debugging. LLM provider is configurable (Anthropic, OpenAI,
Bedrock, or a deterministic stub for testing).

**Results**: *No test results yet.*
