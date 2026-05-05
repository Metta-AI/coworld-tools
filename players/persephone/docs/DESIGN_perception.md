# Perception Utility -- Design Report

Stateless function: one raw pixel frame in, one structured symbolic
representation out. No memory, no belief state, no history. Agents
compose this with their own state tracking.

---

## Scope

The perception module is responsible for:

1. Unpacking a raw 8192-byte frame into a 128x128 pixel array
2. Detecting which view/phase is currently displayed
3. Extracting all visible information from the detected view
4. Returning a single structured object

It is NOT responsible for:
- Tracking changes across frames (that's belief state)
- Making decisions (that's policy)
- Maintaining any mutable state between calls

---

## Output Structure

```python
@dataclass
class FramePerception:
    """Complete symbolic representation of a single frame."""

    # Which view is displayed. Determines which sub-view field is populated.
    view: View  # enum

    # Exactly one of these is populated, based on view.
    overworld: OverworldPerception | None
    chatroom: ChatroomPerception | None
    global_chat: GlobalChatPerception | None
    info_screen: InfoScreenPerception | None
    role_reveal: RoleRevealPerception | None
    exchange: ExchangePerception | None
    result: ResultPerception | None       # Reveal + GameOver
    lobby: LobbyPerception | None

    # Raw frame data, retained for downstream consumers that need pixels.
    raw_pixels: np.ndarray  # (128, 128) uint8, values 0-15
```

---

## View Enum and Detection

```python
class View(Enum):
    ROLE_REVEAL = "role_reveal"
    LOBBY = "lobby"
    PLAYING = "playing"
    HOSTAGE_SELECT = "hostage_select"
    LEADER_SUMMIT = "leader_summit"
    HOSTAGE_EXCHANGE = "hostage_exchange"
    WHISPER = "whisper"
    WAITING_ENTRY = "waiting_entry"
    GLOBAL_CHAT = "global_chat"
    INFO_SCREEN = "info_screen"
    REVEAL = "reveal"
    GAME_OVER = "game_over"
    UNKNOWN = "unknown"
```

### Detection Algorithm

Views are detected by checking pixel patterns at known positions. The
checks are ordered to resolve ambiguities (some views share visual
elements). This ordering is informed by the upstream `parsePhase` in
`bots/frame_parser.ts:74-111`.

```
1. Check for double border (role reveal / info screen):
   border0 = pixels[0, 0]
   border2 = pixels[2, 2]
   if border0 != 0 and border0 == border2:
     if pixels[4, 4] == 0:  → ROLE_REVEAL  (black interior = intro screen)
     else:                  → INFO_SCREEN   (non-black interior = info view)

2. Read text at (2, 2) in color 2:
   if starts with "WHISP":  → WHISPER
   if starts with "KNOWN":  → INFO_SCREEN  (shared mode, no border)

3. Check bottom bar for "WAITING" at (2, 121) in color 8:
   if match:               → WAITING_ENTRY

4. Continue with text at (2, 2) in color 2:
   if matches "R\d .*:":   → PLAYING
   if matches "\d+/\d+":   → LOBBY
   if starts with "REVEAL": → REVEAL

5. Read text at (2, 2) in color 8:
   if starts with "SELECT": → HOSTAGE_SELECT
   if starts with "EXCHANGING": → HOSTAGE_EXCHANGE

5b. Check for centered "HOSTAGE EXCHANGE" at y=14, color 8:
    (The exchange screen renders the title centered, not at x=2)
    if found:              → HOSTAGE_EXCHANGE

6. Read text at (2, 2) in color 1:
   if contains "PICK":      → HOSTAGE_SELECT (non-leader variant)

7. Check for global chat/shout:
   Read text at (2, 2) in color 2. If it ends with "CHAT" or "SHOUT"
   and is longer than 4 chars:
   → GLOBAL_CHAT
   (e.g., "Underworld SHOUT" or "Mortal Realm CHAT")

7.5. Leader summit (reuses dim text from step 6):
   if starts with "LEADERS": → LEADER_SUMMIT

8. Check for game over (win text centered at y=60):
   Scan multiple x offsets at y=60 in team colors (3, 14) and draw
   color (1). If "WIN" or "ONE" found:
   → GAME_OVER

9. Fallback: → UNKNOWN
```

### Notes on Detection

- The game has no "CHATROOM" view -- all private conversations use the
  "whisper" view with "WHISP" header text.
- Global chat uses "SHOUT" as the header suffix in current game versions
  (not "CHAT" as documented in older references). The detector handles both.
- The hostage exchange screen renders its title CENTERED at y=14 (not at
  x=2 like other HUD text), requiring a multi-x-offset scan.
- The leader summit phase ("LEADERS MEET {n}S" in dim text) is detected
  as its own `LEADER_SUMMIT` view. Non-leaders cannot act during this
  phase; agents should treat it as a wait state. The overworld parser
  still runs for this view (minimap, position, etc. are all visible).

### Waiting Entry as a Sub-state

`WAITING_ENTRY` is technically the overworld view with a special bottom
bar. The game world, minimap, and top bar HUD are all still rendered.
Our parser detects this as its own view enum value (agents need to
know not to press buttons that would cancel the entry request), but the
overworld data (minimap, position, etc.) is still extractable from the
frame and is included.

**Design decision**: `WAITING_ENTRY` populates BOTH `view` (as the enum)
AND `overworld` (with the extractable overworld data). This lets agents
handle the waiting state specially while still having access to spatial
information.

---

## View 1: Overworld (Playing / HostageSelect / LeaderSummit)

Active during `PLAYING`, `HOSTAGE_SELECT`, `LEADER_SUMMIT`, and `WAITING_ENTRY` views.

### Layout

```
y=0..8:     Top bar (HUD)          | y=2..21: Minimap (20x20)
y=9..111:   Game world viewport    |          at x=106..125
y=112..118: Shout strip (Playing)  |
y=119..127: Bottom bar             |
```

### Extractable Components

```python
@dataclass
class OverworldPerception:
    # HUD
    round: int | None           # 1-indexed round number (from "R{n}")
    timer_secs: int | None      # Seconds remaining (from "M:SS")
    role_name: str | None       # Own role name (from right side of top bar)
    role_team_color: int | None # Palette index of role text (3=Shades, 14=Nymphs)

    # Phase-specific top bar (HostageSelect)
    hostage_select_secs: int | None   # Timer shown during hostage select
    is_leader_selecting: bool         # True if "SELECT" in color 8 (we are leader)

    # Minimap
    minimap_dots: list[MinimapDot]    # All non-background dots on the minimap

    # Position (derived from minimap self-dot + floor grid dots)
    self_position: Position | None

    # Room detection (from floor colors near screen center)
    room: Room | None

    # Shout strip (only during Playing)
    last_shout: str | None            # Text from the shout strip
    last_shout_color: int | None      # Sender's player color

    # Bottom bar state
    bottom_bar: OverworldBottomBar

    # Nearby player indicators (speech bubbles, pending entry blinks)
    speech_bubbles: list[SpeechBubble]

@dataclass
class MinimapDot:
    color: int          # Palette index
    minimap_x: int      # 0-19, position within minimap
    minimap_y: int      # 0-19
    world_x: int        # Estimated world coordinate
    world_y: int        # Estimated world coordinate
    is_self: bool       # True if color == 2

@dataclass
class Position:
    room: Room          # RoomA or RoomB
    x: int              # World pixel coordinate
    y: int              # World pixel coordinate

class Room(Enum):
    UNDERWORLD = "underworld"   # RoomA, floor color 12
    MORTAL_REALM = "mortal_realm"  # RoomB, floor color 9

@dataclass
class SpeechBubble:
    screen_x: int       # Top-left x of the player sprite (not the bubble)
    screen_y: int       # Top-left y of the player sprite
    player_color: int   # Color read from sprite center pixel

class BottomBarState(Enum):
    DEFAULT = "default"           # "J:CHAT  K:INFO  L:MENU"
    WAITING = "waiting"           # "WAITING..."
    COMM_MENU = "comm_menu"       # "< SHOUT >" or "< INFO >"

@dataclass
class OverworldBottomBar:
    state: BottomBarState
    comm_menu_item: str | None    # Current item text if comm menu is open
    has_unread_global: bool       # True if green dot at (124, 123)
```

### Pixel Details

**Room detection**: Sample a 13x13 area centered on screen at
`(64, floor((128 + 9 - 9) / 2))` = `(64, 64)`. Count floor-color
pixels: RoomA colors are 12 (base) and 6 (dot), RoomB colors are 9
(base) and 10 (dot). Whichever has more wins (threshold >= 5).

**Minimap scanning**: Read the 20x20 pixel region at (106, 2) through
(125, 21). Exclude colors 0 (black), 1 (border), 5 (obstacles), and
the room's base floor color (12 for Underworld, 9 for Mortal Realm).
Color 2 = self dot. All other non-excluded colors are other player dots.

**Position estimation** (from upstream `bot_utils.ts:readPosition`):
1. Get coarse position from minimap self-dot: `world_x ≈ dot_mx * (roomW / 20) + cellW/2`
2. Find a 2x2 floor grid dot on screen (alt color: 6 for RoomA, 10 for RoomB)
3. Use the known 24-pixel grid to compute exact camera offset
4. Derive player position from camera + screen center

**Shout strip**: At y=112. Check for color-8 marker pixels at x=0,
y in [112, 114]. If found, scan for non-zero non-8 colored text at
(2, 112). The text color is the sender's player color.

**Speech bubbles**: Scan the game world area (y=9 to y=111, x=0 to
x=105 to avoid minimap) for the 3x2+1 pattern in color 2:
```
row y:   2 2 2 ≠2
row y+1: 2 2 2 ≠2
row y+2: ≠2 ≠2 ≠2 2
```
Player sprite is at (pattern_x + 3, pattern_y + 3). Read center pixel
at (+3, +3) offset for the player's color.

**Unread global dot**: Check pixel at (124, 123). If color == 11
(bright green), unread messages exist. Note this blinks (16 ticks
on/off), so a single frame may miss it. The perception module reports
what's visible in this frame; the agent should track across frames if
it needs reliable unread detection.

---

## View 2: Chatroom

### Layout

```
y=0..8:     Header ("CHAT" + occupant sprites)
y=10..118:  Message area
y=111..118: Pending entry indicator (overlays messages, when present)
y=119..127: Bottom bar (actions / menu / target picker)
```

### Extractable Components

```python
@dataclass
class ChatroomPerception:
    # Occupants (from header bar sprites)
    occupant_colors: list[int]    # Colors of sprites in header, left to right

    # Messages (from message area)
    # Note: OCR of messages is expensive and error-prone. We extract what
    # we can but the primary signals are the structured indicators.
    messages: list[ChatMessage]

    # Pending entry
    has_pending_entry: bool       # "!" indicator detected
    pending_entry_color: int | None  # Color of the requesting player's sprite

    # Bottom bar state
    bottom_bar: ChatroomBottomBar

@dataclass
class ChatMessage:
    """A single visible chat message line."""
    sender_color: int | None  # Player color (None for system messages)
    is_system: bool           # True if rendered in color 8 (system)
    text: str                 # OCR'd text content (best-effort)
    y_position: int           # Screen y where this message is drawn

class ChatroomBarState(Enum):
    DEFAULT = "default"       # "L:EXIT  K:ACTIONS  ENTER:MSG"
    MENU = "menu"             # "(CATEGORY) ACTION"
    TARGET_PICKER = "target"  # "COLOR: [sprites]" or "ROLE: [sprites]"

@dataclass
class ChatroomBottomBar:
    state: ChatroomBarState
    # Default state indicators
    pending_role_offer: bool    # "R!" at (118, 121) in color 8
    pending_color_offer: bool   # "C!" at (118, 121) in color 8
    # Menu state
    menu_category: str | None   # "COLOR", "ROLE", "LEADER", or "EXIT"
    menu_item: str | None       # Full action label (e.g., "R.OFFER", "C.UNOFFR")
    menu_enabled: bool          # True if color 2 (enabled), False if color 1
    # Target picker state
    target_mode: str | None     # "COLOR" or "ROLE"
    target_colors: list[int]    # Colors of offerer sprites shown
```

### Pixel Details

**Occupant sprites**: Scan at x=22 with stride 9 (PLAYER_W + 2), y=1
to y=7. For each slot, check for any non-zero non-1 pixel in the 7x7
area. The dominant non-zero non-1 color is the occupant's player color.
Stop at the first empty slot.

**Pending entry indicator**: Scan for color-8 pixels in x=[2,4],
y=[110,116]. If found, read the player sprite color at (8+3, 111+3) =
(11, 114) center pixel.

**Offer indicators** (default bar state): Read text at (118, 121) in
color 8. "R" prefix = role offer pending, "C" prefix = color offer.
These are steady (not blinking).

**Menu state**: Read text at (2, 121). If color 2 and matches
`\((\w+)\)\s+(.+)`, it's a menu display: group 1 = category, group 2 =
item label. If color 1 with same pattern, menu is showing but item is
disabled.

**Target picker**: Read text at (2, 121) in color 8. If starts with
"COLOR:" or "ROLE:", scan for sprites after the label text.

**Message OCR**: Messages are at y positions from 10 upward in 7-pixel
increments. For each 7-pixel row, check if there's content (any
non-zero pixels). System messages use color 8. Player messages have a
7x7 sprite at x=2, then text at x=10 in the sender's color.

---

## View 3: Global Chat

### Layout

```
y=0..8:              Header ("{RoomName} CHAT")
y=10..votingBottom:  Usurp/hostage section
y=votingBottom:      1px divider line (color 1)
y=votingBottom+2..:  Message area
y=119..127:          Bottom bar
```

### Extractable Components

```python
@dataclass
class GlobalChatPerception:
    room_name: str | None         # "Underworld" or "Mortal Realm"

    # Usurp section (non-leader)
    usurp_candidate: UsurpCandidate | None

    # Hostage section (leader during HostageSelect)
    hostage_grid: HostageGrid | None

    # Messages
    messages: list[ChatMessage]

    # Bottom bar
    bottom_bar_text: str | None   # Raw OCR of bottom bar

@dataclass
class UsurpCandidate:
    """Current usurp candidate shown in the selector."""
    text: str | None        # "NONE", "ME", or None if showing a sprite
    player_color: int | None  # Player color if showing a sprite

@dataclass
class HostageGrid:
    """Hostage selection grid (visible to leaders during HostageSelect)."""
    eligible_colors: list[int]    # Colors of eligible players
    selected_colors: list[int]    # Colors of currently selected players
    cursor_index: int | None      # Which cell has the cursor outline
    count_label: str | None       # e.g., "1/2 HOSTAGES"
    is_committed: bool            # True if "COMMITTED" shown instead of grid
```

### Pixel Details

**Room name**: Read text at (2, 2) in color 2. Match against known
patterns: `"Underworld CHAT"`, `"Mortal Realm CHAT"`.

**Usurp candidate**: If text `"USURP:"` detected at (2, 11) in
color 1, check what follows at x=29 (label is 23px + 4px space).
If text in color 2 reads "NONE" or "ME", it's a text candidate.
Otherwise check for a player sprite and read its color.

**Hostage grid**: Grid starts at y=11. Cells are 12x14 pixels, max 4
columns. For each cell, check for a sprite (non-zero non-1 pixels in
the center area). A color-2 outline rect = cursor. Color-11 check
marks at specific positions within the cell = selected.

**Committed state**: If `"COMMITTED"` text detected centered around
y=14 in color 2, the leader has already committed.

---

## View 4: Info Screen

### Extractable Components

```python
@dataclass
class InfoScreenPerception:
    mode: InfoMode          # "shared" or "role"

    # "role" mode
    role_name: str | None
    team_name: str | None
    team_color: int | None

    # "shared" mode
    known_players: list[KnownPlayer]

@dataclass
class KnownPlayer:
    color: int              # Player's palette color
    role_name: str | None   # Role name if fully revealed, None if color-only
    team_color: int | None  # Team color (from role indicator or color dot)
    is_self: bool           # First entry is always self
    color_only: bool        # True if "???" shown (color exchange only)

class InfoMode(Enum):
    ROLE = "role"
    SHARED = "shared"
```

### Pixel Details

**Mode detection**: If text `"KNOWN PLAYERS"` at (2, 2) in color 2, it's
"shared" mode. If "YOU ARE" text detected (with team-color border), it's
"role" mode.

**Known players list** (shared mode): Rows at y = 12 + row * 11. Each
row has a sprite at x=4. Read the center pixel at (7, y+3) for color.
Text at (15, y+2): if in a team color and recognizable as a role name,
it's a full reveal. If color 1 and reads "???", it's color-only.

---

## View 5: Role Reveal

### Extractable Components

```python
@dataclass
class RoleRevealPerception:
    role: str | None          # e.g., "Hades", "Persephone"
    team: str | None          # "Shades" or "Nymphs"
    team_color: int | None    # 3 or 14 (from border color)
    room: str | None          # "Underworld" or "Mortal Realm"
    player_count: int | None  # e.g., 10
    room_size: int | None     # e.g., 120 (room is square: 120x120)
    countdown_secs: int | None  # Seconds until game starts
```

### Pixel Details

**Border color**: Read pixels[0, 0]. This is the team color (3 or 14).
Confirm with pixels[2, 2] matching.

**Text scanning**: The text is centered, so we can't read from a fixed
x position. Scan horizontally at each expected y offset for text in the
expected color:

| y | Content | Color | Parse method |
|---|---------|-------|-------------|
| 8 | "YOU ARE" | 2 | Confirm presence |
| 18 | Role name | border_color | Match against known role names |
| 28 | Team name + " TEAM" | border_color | Match against "Shades TEAM" / "Nymphs TEAM" |
| 46 | Room name | 2 | Match against "Underworld" / "Mortal Realm" |
| 56 | "{n}P  {w}x{h}" | 1 | Parse player count and room dimensions |
| ~100 | "STARTING IN {n}" | 2 | Parse countdown seconds |

**OCR approach for centered text**: For each expected y position, scan
x from 0 to ~60, attempting to read text in the expected color. Match
the result against known strings (role names, team names, room names).
For numeric content (player count, room size, countdown), apply the
`toDigits` normalization (O→0, S→5) before parsing.

---

## View 6: Hostage Exchange

### Extractable Components

```python
@dataclass
class ExchangePerception:
    # Leader(s) shown
    leaders: list[ExchangePlayer]
    # Hostages leaving viewer's room
    departing: list[ExchangePlayer]
    # Hostages arriving to viewer's room
    arriving: list[ExchangePlayer]
    # Viewer's status
    viewer_status: str | None  # "hostage", "leader", or "spectator"

@dataclass
class ExchangePlayer:
    color: int              # Player color from sprite
    role_indicator: RoleIndicator | None  # Parsed role indicator bar
```

### Pixel Details

Content starts at y=26. Labels "LEADERS"/"LEADER" at (8, 26) in color
2, "DEPARTING" at (8, y) in color 8, "ARRIVING" at (8, y) in color 11.
Each player row is a sprite at (10, y) with a role slot at (10, y+8).
Rows are 14 pixels apart.

Bottom bar at y=121: "YOU ARE BEING EXCHANGED" (color 8) = hostage,
"ESCORTING HOSTAGES" (color 2) = leader, "HOSTAGES EXCHANGING..." (color
1) = spectator.

---

## View 7: Result (Reveal + GameOver)

### Extractable Components

```python
@dataclass
class ResultPerception:
    is_reveal: bool         # True = Reveal phase, False = GameOver phase
    winner: str | None      # "Shades", "Nymphs", or None (draw)
    winner_color: int | None  # 3, 14, or 1
```

### Pixel Details

Win text is rendered centered at y=60. Scan for text in colors 3
("Shades WIN!"), 14 ("Nymphs WIN!"), or 1 ("NO ONE WINS!"). The
`is_reveal` flag is set if "REVEAL!" is detected at (2, 2) in color 2.

---

## View 8: Lobby

### Extractable Components

```python
@dataclass
class LobbyPerception:
    player_count: int | None    # Current connected players
    max_players: int | None     # Required player count
    countdown_secs: int | None  # Countdown to game start (if full)
```

### Pixel Details

Top bar text at (2, 2) in color 2: `"{count}/{max} PLAYERS"`. Parse
with `toDigits` normalization. If countdown: text at (80, 2) in color
8: `"START {secs}"`.

No minimap during lobby. All players visible regardless of room. No
fog of war.

---

## Role Indicator Parsing

Role indicators appear below player sprites in several views (overworld,
info screen, exchange screen). They are 5x2 pixels at (sprite_x + 1,
sprite_y + 8).

```python
@dataclass
class RoleIndicator:
    team: str               # "shades" or "nymphs" (from base color)
    role_class: str         # "key_a", "key_b", or "grunt"

# Detection logic:
# Base fill color: 3 = Shades, 14 = Nymphs
# Special dots ON TOP of the base fill:
#   Hades:      color 8 at center (x+2, y+0) and (x+2, y+1)
#   Persephone: color 2 at center (x+2, y+0) and (x+2, y+1)
#   Cerberus:   color 8 at (x+1, y+0) and (x+3, y+0)
#   Demeter:    color 2 at (x+1, y+0) and (x+3, y+0)
#   Grunt:      no special dots (pure team color fill)
```

Note: the indicator tells us team + key/grunt status but NOT the
specific role within a key class (Hades vs Cerberus, Persephone vs
Demeter) -- those pairs share the same dot color, just different
positions (center vs split). We CAN distinguish them:

| Pattern | Role |
|---------|------|
| Team 3, center dots (color 8) | Hades |
| Team 3, split dots (color 8) | Cerberus |
| Team 3, no dots | Shade (grunt) |
| Team 14, center dots (color 2) | Persephone |
| Team 14, split dots (color 2) | Demeter |
| Team 14, no dots | Nymph (grunt) |

---

## OCR Engine

The game uses a fixed 3-wide x 5-tall pixel font. All glyphs are known
(see font catalog in the rendering report). The OCR engine needs to:

1. **Read text at a position in a specific color**: Filter frame to only
   the target color, then match glyph patterns left-to-right starting
   at (x, y). Advance x by glyph_width + 1 (= 4) per character, 4 per
   space.

2. **Read text at a position in any color**: Probe the pixel at (x, y)
   to determine the color, then read in that color.

3. **Scan for centered text**: For a known y position where text is
   centered, scan x from 0 to ~60 attempting reads in each candidate
   color. Return the first successful match of sufficient length.

### Ambiguity Handling

The game renders distinct glyphs for S vs 5 and O vs 0. Earlier
versions of this document incorrectly stated they were pixel-identical.
The OCR engine matches them as separate characters with no ambiguity.

Legacy `normalize_text()` and `normalize_digits()` functions are
retained as no-ops for backward compatibility.

### Glyph Matching

For each position, compare the 3x5 pixel region against all known
glyphs. The target-color pixels must match the `#` positions in the
glyph; non-target-color pixels must be at the `.` positions. A match
threshold of ~90% handles minor rendering artifacts.

---

## Implementation Language

### Recommendation: Python

The perception module should be written in Python.

**Arguments for Python**:

1. **Agent language**: Python is the primary agent language. Direct
   `import` is the simplest possible integration -- no serialization,
   no IPC, no subprocess overhead.

2. **Performance is sufficient**: A 128x128 frame is 16,384 pixels.
   The upstream TypeScript parser runs at 24fps in Node.js without
   issues. Python with NumPy for array operations will be comparable.
   The perception function needs to complete in <42ms (one frame
   period); realistic expectation is <5ms for the full parse.

3. **NumPy as the acceleration layer**: Frame unpacking, color
   filtering, region extraction, and pattern matching all map naturally
   to NumPy vectorized operations. No need for C extensions.

4. **Iteration speed**: We'll be tuning the parser as we discover edge
   cases. Python's edit-run cycle is fast.

**Multi-language agents**: Agents in other languages (TypeScript, Rust)
have two options:

1. **Use the upstream TypeScript parser** (`bots/frame_parser.ts`) which
   already exists and works. TypeScript agents don't need our Python
   parser.

2. **Call the Python parser via subprocess**: The perception module can
   be invoked as a CLI tool that reads a frame from stdin and writes
   JSON to stdout. This is ~50ms overhead per call, acceptable for
   agents that don't need 24fps perception.

3. **Reimplement in the target language**: The logic is well-documented
   and deterministic. A Rust or C port is straightforward if needed.

A C/Rust FFI library would be premature. The 24fps pixel-parsing
workload doesn't justify the complexity.

### Module Location

```
persephone/
  perception/
    __init__.py           # Public API: parse_frame(raw_bytes) -> FramePerception
    _unpack.py            # Frame unpacking (8192 bytes -> 128x128 array)
    _detect.py            # View detection
    _ocr.py               # Text reading engine + font data
    _overworld.py         # Overworld view parser
    _chatroom.py          # Chatroom view parser
    _global_chat.py       # Global chat view parser
    _info_screen.py       # Info screen parser
    _role_reveal.py       # Role reveal parser
    _exchange.py          # Hostage exchange parser
    _result.py            # Reveal / GameOver parser
    _lobby.py             # Lobby parser
    _minimap.py           # Minimap scanner (shared by overworld views)
    _position.py          # Position estimation (shared by overworld views)
    _sprites.py           # Sprite/shape recognition
    _indicators.py        # Role indicator parsing
    _bubbles.py           # Speech bubble detection
    _common.py            # Shared constants, color sets, pixel helpers
    types.py              # All dataclass definitions (FramePerception, etc.)
```

### Public API

```python
from perception import parse_frame
from perception.types import FramePerception, View

# From raw bytes (as received from WebSocket)
result: FramePerception = parse_frame(raw_bytes)

# Or from an already-unpacked array
result = parse_frame(pixels_128x128)

# Use the result
if result.view == View.PLAYING and result.overworld:
    for dot in result.overworld.minimap_dots:
        print(f"Player at ({dot.world_x}, {dot.world_y}), color={dot.color}")
```

### Performance Budget

At 24fps, each frame has ~42ms. Target: parse a frame in <5ms.

| Component | Estimated Cost |
|-----------|---------------|
| Unpack (8192 → 16384) | <0.1ms (NumPy) |
| View detection | <0.5ms (few pixel reads + 1-2 OCR calls) |
| Minimap scan | <0.2ms (400 pixel reads) |
| Position estimation | <0.5ms (minimap + floor dot scan) |
| OCR (per call) | <0.5ms (scan ~30 chars = ~450 pixel comparisons) |
| Speech bubble scan | <1ms (pattern match over game area) |
| Full overworld parse | <3ms total |
| Full chatroom parse | <2ms total (header + indicators + message OCR) |

These are conservative estimates. NumPy vectorization will likely make
most operations sub-0.1ms.

---

## Design Principles

1. **Stateless**: Every call to `parse_frame()` is independent. No
   internal state, no frame counter, no "previous frame" comparison.
   Agents own their state.

2. **Best-effort extraction**: OCR and pattern matching may fail on any
   given frame (fog, animation, edge cases). Fields are `None` when
   extraction fails. Agents must tolerate missing data.

3. **View-complete**: Every field extractable from a single frame is
   extracted. Even if the agent doesn't need it now, the perception
   module should provide it. Avoids re-parsing later.

4. **No interpretation**: The module reports what it sees, not what it
   means. "There is a color-3 dot on the minimap" rather than "Hades
   is nearby." Interpretation is the agent's job.

5. **Cheap to call**: Agents should call `parse_frame()` every tick
   without worrying about cost. The 5ms budget is well within the
   42ms frame period.
