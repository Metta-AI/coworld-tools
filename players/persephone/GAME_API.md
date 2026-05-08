# Persephone's Escape -- Game API Reference

Technical reference for building agents that play Persephone's Escape.
Covers server setup, the wire protocol, observation/action spaces, frame
layout, and agent architecture patterns.

Source: `~/coding/bitworld/persephones_escape/`

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Running the Server](#running-the-server)
3. [Connecting to the Server](#connecting-to-the-server)
4. [Observation Space: Frame Format](#observation-space-frame-format)
5. [Action Space: Sending Input](#action-space-sending-input)
6. [Frame Layout Reference](#frame-layout-reference)
7. [Phase Detection from Pixels](#phase-detection-from-pixels)
8. [Overworld View Details](#overworld-view-details)
9. [Whisper View Details](#whisper-view-details)
10. [Global Chat View Details](#global-chat-view-details)
11. [Info Screen Details](#info-screen-details)
12. [Other Phase Views](#other-phase-views)
13. [Visual Indicators](#visual-indicators)
14. [Text Rendering and OCR](#text-rendering-and-ocr)
15. [Input Sequencing for Menus](#input-sequencing-for-menus)
16. [Agent Architecture Patterns](#agent-architecture-patterns)
17. [Configuration](#configuration)
18. [Source File Index](#source-file-index)

---

## Architecture Overview

```
 Agent (Python/TS)             Server (TypeScript)
 +-----------------+           +------------------+
 | WebSocket       | <-------> | /player endpoint |
 | client          |  frames   | game loop @ 24hz |
 |                 |  -------> |                  |
 |                 |  buttons  | Sim.step()       |
 |                 |  + chat   | render()         |
 +-----------------+           +------------------+
```

The server is a TypeScript WebSocket application
(`persephones_escape/server.ts`). It runs the game simulation (`Sim` class)
at 24 FPS. Each connected player receives a unique 128x128 4-bit pixel
frame per tick, rendered from their perspective. Players send 2-byte button
packets and variable-length chat packets.

There is no structured state API. **Agents see only pixels.** All game
information must be extracted from the rendered frame via pixel parsing, OCR,
and visual pattern recognition. This is the tournament contract.

---

## Running the Server

### Prerequisites

- Node.js 18+ with `tsx` available
- Dependencies installed: `cd ~/coding/bitworld/persephones_escape && npm install`

### Launcher Script (recommended)

The project includes a Python launcher at `scripts/launch_server.py` that
wraps the upstream server with ergonomic defaults:

```bash
# Default: port 2500, random seed, default 10-player config
python scripts/launch_server.py

# Named preset, fixed seed, quiet mode
python scripts/launch_server.py --config simple --seed 42 --quiet

# Inline config tweak (deep-merged with defaults -- no need to repeat roles/rounds)
python scripts/launch_server.py --config-json '{"obstacleCount": 0, "autoGrantWhisperEntry": true}'

# Full custom config file, public binding, logs routed to a directory
python scripts/launch_server.py --config-file my_config.json --public --log-dir ./run_logs
```

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `2500` | Server listen port |
| `--public` | off | Bind `0.0.0.0` instead of `localhost` |
| `--seed` | random | RNG seed (random if omitted, printed for reproducibility) |
| `--config NAME` | none | Named preset (default, simple, empty, tiny, short, empty3, medium) |
| `--config-file PATH` | none | Path to complete JSON config file |
| `--config-json JSON` | none | Inline JSON, deep-merged with defaults |
| `--log-dir DIR` | none | Route game logs and server output to this directory |
| `--replay PATH` | none | Write binary replay file |
| `--quiet` | off | Suppress periodic heartbeat lines |

Config flags are mutually exclusive. If none is given, the server uses
`DEFAULT_GAME_CONFIG` (10 players, 3 rounds of 15s).

### Direct Server Command

For direct access without the wrapper:

```bash
cd ~/coding/bitworld/persephones_escape
npx tsx server.ts --address=localhost --port=8080
```

**CLI flags** (`server.ts:58-68`):

| Flag | Default | Description |
|------|---------|-------------|
| `--address=HOST` | `localhost` | Bind address |
| `--port=PORT` | `8080` | Listen port |
| `--seed=N` | `0xb1770` | RNG seed |
| `--config=NAME` | none | Named config preset |
| `--config-file=PATH` | none | JSON config file |
| `--replay=PATH` | none | Write replay file |

The server prints `Persephone's Escape listening on ws://HOST:PORT/player`
when ready. It accepts player connections on `/player` and global viewer
connections on `/global`.

### Server Logging

The server produces two kinds of output:

1. **Stdout**: periodic heartbeat (`tick=N phase=Phase players=N`) every
   5 seconds, plus startup and game-over messages.

2. **Game-over logs**: written to `logs/{timestamp}/` relative to the
   server's working directory. Contains `full.log` (complete game timeline)
   and per-player logs (`{color}_{shape}.log`) with role, interactions,
   and timeline filtered to that player.

The launcher's `--log-dir` flag routes both to the specified directory
and tees stdout to `{log_dir}/server.log`. In `--quiet` mode, heartbeat
lines are suppressed from the console but still written to the log file.

### Game Configuration

Game configuration is defined in the `GameConfig` interface
(`game/types.ts:120-134`). The default config creates a 10-player game with
3 rounds of 15 seconds each (`game/constants.ts:88-102`). Named presets
are defined in `game/config_presets.ts`.

Notable config fields:

| Field | Type | Description |
|-------|------|-------------|
| `roles` | `RoleEntry[]` | Role composition (role, team, count) |
| `rounds` | `RoundConfig[]` | Per-round duration (secs) and hostage count |
| `obstacleCount` | `number?` | Override obstacles per room (0 = none) |
| `chatMaxCharsPerLine` | `number?` | Message line width (default 29) |
| `actionRateLimits` | `Record<string, number>?` | Per-action cooldowns in ticks |
| `groupNamePrefixInRoomA` | `string?` | Force name-prefix players into RoomA |
| `autoGrantWhisperEntry` | `boolean?` | Auto-grant whisper entry requests |
| `fastTimers` | `boolean?` | Use shortened phase durations for testing |

### Named Presets (`game/config_presets.ts`)

| Preset | Players | Rounds (duration) | Hostages | Obstacles | Notes |
|--------|---------|-------------------|----------|-----------|-------|
| `default` | 10 | 3 (15s / 15s / 15s) | 1 / 1 / 1 | default | Same as DEFAULT_GAME_CONFIG |
| `fast` | 10 | 3 (15s / 15s / 15s) | 1 / 1 / 1 | default | Identical to default |
| `tiny` | 10 | 1 (1s) | 1 | default | Ultra-short smoke test |
| `short` | 10 | 1 (30s) | 1 | default | Quick single-round |
| `empty` | 10 | 1 (30s) | 1 | **0** | No obstacles |
| `simple` | **6** | 1 (60s) | 1 | **0** | No obstacles; LLMs grouped via `groupNamePrefixInRoomA` |
| `empty3` | 10 | 3 (45s / 45s / 45s) | 2 / 2 / 2 | **0** | No obstacles; 2 hostages/round |
| `debug2r` | 10 | 2 (60s / 60s) | 1 / 1 | **0** | No obstacles; explicit 4+4+2 roles |
| `medium` | 10 | 3 (180s / 120s / 60s) | 1 / 1 / 1 | default | Descending duration; realistic play |
| `medium6` | **6** | 3 (180s / 120s / 60s) | 1 / 1 / 1 | default | 6-player medium |
| `medium12` | **12** | 5 (300s / 240s / 180s / 120s / 60s) | 2/2/2/1/1 | default | Large 5-round game |
| `medium12_half` | **12** | 5 (150s / 120s / 90s / 60s / 30s) | 2/2/2/1/1 | default | Half-duration variant |

**Key patterns:**
- The `medium` family uses **descending round durations** — early rounds
  are long (exploration), later rounds are short (urgency).
- Player counts: 6, 10, or 12 (room sizes scale per RULEBOOK).
- Hostage counts: 1 or 2 per round (more hostages = more room churn).
- The `default`/`fast` 15-second rounds are designed for rapid automated
  testing, not representative of realistic play tempo. Agents should be
  robust to both extremes.

---

## Connecting to the Server

### WebSocket Endpoint

```
ws://HOST:PORT/player?name=AGENT_NAME
```

Query parameters (`server.ts:72-73`, also `docs/player_protocol_spec.md:12-29`):

| Param | Required | Description |
|-------|----------|-------------|
| `name` | No | Player identity (spaces replaced with `_`) |
| `slot` | No | Zero-based player slot for stable assignment |
| `token` | No | Join secret for authentication |

### Connection Lifecycle

1. Connect via WebSocket to `/player?name=my_agent`
2. Server adds the player to the sim during the Lobby phase
3. Each tick (~41.7ms at 24 FPS), the server sends one binary frame (8192 bytes)
4. Client sends button packets (2 bytes) and chat packets (variable) as needed
5. On disconnect, the player is removed from the sim

### Python Connection Example

```python
import websocket
import struct

ws = websocket.WebSocket()
ws.connect("ws://localhost:8080/player?name=my_bot")

while True:
    frame_data = ws.recv()  # 8192 bytes, binary
    if len(frame_data) != 8192:
        continue

    # Unpack frame to 128x128 array of 4-bit palette indices
    pixels = unpack_frame(frame_data)

    # Determine action and send button mask
    mask = compute_action(pixels)
    ws.send(struct.pack("BB", 0x00, mask), opcode=0x2)  # binary

    # Optionally send chat
    # ws.send(b"\x01" + b"hello world", opcode=0x2)

def unpack_frame(data: bytes) -> list[int]:
    """Unpack 8192 packed bytes to 16384 4-bit pixel values."""
    pixels = [0] * (128 * 128)
    for i, byte in enumerate(data):
        pixels[i * 2] = byte & 0x0F
        pixels[i * 2 + 1] = (byte >> 4) & 0x0F
    return pixels

ws.close()
```

### TypeScript Connection Example

```typescript
import WebSocket from "ws";

const ws = new WebSocket("ws://localhost:8080/player?name=my_bot");

ws.on("message", (data: Buffer) => {
  if (data.length !== 8192) return;

  // Unpack to 128x128 pixel array
  const pixels = new Uint8Array(128 * 128);
  for (let i = 0; i < 8192; i++) {
    pixels[i * 2] = data[i] & 0x0f;
    pixels[i * 2 + 1] = data[i] >> 4;
  }

  // Send button mask
  const mask = computeAction(pixels);
  ws.send(Buffer.from([0x00, mask]));

  // Send chat message (optional)
  // ws.send(Buffer.concat([Buffer.from([0x01]), Buffer.from("hello")]));
});
```

---

## Observation Space: Frame Format

### Screen Dimensions

- **128 x 128 pixels**, each pixel is a 4-bit index (0--15) into the
  PICO-8 palette
- Constants: `SCREEN_WIDTH = 128`, `SCREEN_HEIGHT = 128`
  (`game/constants.ts:27-28`)

### Wire Format

- **8192 bytes** per frame (`PROTOCOL_BYTES = 128 * 128 / 2`)
- Two pixels packed per byte:
  - **Bits 0--3** (low nibble): left/even pixel
  - **Bits 4--7** (high nibble): right/odd pixel
- Pixels stored left-to-right, top-to-bottom

**Packing** (`rendering/framebuffer.ts:108-115`):
```
packed[i] = indices[i*2] | (indices[i*2 + 1] << 4)
```

**Unpacking**:
```
pixels[i*2]     = packed[i] & 0x0F
pixels[i*2 + 1] = packed[i] >> 4
```

### PICO-8 Color Palette

| Index | Hex | Common Name |
|------:|---------|-------------|
| 0 | `#000000` | Black |
| 1 | `#1d2b53` | Dark blue |
| 2 | `#7e2553` | Dark magenta |
| 3 | `#008751` | Dark green |
| 4 | `#ab5236` | Brown |
| 5 | `#5f574f` | Dark gray |
| 6 | `#c2c3c7` | Light gray |
| 7 | `#fff1e8` | White |
| 8 | `#ff004d` | Red |
| 9 | `#ffa300` | Orange |
| 10 | `#ffec27` | Yellow |
| 11 | `#00e436` | Green |
| 12 | `#29adff` | Blue |
| 13 | `#83769c` | Lavender |
| 14 | `#ff77a8` | Pink |
| 15 | `#ffccaa` | Peach |

### Key Semantic Colors

| Usage | Palette Index | Notes |
|-------|---------------|-------|
| Shades team color | 3 (dark green) | Used for HUD text, role reveal borders, role indicators |
| Nymphs team color | 14 (pink) | Used for HUD text, role reveal borders, role indicators |
| Underworld floor | 12 (blue) | RoomA base floor color |
| Mortal Realm floor | 9 (orange) | RoomB base floor color |
| Walls | 5 (dark gray) | Room boundaries and obstacles |
| HUD text (normal) | 2 (dark magenta) | Round/timer display, headers |
| HUD text (dim) | 1 (dark blue) | Hints, control labels |
| HUD text (alert) | 8 (red) | Hostage select timer, system messages, pending offers |
| Self on minimap | 2 (dark magenta) | Always white appears as palette 2 for the viewer's own dot |

### Player Colors

8 distinct colors assigned by player index (`game/constants.ts:130`):

| Player Index | Palette | In-Game Name |
|:------------:|:-------:|:------------:|
| 0 | 3 | RED |
| 1 | 14 | BLUE |
| 2 | 8 | YELLOW |
| 3 | 10 | GREEN |
| 4 | 7 | ORANGE |
| 5 | 9 | PURPLE |
| 6 | 11 | LIME |
| 7 | 12 | NAVY |

Assignment wraps: player index `i` gets `PLAYER_COLORS[i % 8]`. The
in-game names (`COLOR_NAMES` in `constants.ts:132-134`) are the labels
players see in the UI and should use for identification. **Note**: these
names are game-specific labels and do not necessarily correspond to how
the PICO-8 palette colors appear visually.

### Player Shapes

12 distinct 7x7 pixel shapes, assigned by player index
(`game/types.ts:17`):

Circle, Square, Triangle, Diamond, Star, Cross, X, Heart, Crescent, Bolt,
Hourglass, Ring

Each shape uses a 7x7 pixel pattern where value 1 = outline (black),
value 2 = fill (player color). The shape index is `playerIndex % 12`.

---

## Action Space: Sending Input

### Button Packet (2 bytes)

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x00` | Packet type: PACKET_INPUT |
| 1 | bitmask | Button state |

**Button bitmask** (`game/constants.ts:33-39`):

| Bit | Mask | Button | Game Function |
|----:|-----:|--------|---------------|
| 0 | `0x01` | Up | Move up / scroll up / menu navigate |
| 1 | `0x02` | Down | Move down / scroll down / menu navigate |
| 2 | `0x04` | Left | Move left / menu navigate left / cycle surfaces |
| 3 | `0x08` | Right | Move right / menu navigate right / cycle surfaces |
| 4 | `0x10` | Select (L) | Open shout / exit whisper / close menus / commit in some contexts |
| 5 | `0x20` | A (J) | Create whisper / confirm menu / toggle hostage selection |
| 6 | `0x40` | B (K) | Request whisper entry / open action menu / commit hostages |

**Special mask**: `0xFF` (255) = reset signal. Clears both current and
previous input state.

**Important**: The game detects **button presses** (rising edge), not
held buttons. A "press" is when a button transitions from 0 to 1 between
the current and previous tick. To press a button, you must:

1. Send a frame with the button bit **cleared** (0)
2. Send the next frame with the button bit **set** (1)

Simply holding a button down continuously registers as one press on the
first frame, then nothing. For directional movement, holding works fine
(acceleration continues while held). For menu actions, you need distinct
press-release cycles.

### Chat Packet (variable length)

| Byte | Value | Description |
|------|-------|-------------|
| 0 | `0x01` | Packet type: PACKET_CHAT |
| 1+ | ASCII | Printable ASCII text (0x20--0x7e) |

Chat is context-sensitive (`server.ts:87-97`):
- If in a whisper: message goes to whisper occupants
- If NOT in a whisper: message goes to global room chat

**Important**: chat routing is based on the player's `inWhisper` state,
not whether the global chat UI is "open." An agent in the overworld can
send a global chat message by sending a chat packet even without opening
the global chat view (i.e., without pressing Select). However, the agent
cannot *read* global chat responses without opening the view.

While in a whisper, there is **no way to send a global message**. All
chat packets are routed to the whisper. The agent must exit the whisper
first.

Messages are truncated to `CHAT_MAX_TOTAL = 58` characters (29 per line,
2 lines). Rate-limited: whisper chat at 48 ticks (2 seconds), shout at
240 ticks (10 seconds).

### Discrete Action Mapping (for RL/policy agents)

The standard bitworld action space maps 27 discrete actions to button masks.
This is the mapping used by the mettagrid tournament runner:

```
Action = (direction, button)
  9 directions: none, up, down, left, right, up+left, up+right, down+left, down+right
  3 buttons: none, A, B
  Total: 9 x 3 = 27 actions
```

| Index | Mask | Description |
|------:|-----:|-------------|
| 0 | `0x00` | noop |
| 1 | `0x20` | A |
| 2 | `0x40` | B |
| 3 | `0x01` | up |
| 4 | `0x21` | up + A |
| 5 | `0x41` | up + B |
| 6 | `0x02` | down |
| 7 | `0x22` | down + A |
| 8 | `0x42` | down + B |
| 9 | `0x04` | left |
| 10 | `0x24` | left + A |
| 11 | `0x44` | left + B |
| 12 | `0x08` | right |
| 13 | `0x28` | right + A |
| 14 | `0x48` | right + B |
| 15 | `0x05` | up + left |
| 16 | `0x25` | up + left + A |
| 17 | `0x45` | up + left + B |
| 18 | `0x09` | up + right |
| 19 | `0x29` | up + right + A |
| 20 | `0x49` | up + right + B |
| 21 | `0x06` | down + left |
| 22 | `0x26` | down + left + A |
| 23 | `0x46` | down + left + B |
| 24 | `0x0A` | down + right |
| 25 | `0x2A` | down + right + A |
| 26 | `0x4A` | down + right + B |

**Note: the Select button (`0x10`) is NOT in the 27-action space.** This
is a significant limitation for Persephone's Escape. Features gated behind
Select include:

| Feature | Impact without Select | Workaround |
|---------|----------------------|------------|
| Open global chat (shout) | Cannot read global messages | Shout strip shows last message |
| Send global chat | Cannot open UI | **Chat packet workaround**: send a `PACKET_CHAT` while not in a whisper; server routes it to global regardless of UI state |
| Usurp voting | Cannot vote (requires shout view open) | None |
| Exit whisper (shortcut) | Slower exit only | Use action menu: B → EXIT category → A |
| Close whisper action menu | Cannot close | Must select an action or navigate to EXIT |
| Commit hostage selection | Leader cannot commit early | Use B/K to commit (wait — B IS in the 27-action space, so this IS accessible) |

**This constraint only applies if using the mettagrid runner.** The mettagrid
runner was built for Among Them (Nim) and has no Persephone integration.
Agents connecting directly to the Persephone WebSocket server send raw
2-byte button packets and can include Select (`0x10`) in any mask. A custom
action space that includes Select is strongly recommended for Persephone.

---

## Frame Layout Reference

The 128x128 frame is divided into functional regions depending on the
current view.

### Overworld View (Playing / HostageSelect / LeaderSummit / Lobby phases)

```
+------------------------------------------+
| Top bar (y=0..8, h=9)       | Minimap    |
|  Round/timer (color 2)      | (20x20)    |
|  Role name (team color)     | x=106,y=2  |
+------------------------------+           |
| Game world viewport                      |
|  Camera centered on player               |
|  Fog of war (shadow map)                 |
|  Player sprites (7x7)                    |
|  Obstacles (8x8)                         |
|  Floor with grid dots                    |
|                                          |
+------------------------------------------+
| Shout strip (y=112..118, h=7)            |
|  Last global chat message (Playing only) |
+------------------------------------------+
| Bottom bar (y=119..127, h=9)             |
|  Context hints / menu items              |
+------------------------------------------+
```

**Constants** (`game/constants.ts`):
- `BOTTOM_BAR_H = 9` (pixels from bottom)
- `MINIMAP_SIZE = 20`
- `MINIMAP_X = 106` (`SCREEN_WIDTH - MINIMAP_SIZE - 2`)
- `MINIMAP_Y = 2`

### Whisper View

```
+------------------------------------------+
| Top bar (y=0..8, h=9)                    |
|  "WHISP" text (color 2, x=2,y=2)        |
|  Occupant sprites (x=22+, y=1, stride 9) |
+------------------------------------------+
| Message area (y=10 to y=barY-1)          |
|  Chat messages with sender sprites       |
|  System messages in color 8              |
|  [!] [sprite] WANTS IN (if pending)      |
+------------------------------------------+
| Bottom bar (y=119..127, h=9)             |
|  Default: "H/I:TAB L:EXIT K:ACT"        |
|  Menu open: "(CATEGORY) ACTION"          |
|  Target picker: "ROLE: [sprites]"        |
|  Offer indicators: "R!" or "C!" at right |
+------------------------------------------+
```

### Global Chat View

```
+------------------------------------------+
| Top bar (y=0..8, h=9)                    |
|  "[ROOM_NAME] CHAT" (color 2)            |
+------------------------------------------+
| Usurp/hostage area (y=10+)              |
|  Non-leader: "USURP: [candidate]"        |
|  Leader: hostage selection grid           |
+------------------------------------------+
| Divider line (1px, color 1)              |
+------------------------------------------+
| Message area (to barY-1)                 |
|  Global chat messages                    |
+------------------------------------------+
| Bottom bar (y=119..127, h=9)             |
|  Leader: "J:TOG  K:COMMIT  L:CLOSE"     |
|  Non-leader: "H/I:TAB L:CLOSE K:NEXT"   |
+------------------------------------------+
```

---

## Phase Detection from Pixels

The current game phase can be determined from pixel patterns
(`bots/frame_parser.ts:75-106`):

### Detection Logic

| Phase | Detection Method |
|-------|-----------------|
| **roster_reveal / role_reveal** | Colored border at (0,0) and (2,2) are the same non-zero color; pixel at (4,4) is black. (Panel 0 = roster reveal, panels 1-3 = role reveal; distinguishable by content.) |
| **whisper** | Text "WHISP" at (2,2) in color 2 |
| **waiting_entry** | Text "WAITING" at (2, barY+2) in color 8 |
| **playing** | Text at (2,2) in color 2 starts with "R" and contains ":" |
| **lobby** | Text at (2,2) in color 2 matches `\d+/\d+` pattern |
| **reveal** | Text "REVEAL" at (2,2) in color 2 |
| **hostage_select** | Text "SELECT" at (2,2) in color 8 |
| **leader_summit** | Text at (2,2) in color 1 starts with "LEADERS" |
| **hostage_exchange** | Text "EXCHANGING" at (2,2) in color 8 |
| **info_screen** | Border at (0,0) and (2,2) same color (no inner black) |

Where `barY = SCREEN_HEIGHT - BOTTOM_BAR_H = 119`.

### Pseudo-code

```python
def detect_phase(pixels):
    border0 = pixels[0]
    border2 = pixels[2 * 128 + 2]

    # Role reveal: colored double border with black interior
    if border0 != 0 and border0 == border2:
        if pixels[4 * 128 + 4] == 0:
            return "role_reveal"  # covers both RosterReveal and RoleReveal phases

    # Whisper: "WHISP" header
    if read_text(pixels, 2, 2, color=2).startswith("WHISP"):
        return "whisper"

    # Waiting for whisper entry
    if read_text(pixels, 2, 121, color=8).startswith("WAITING"):
        return "waiting_entry"

    hud_text = read_text(pixels, 2, 2, color=2)
    if hud_text[0:1] == "R" and ":" in hud_text:
        return "playing"
    if re.match(r"\d+/\d+", hud_text):
        return "lobby"
    if hud_text.startswith("REVEAL"):
        return "reveal"

    hud_8 = read_text(pixels, 2, 2, color=8)
    if hud_8.startswith("SELECT"):
        return "hostage_select"
    if hud_8.startswith("EXCHANGING"):
        return "hostage_exchange"

    # Info screen: same-color border without black inner
    if border0 != 0 and border0 == border2:
        return "info_screen"

    return "unknown"
```

**Caveat**: The game font renders `S` and `5` identically, and `O` and `0`
identically (both are 3x5 pixel patterns). Text recognition must normalize
these (`bots/frame_parser.ts:71-72`).

---

## Overworld View Details

### Camera

The camera centers on the player with clamping at room edges
(`rendering/renderer.ts:78-92`):

```
cameraX = clamp(playerCenterX - 64, 0, roomW - 128)
cameraY = clamp(playerCenterY - topBar - visH/2, -topBar, roomH - 128 + botBar)
```

Where `topBar = 9`, `botBar = 9`, `visH = 110`.

A pixel at screen position `(sx, sy)` maps to world position
`(cameraX + sx, cameraY + sy)`.

### Floor Grid Dots

Rooms have a subtle 2x2 pixel dot pattern on a 24-pixel grid
(`game/sim.ts:138-143`). At every `(x, y)` where `x % 24 ∈ {11,12}` and
`y % 24 ∈ {11,12}`, the floor uses an alternate color:

| Room | Base Color | Dot Color |
|------|-----------|-----------|
| Underworld | 12 (blue) | 6 (light gray) |
| Mortal Realm | 9 (orange) | 10 (yellow) |

These dots are dense enough that at least one is always visible in the
viewport, providing a reference for dead-reckoning position estimation.

### Fog of War

During Playing, HostageSelect, and LeaderSummit phases, shadows are cast
from the player's center position via raycasting (`game/sim.ts:201-232`).
Shadowed pixels are darkened using a lookup table (`SHADOW_MAP` in
`constants.ts:120`):

```
SHADOW_MAP = [0, 12, 9, 5, 5, 0, 5, 5, 5, 12, 9, 9, 0, 12, 12, 9]
```

Players in shadow (except self) are hidden from both the viewport and the
minimap. **However**, the shadow buffer is viewport-sized (128x128) and
computed only for camera-visible screen pixels (`sim.ts:231-262`). The
minimap shadow check (`renderer.ts:384-387`) first bounds-checks whether
a player's position falls within the camera viewport; if it does NOT
(player is far away), the shadow lookup is skipped and the player's dot
is **always drawn**. This means:

- Players **inside** the viewport who are behind obstacles: hidden from
  both viewport and minimap.
- Players **outside** the viewport (far away): always visible on the
  minimap regardless of obstacles between them and the viewer.

The result is complementary coverage: the viewport reliably shows nearby
unobstructed players, while the minimap reliably shows distant players.

### Minimap

A 20x20 pixel minimap at the top-right corner
(`rendering/renderer.ts:298-348`):

- Position: `x=106, y=2` with 1-pixel border in color 1
- Background: room floor color
- Obstacles: single dark gray (5) pixel per obstacle
- **Player dots**: 1 pixel each, drawn in player color order with the
  viewer drawn **last** (overwrites others at same position)
- **Self dot**: always color 2 (dark magenta)

**Scaling**: `minimapX = worldX * 20 / roomW`, `minimapY = worldY * 20 / roomH`

**Important**: Because the viewer's dot is drawn last, when you are at the
same minimap cell as another player, your dot covers theirs. This means a
target you're pursuing can "disappear" from the minimap when you're very
close. The reference bot architecture tracks `lastSawTargetTick` to handle
this (`learnings.md:130-137`).

### HUD - Top Bar

During Playing phase (`rendering/renderer.ts:366-383`):
- **Round/Timer**: `R{round} {min}:{sec}` at (2, 2) in color 2
  - Example: `R1 0:15`, `R2 0:03`
- **Role name**: at right edge (before minimap) in team color (3 or 14)
  - Example: `Hades` in color 3, `Persephone` in color 14

### HUD - Bottom Bar

Default (Playing/HostageSelect/LeaderSummit, no menu open):
- `J:NEW  K:JOIN  L:SHOUT` at (2, barY+2) in color 1
- If waiting for whisper entry: `WAITING...` at (2, barY+2) in color 8
- Unread global indicator: blinking green (11) dot at (124, barY+4)
  - Blinks when `tickCount & 16` is true (toggles every 16 ticks)

**Button key**: J = A button, K = B button, L = Select button,
H/I = Left/Right arrows.

### Shout Strip

During Playing and LeaderSummit phases (`rendering/renderer.ts:371-382`):
- Position: `y = barY - 7 = 112` (7 pixels tall, above bottom bar)
- Shows the most recent global chat message
- Left edge: 3 red (8) pixels as a vertical marker at x=0
- Text at x=2 in the sender's player color
- Maximum 29 characters displayed

---

## Whisper View Details

Full-screen view when inside a whisper
(`rendering/renderer.ts:105-196`):

### Top Bar
- `WHISP` at (2, 2) in color 2
- Occupant sprites starting at x=22, stride = `PLAYER_W + 2 = 9`, y=1

### Message Area
- Messages: y=10 to y=barY-1 (barY = 119)
- Line height: 7 pixels
- System messages: color 8 (red), prefixed with player sprite references
- Player messages: sender's sprite at left, text in sender's player color
- Scroll: up/down buttons adjust `chatScrollOffset`

### Pending Entry Indicator
- When someone is requesting entry: drawn at bottom of message area
  - `!` at (2, reqY) in color 8
  - Requester's sprite at (8, reqY)
  - `WANTS IN` at (17, reqY) in color 8
  - `reqY = barY - 8 = 111`

### Bottom Bar Actions

**Default state**: `H/I:TAB L:EXIT K:ACT` in color 1

During LeaderSummit (forced whisper between leaders):
`SUMMIT {secs}S  ENTER:MSG` in color 8

**Summit input restrictions:** During the LeaderSummit phase, the B button
(action menu open) and Select button (exit whisper) are disabled for
players in the summit whisper (`sim.ts:539,544` gate on `!isSummit`). The
summit whisper is created fresh with empty offer sets, so no reactive
offer acceptance is possible either. Available inputs: chat (ENTER), tab
cycling (Left/Right between whisper/shout/info surfaces), message scroll
(Up/Down).

**Pending offer indicators** (steady, not blinking):
- `R!` at (SCREEN_WIDTH - 10, barY + 2) in color 8 = someone offered role exchange
- `C!` at same position in color 8 = someone offered color exchange

**2D Action Menu** (B/K button opens, navigate with d-pad):
- Categories cycle left/right: COLOR, ROLE, LEADER, EXIT
- Items cycle up/down within category
- Display: `(CATEGORY) ACTION` in color 2 (enabled) or 1 (disabled)
- A/J confirms, Select/L closes

**Target Picker** (after selecting C.ACCPT or R.ACCPT):
- `COLOR:` or `ROLE:` label, then offerer sprites with selection box
- Navigate left/right, A confirms, Select cancels

### Whisper Menu Structure

```
COLOR               ROLE               LEADER             EXIT
  C.OFFER/C.UNOFFR    ROLE               PASS               EXIT
  C.ACCPT              R.OFFER/R.UNOFFR   TAKE
                       R.ACCPT            GRANT
```

Defined in `game/menu_defs.ts:42-72`.

---

## Global Chat View Details

Full-screen view for room-wide communication
(`rendering/renderer.ts:198-296`):

### Top Bar
- `{ROOM_NAME} CHAT` at (2, 2) in color 2
  - `Underworld CHAT` or `Mortal Realm CHAT`

### Usurp/Hostage Section (below top bar)

**Non-leader**: Usurp candidate selector
- `USURP:` label at (2, 11) in color 1
- Current candidate (sprite or text like `NONE`, `ME`) at label-right
- Navigate left/right, A/J to cast vote

**Leader during HostageSelect**: Hostage selection grid
- Player sprites in a grid (12x14 cells, max 4 columns)
- Checkmarks (color 11) on selected players
- Cursor box (color 2) around current selection
- `{n}/{total} HOSTAGES` label below grid
- Bottom bar: `J:TOG  K:COMMIT  L:CLOSE`

### Divider
- 1-pixel horizontal line in color 1 separating voting/hostage area from messages

### Message Area
- Global room chat messages below divider
- Same format as whisper messages (sender sprite + text)

---

## Info Screen Details

Accessible by cycling surfaces (Left/Right arrows) while in the shout
or whisper view. Shows known player information
(`rendering/renderer.ts:487-576`):

### "shared" Mode

- Header: `KNOWN PLAYERS` at (2, 2) in color 2
- List starts at y=12, row height = 11 pixels
- Each row: player sprite at x=4, then:
  - **Full role known**: role indicator bar + role name in team color
  - **Color only known**: single team-color dot + `???` in color 1
- Self always first in list
- Scroll with up/down if list exceeds screen
- Scroll indicator on right edge

### Role Indicator Bars

Below each player sprite, a 5x2 pixel bar in team color with special dots
for key roles (`rendering/renderer.ts:60-76`):

| Role | Bar Color | Dots |
|------|-----------|------|
| Hades | 3 (Shades) | Center dot in color 8 (red) |
| Cerberus | 3 (Shades) | Two dots (x+2, x+4) in color 8 |
| Shade | 3 (Shades) | No special dots |
| Persephone | 14 (Nymphs) | Center dot in color 2 (magenta) |
| Demeter | 14 (Nymphs) | Two dots (x+2, x+4) in color 2 |
| Nymph | 14 (Nymphs) | No special dots |

---

## Other Phase Views

### Intro Sequence (RosterReveal + RoleReveal)

The intro is a 4-panel sequence sharing a single 15-second timer. All
panels have a colored double border in the team color at (0,0) and (2,2)
with a black interior (pixel at (4,4) is black). Players navigate with
A/Right (forward) and B/Left (back).

**Panel 0 -- Roster Reveal** (phase = `RosterReveal`):
- Two columns listing players by room (Underworld left, Mortal Realm right)
- Player sprites with character names
- "NEXT IN {secs}" countdown

**Panel 1 -- Role Card** (phase = `RoleReveal`):
- Bordered screen (`rendering/renderer.ts:442-485`):
- Double border in team color at (0,0) and (2,2)
- Black interior
- Centered text top-to-bottom:
  - Player's own sprite
  - `YOU ARE` (color 2)
  - Role name (team color)
  - Team name + ` TEAM` (team color)
  - `ASSIGNED TO` (color 1)
  - Room name (color 2)
  - `{n}P  {w}x{h}` info line (color 1) -- player count and room size
  - Control hints (WASD, J/K/L)
  - `STARTING IN {secs}` (color 2)

**Panel 2 -- Role Summary** (phase = `RoleReveal`):
- Lists all unique role names in the match
- Shows MISSING core roles and active ECHO substitutions
- `STARTING IN {secs}` countdown

**Panel 3 -- Round Schedule** (phase = `RoleReveal`):
- Table: ROUND | TIME | HOSTAGE for each configured round
- Players on this panel can press forward to mark "ready"
- `STARTING IN {secs}` countdown

### Hostage Exchange Screen

(`rendering/renderer.ts:763-828`):
- Title: `HOSTAGE EXCHANGE` at top (color 8)
- Room floor color background
- **LEADER section**: your room's leader sprite.
  If the viewer IS a leader, both rooms' leaders are shown side-by-side
  under the label "LEADERS" (plural). Non-leaders see only their own
  room's leader under "LEADER" (singular).
- **DEPARTING section**: hostages leaving your room — full sprites
  (color + shape for player identification)
- **ARRIVING section**: hostages coming to your room — full sprites
- **Role indicators (likely bug)**: `renderExchangeRow` (line 760) calls
  `drawRoleSlot(p.role, p.team)` unconditionally on all shown sprites.
  Unlike the overworld renderer (which gates on `revealedTo` /
  `colorRevealedTo` at line 957), the exchange screen does NOT check
  whether the viewer has mechanically discovered the player's role. This
  means true role indicators (team color bar + key-role dots) are visible
  for ALL exchange-screen sprites regardless of prior interaction. This
  is inconsistent with the information model and likely unintentional.
- Bottom bar status:
  - `YOU ARE BEING EXCHANGED` (color 8) -- if you are a hostage
  - `ESCORTING HOSTAGES` (color 2) -- if you are a leader
  - `HOSTAGES EXCHANGING...` (color 1) -- otherwise
- Duration: 8 seconds (1 second with `fastTimers`)

### Reveal / Game Over

- Top bar: `REVEAL!` (color 2)
- Center screen: winner text
  - `{TEAM_NAME} WIN!` in team color
  - or `NO ONE WINS!` in color 1

---

## Visual Indicators

In the overworld view, players have various indicators drawn relative to
their sprite position (`rendering/renderer.ts:748-783`):

| Indicator | Pixels | Color | Meaning |
|-----------|--------|-------|---------|
| Crown | 3 dots above sprite at y-2,y-3 + bar at y-1 | 8 (red) | Room leader |
| Hostage mark | Single dot at (cx, y-1) | 3 (green) | Selected as hostage |
| Speech bubble | 3x2 block at (x-3, y-3) + tail at (x, y-1) | 2 (magenta) | In a whisper |
| Pending `?` | Single dot at (cx, y-1), blinking | 8 (red) | Waiting for whisper entry |
| Role indicator | 5x2 bar below sprite | Team color | Visible for self, revealed players, and during Reveal/GameOver |
| Color dot | Single dot below sprite center | Team color | Visible when color-only revealed |

"Blinking" means visible when `tickCount & 8` is true (toggles every 8 ticks).

---

## Text Rendering and OCR

The game uses a built-in 3-wide x 5-tall pixel font
(`rendering/framebuffer.ts:8-58`). Each glyph is rendered as a `#`/`.`
pattern where `#` = foreground pixel, `.` = transparent.

### Font Coverage

Supported characters: `A-Z`, `0-9`, `:`, `!`, `?`, `'`, `.`, `,`, `-`,
`/`, `*`, `(`, `)`, `<`, `>`

**Not supported**: `#`, `@`, `%`, `_`, `+`, `=`, `[`, `]`, lowercase.
Missing characters are silently skipped during rendering.

### Character Metrics

- Glyph width: 3 pixels (all glyphs)
- Glyph height: 5 pixels
- Inter-character gap: 1 pixel
- Space width: 4 pixels
- Effective character cell: 4 pixels wide (3 + 1 gap)

### OCR Ambiguities

~~Two glyph pairs are **pixel-identical** and cannot be distinguished:~~

**Correction**: The game renders **distinct** glyphs for all characters.
The claims below were incorrect and based on an earlier or hypothetical
font. The actual glyphs (from `rendering/framebuffer.ts` and
`common/spriteRecognition.ts`) are:

- `S`: `.##`, `#..`, `.##`, `..#`, `##.` (asymmetric)
- `5`: `###`, `#..`, `###`, `..#`, `###` (symmetric)
- `O`: `###`, `#.#`, `#.#`, `#.#`, `###` (full corners)
- `0`: `.#.`, `#.#`, `#.#`, `#.#`, `.#.` (rounded corners)

These are visually distinct and can be OCR'd unambiguously. No
normalization is required. The `norm()` function in the reference
frame parser (`bots/frame_parser.ts:70-72`) is now a no-op.

Other notable glyphs that differ from naive expectations:
- `M`: `#.#`, `###`, `###`, `#.#`, `#.#` (double-filled middle rows)
- `N`: `###`, `#.#`, `#.#`, `#.#`, `#.#` (full top, straight sides)
- `D`: `##.`, `#.#`, `#.#`, `#.#`, `##.` (rounded right side)

### Reading Text from Pixels

To read text at position (x, y) in a specific color:
1. Filter the frame to only pixels matching the target color
2. Starting at (x, y), try to match each font glyph
3. Advance by glyph width + 1 after each match
4. Spaces are detected as 4 consecutive transparent columns

The reference implementation is in `bots/frame_parser.ts:43-48`, delegating
to `common/spriteRecognition.ts`.

---

## Input Sequencing for Menus

Menu interactions require specific button-press sequences. The game uses
**rising-edge detection** -- an action triggers on the frame where a button
transitions from not-pressed to pressed.

### Overworld Actions

| Action | Button Sequence |
|--------|----------------|
| Create whisper | `A/J` (press then release; must not be near another whisper) |
| Request entry to whisper | `B/K` (press then release; must be near a whisper player) |
| Cancel entry request | `B/K` (while waiting) |
| Open global chat (shout) | `Select/L` (press then release) |

### Chatroom Actions

| Action | Button Sequence |
|--------|----------------|
| Exit whisper | `Select/L` |
| Open action menu | `B/K` |
| Navigate categories | `Left`/`Right` in menu |
| Navigate items | `Up`/`Down` in menu |
| Select item | `A/J` in menu |
| Close action menu | `Select/L` in menu |
| Scroll messages | `Up`/`Down` (when menu closed) |
| Cycle surfaces (whisper/shout/info) | `Left`/`Right` (when menu closed) |

### Menu Sequences (from `game/menu_defs.ts:200-233`)

To execute a whisper action programmatically:

1. Press `B/K` (open menu), release
2. Press `Left`/`Right` to reach target category, release between presses
3. Press `Up`/`Down` to reach target item, release between presses
4. Press `A/J` (confirm), release
5. For `R.ACCPT` / `C.ACCPT`: press `A/J` again to confirm target picker

**Example**: Execute R.OFFER (category 1 "ROLE", item 1):
```
B, 0, Right, 0, Down, 0, A, 0
```

Where `0` means "send mask 0x00" (all buttons released) for one frame.
B = `0x40`, A = `0x20`, Right = `0x08`, Down = `0x02`.

**Example**: Execute R.ACCPT with auto-target (category 1, item 2):
```
B, 0, Right, 0, Down, 0, Down, 0, A, 0, A, 0
```

The extra trailing `A, 0` confirms the first offerer in the target picker.

### Global Chat Actions

| Action | Button Sequence |
|--------|----------------|
| Close global chat | `Select/L` |
| Scroll messages | `Up`/`Down` |
| Cast usurp vote | `Left`/`Right` to navigate candidates, `A/J` to vote |
| Toggle hostage (leader) | `A/J` |
| Commit hostages (leader) | `B/K` |

### Critical Timing Notes

1. **One frame per button transition.** Never combine a press and release
   in the same frame. Always alternate between mask-with-bit-set and
   mask-zero.

2. **Menu state is not directly observable.** The menu open/closed state
   must be tracked by the agent. If a sequence is interrupted (e.g., by a
   phase change), the menu may be left in an unexpected state.

3. **The B button in whispers is a toggle.** If the action menu is already
   open, pressing B closes it instead of opening it. Sequences must assume
   the menu starts closed. (`learnings.md:148-156`)

4. **Rate limiting.** Whisper actions have a 48-tick (2-second) cooldown
   by default. Shout messages have a 240-tick (10-second) cooldown.
   Sending the same action faster will be silently dropped.

---

## Agent Architecture Patterns

Based on the reference LLM bot implementation and documented learnings
(`learnings.md`).

### Key Constraints

1. **LLM latency >> tick time.** At 24 FPS, a tick is ~42ms. LLM calls
   take 500--1500ms. The agent cannot query an LLM every tick.

2. **Pixel-only observation.** No structured state. Frame parsing is
   required and error-prone (OCR ambiguities, fog of war, sprite
   occlusion).

3. **Button input only.** No direct API calls. All game actions must be
   expressed as sequences of button presses.

### Recommended Architecture: Task List + Event Buffer

The working architecture from the reference bot (`bots/tasks.ts`):

```
LLM/Policy
  |
  | emits { clear: "all"|"non_loop", append: [tasks...] }
  v
Task Queue
  |
  | tasks execute frame-by-frame
  v
Button Mask Output (per-frame)
```

**Task categories**:
- **ONCE**: fire one action, self-remove (e.g., `shout`, `chat`, `exit_whisper`)
- **SEQUENCE**: multi-frame, self-terminate on success/failure/timeout (e.g.,
  `walk_to`, `pursue_chat`, `pursue_exchange`)
- **LOOP**: persistent reactive behavior, singleton per kind (e.g.,
  `loop_auto_grant`, `loop_auto_accept_role`, `loop_auto_accept_color`)

**Phase routing**: The executor (not the LLM) handles phase-appropriate
behavior. Movement tasks skip in whisper; whisper tasks skip in overworld.
This prevents the LLM from needing to reason about phase transitions.

**Event buffer**: Every task lifecycle event (started, fired, succeeded,
failed, replaced) is logged and included in the next LLM prompt, then
flushed. This gives the LLM visibility into what actually happened.

### Coordination Patterns

**"Stupid meetup protocol"** (`learnings.md:116-125`):
- Each agent shouts a fixed coordinate via global chat (e.g., "meet at 50 50")
- All allies set `walk_to(50, 50)` + `pursue_exchange(partner_color, "role")`
- First to arrive creates a whisper; others request entry
- `loop_auto_grant` handles entry grants
- Role exchange happens inside the whisper

This beats sophisticated pursuit because:
- The minimap self-dot overwrites others at the same cell
- Fog of war makes direct tracking unreliable
- Convergence to a known point is simpler than mutual tracking

### Useful Config for Testing

```json
{
  "obstacleCount": 0,
  "autoGrantWhisperEntry": true,
  "groupNamePrefixInRoomA": "bot_"
}
```

- `obstacleCount: 0` removes pathfinding complexity
- `autoGrantWhisperEntry: true` removes the GRANT dance
- `groupNamePrefixInRoomA` ensures agents share a room

---

## Configuration

### GameConfig Interface

```typescript
interface GameConfig {
  roles: RoleEntry[];           // Role composition
  rounds: RoundConfig[];        // Per-round settings
  obstacleCount?: number;       // 0 = no obstacles
  chatMaxCharsPerLine?: number; // Default 29
  actionRateLimits?: Record<string, number>;  // Ticks per action
  groupNamePrefixInRoomA?: string;  // Force prefix players to RoomA
  autoGrantWhisperEntry?: boolean;  // Auto-grant entry requests
  fastTimers?: boolean;         // Short phase durations for testing
}

interface RoleEntry {
  role: Role;   // Hades | Persephone | Cerberus | Demeter | Shades | Nymphs | Spy | EchoOfHades | EchoOfPersephone | EchoOfCerberus | EchoOfDemeter
  team: Team;   // TeamA (Shades) | TeamB (Nymphs)
  count: number;
}

interface RoundConfig {
  durationSecs: number;  // Round duration in seconds
  hostages: number;      // Hostages per room this round
}
```

### Default Config

```typescript
{
  roles: [
    { role: Role.Hades,      team: Team.TeamA, count: 1 },
    { role: Role.Persephone, team: Team.TeamB, count: 1 },
    { role: Role.Cerberus,   team: Team.TeamA, count: 1 },
    { role: Role.Demeter,    team: Team.TeamB, count: 1 },
    { role: Role.Shades,     team: Team.TeamA, count: 3 },
    { role: Role.Nymphs,     team: Team.TeamB, count: 3 },
  ],
  rounds: [
    { durationSecs: 15, hostages: 1 },
    { durationSecs: 15, hostages: 1 },
    { durationSecs: 15, hostages: 1 },
  ],
}
```

### LLM Role Assignment Bias

The sim assigns LLM-prefixed players (`name.startsWith("llm_")`) to
TeamA roles first (`game/sim.ts:1091-1124`). This ensures LLM bots
preferentially receive Shades team key roles during testing.

---

## Source File Index

### Game Logic

| File | Lines | Description |
|------|------:|-------------|
| `game/sim.ts` | 1566 | Complete game simulation: physics, input, whispers, exchange, win condition |
| `game/types.ts` | 134 | Type definitions: Phase, Team, Role, Room, Player, Chatroom, Config |
| `game/constants.ts` | 178 | All constants: screen, physics, colors, shapes, default config |
| `game/protocol.ts` | 41 | Input/chat packet encoding and decoding |
| `game/menu_defs.ts` | 253 | Menu system: 1D and 2D navigation, button sequences |
| `game/util.ts` | ~30 | Math utilities (clamp, distSq, chat coalescing) |

### Rendering

| File | Lines | Description |
|------|------:|-------------|
| `rendering/renderer.ts` | 794 | Per-player 128x128 frame rendering (all views) |
| `rendering/framebuffer.ts` | 276 | Pixel buffer, font, region system |
| `rendering/globalViewer.ts` | ~666 | Spectator view (sprite protocol, not pixels) |

### Server

| File | Lines | Description |
|------|------:|-------------|
| `server.ts` | 212 | WebSocket server, game loop, client management, replay recording |
| `replay.ts` | ~100 | Replay file recording |

### Reference Bots

| File | Lines | Description |
|------|------:|-------------|
| `bots/frame_parser.ts` | 547 | OCR/pixel parsing: phase detection, HUD, minimap, whisper status |
| `bots/tasks.ts` | ~500 | Task definitions, executor, event buffer |
| `bots/belief_state.ts` | ~300 | Accumulated world knowledge from frame parsing |
| `bots/bot_utils.ts` | ~200 | Movement, pathfinding, input helpers |
| `bots/llm_bot.ts` | ~400 | LLM-driven bot (Claude Haiku via Bedrock) |
| `bots/winner_bot.ts` | ~150 | Hardcoded policy: approach, whisper, offer exchange, accept all |
| `bots/smart_bots.ts` | ~100 | Random-walk filler bots with menu interaction |

### Documentation

| File | Description |
|------|-------------|
| `RULES.md` | Game rules |
| `GUIDE.md` | Interface and controls guide |
| `learnings.md` | LLM agent architecture notes and failure modes |

### Protocol Specs (bitworld-level)

| File | Description |
|------|-------------|
| `~/coding/bitworld/docs/player_protocol_spec.md` | Bitscreen protocol: frame format, button/chat packets |
| `~/coding/bitworld/docs/global_protocol_spec.md` | Global viewer sprite protocol |
| `~/coding/bitworld/docs/reward_protocol_spec.md` | Reward stream format |
