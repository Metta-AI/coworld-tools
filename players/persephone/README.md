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
rounds, players communicate in private whispers and global room chat to
discover identities. Between rounds, room leaders select hostages to swap
between rooms (meeting briefly in a private summit first). Victory
requires the team's key role pair to complete a mutual role exchange
(R.OFFER + R.ACCPT) inside a whisper -- the only mechanic that counts
toward the win condition. If Hades and Persephone end in the same room,
Shades get tiebreaker priority; otherwise Nymphs do. If neither team's
key pair exchanged, nobody wins. Players may lie in chat but mechanically
revealed information is always truthful.

### [GAME_API.md](GAME_API.md) -- Technical API Reference

Everything needed to build an agent. The server is a TypeScript
WebSocket app (`tsx server.ts --port=8080`). Agents connect to
`ws://HOST:PORT/player?name=NAME` and receive 8192-byte binary frames
(two 4-bit PICO-8 palette pixels packed per byte). Input is a 2-byte
button packet (7-bit mask: up/down/left/right/select/A/B) plus optional
ASCII chat packets. The doc covers frame layout for every view
(overworld with minimap and fog of war, whisper rooms, global chat, info
screen, roster reveal, role reveal, hostage exchange), phase detection
from pixel patterns, the full whisper menu structure with button
sequences, OCR details (3x5 font, all characters distinct), and agent
architecture patterns (task-list + event-buffer approach from the
reference LLM bot). Key gotcha: the standard 27-action bitworld space
omits Select, which gates global chat access, usurp voting, and whisper
exit -- direct WebSocket agents should use the full 7-button mask.

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

### Standalone agents (raw policy)

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

### Orpheus-based agents

Agents built on the Orpheus framework define modes and a `meta_decide`
function rather than a raw policy loop. See
[orpheus/README.md](orpheus/README.md) for an overview and
[orpheus/DESIGN.md](orpheus/DESIGN.md) for the full specification.
(Implementation not yet available — design phase.)

### Perception Module

Python agents can use the perception module (now at
`orpheus/perception/`) for frame parsing:

```python
from orpheus.perception import parse_frame
from orpheus.perception.types import View

result = parse_frame(raw_frame_bytes)
if result.view == View.PLAYING:
    for dot in result.overworld.minimap_dots:
        print(f"Player at ({dot.world_x}, {dot.world_y})")
```

Stateless, single-frame-in / symbolic-out. Handles all game views:
lobby, roster reveal, role reveal, playing, hostage select, leader
summit, hostage exchange, whisper (private chat), global chat (shout),
info screen, waiting entry, reveal, and game over. See
[docs/DESIGN_perception.md](docs/DESIGN_perception.md) for the full
design and `orpheus/perception/types.py` for output dataclass
definitions.

#### Testing the Perception Module

The perception module has a live-frame integration test suite. Fixtures
are real frames captured from a running game server, stored in
`tests/fixtures/`. Run with:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
```

**Note**: test imports currently reference the old `perception` path and
need updating to `orpheus.perception`. See TODO.md.

To capture new frames and add fixtures:

```bash
# Capture frames from a live game
.venv/bin/python scripts/capture.py \
    --launch-server --seed 42 --fillers 9 --duration 30 \
    --output /tmp/capture

# View the timeline of detected views
.venv/bin/python scripts/view_timeline.py /tmp/capture.jsonl

# Extract a specific frame as a test fixture
.venv/bin/python scripts/extract_fixture.py \
    --input /tmp/capture.npy --tick 200 --name my_fixture

# Render a frame to PNG for visual inspection
.venv/bin/python scripts/render_frame.py \
    tests/fixtures/my_fixture.npy --scale 4 -o /tmp/frame.png
```

## Agents

### [Orpheus framework](orpheus/)

Agent framework (design phase). Provides perception, belief state,
task execution, a hook system, and an async outer loop for mode
selection. Agents built on Orpheus define modes and a `meta_decide`
function rather than a raw `policy.py`. See
[orpheus/DESIGN.md](orpheus/DESIGN.md) for the full specification.

### [baseline](agents/baseline/)

**Description**: Thin wrapper around the upstream `winner_bot.ts` from
the bitworld repo. Hardcoded policy: approach nearest player, open
whisper, offer role exchange to everyone, accept all offers. No
strategy, no deception, no team awareness. Uses the full upstream
frame-parsing pipeline (minimap, phase detection, position estimation,
whisper status). Serves as the reference baseline for comparison.

**Results**: *No test results yet.*


