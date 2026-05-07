# Orpheus — Design

## Overview

Orpheus is an agent *framework* for Persephone's Escape. It provides:

- A **perception** module (pixel frames → symbolic state; existing code).
- A **belief state** memory module with a fixed schema shared across all modes.
- A built-in **perception → belief update** pipeline.
- A set of **primitive actions** and action-handling logic (move-to w/ A*,
  chat, offer role reveal, offer role swap, etc.).
- A **hook system** for agent-defined code at stage boundaries.

What an agent supplies:

- A set of **modes** (registered in a mode registry).
- **LLM directives** for the outer loop (mode selection).
- Optional **inter-stage hooks**.

---

## Two-loop architecture

```
┌──────────────────────────────────────────────────────┐
│  Outer loop (LLM)                                    │
│  Selects the active mode based on belief state.      │
└───────────────────────┬──────────────────────────────┘
                        │ sets active mode
┌───────────────────────▼──────────────────────────────┐
│  Inner loop (per-tick, symbolic)                      │
│  Runs the pipeline below using the active mode.      │
└──────────────────────────────────────────────────────┘
```

---

## Inner loop pipeline

Each tick executes four phases in sequence. Every phase has `pre` and `post`
hook points.

```
[pre|perception|post] → [pre|belief_update|post] → [pre|decide|post] → [pre|act|post]
```

**Phase-agnostic execution**: the pipeline runs identically regardless of the
game's current phase. Whether the game is in Lobby, RoleReveal, Playing,
HostageExchange, or GameOver, the same four phases execute in the same order.
There is no framework-level phase gating, suppression, or special-casing.

Phase-appropriate behavior emerges from:
- Perception correctly detecting the current view and extracting all visible
  information.
- Belief update integrating that information into the belief state (including
  the `view` field).
- Modes examining the belief state and making sensible decisions (e.g.,
  returning `IdleTask()` during non-interactive phases).
- Tasks producing appropriate output (including no-ops when nothing can be
  done).

The framework does not need to "suppress" action output during non-interactive
phases. Sending `buttons=0` to the server during HostageExchange is harmless.
It is the agent's responsibility — via its modes — to behave appropriately for
the current game phase.

### Perception phase

Parses the raw pixel frame into structured symbolic output (the `View`).

### Belief update phase

Integrates the perception output into the persistent belief state. Behavior
depends on the perceived view — different views contribute different
information. See the [belief update pipeline](#belief-update-pipeline) section
for the full specification.

### Decide phase

Calls the active mode's `select_task` method. This is the only phase where
mode-specific logic runs (aside from hooks).

### Act phase

Translates the current task (returned by `select_task`) into a per-tick
command sent to the server. A command may contain button input, a chat
packet, or both. Uses the belief state and an `ActionMemory` object to
execute multi-tick tasks.

---

## Mode interface

All modes are stored in a **mode registry**. The agent is in exactly one mode
at any time.

A mode is a class with three required methods:

| Method | When called | Purpose |
|--------|-------------|---------|
| `select_task(belief_state, action_memory) -> Task | None` | Every tick (decide phase) | Task selection; may also mutate belief state |
| `mode_enter(belief_state, action_memory) -> Task | None` | Once, on activation | One-time setup when mode becomes active |
| `mode_switch_cleanup(belief_state, action_memory, new_mode_directive) -> None` | Once, on deactivation | Teardown when being replaced by another mode |

### select_task

Called during the decide phase every tick. It receives the current belief
state (mutable — mode may update any fields directly) and the current action
memory (read-only — provides visibility into what commands the active task
has been sending). Returns a `Task` to set the active task, or `None` to
keep the current task running unchanged.

Its responsibilities:

1. Return the desired task (e.g. `MoveToTask(x, y)`, `IdleTask()`), or
   `None` to reaffirm the current task.
2. Optionally mutate belief state fields directly (e.g., update mode-specific
   counters, flag observations).

`select_task` does **not** call actions directly.

### mode_enter / mode_switch_cleanup

See the [mode switching](#mode-switching) section for the full lifecycle
and calling semantics.

Modes may also attach logic via the pre/post hooks on any phase.

### ModeDirective

A `ModeDirective` specifies which mode to activate and with what parameters.
It is the data type that flows from the outer loop (via the mode buffer) to
the inner loop, and that mode-switch callbacks may override.

```
@dataclass(frozen=True)
class ModeParams:
    """Base class for mode parameters. Subclass per mode."""
    pass

@dataclass(frozen=True)
class ModeDirective:
    mode: str             # Registry key identifying the target mode
    params: ModeParams    # Instance of the mode's declared params type
```

**Equality**: structural (`==` on both `mode` and `params`). Two frozen
dataclasses are equal iff all their fields are equal. This drives the
reaffirmation check — if the consumed `ModeDirective` equals the currently
active mode's directive, no mode switch occurs.

**Mode params**: each mode class declares a `params_type` class attribute —
a frozen dataclass subclass of `ModeParams` that defines the parameters it
accepts. Modes with no parameters use the bare `ModeParams` base (no
fields).

```
@dataclass(frozen=True)
class FindPlayerParams(ModeParams):
    target_index: int
    approach_distance: int = 15

class FindPlayerMode(Mode):
    params_type = FindPlayerParams
    ...

@dataclass(frozen=True)
class ExploreParams(ModeParams):
    pass  # no parameters

class ExploreMode(Mode):
    params_type = ExploreParams
    ...
```

**Param validation**: the framework validates `ModeDirective.params` against
the target mode's declared `params_type` when the inner loop consumes the
mode buffer. Validation checks:

1. `directive.mode` exists in the mode registry. If not → log error, discard
   the directive, continue with current mode.
2. `isinstance(directive.params, registry[directive.mode].params_type)`. If
   not → log error, discard the directive, continue with current mode.

Validation runs at consumption time (not production time) because:
- The outer loop (`meta_decide`) is agent-defined and may produce arbitrary
  values. Failing loudly in the inner loop is safer than silently accepting
  bad directives.
- Mode-switch callbacks may override the directive. Validation must run on
  the *final* directive, after all callbacks have fired.

The same validation applies when a mode-switch callback returns a new
`ModeDirective` — checked before advancing to the next callback.

**Construction by the outer loop**: `meta_decide` constructs a
`ModeDirective` by instantiating the appropriate params type:

```
def meta_decide(belief_state, action_memory):
    ...
    return ModeDirective(
        mode="find_player",
        params=FindPlayerParams(target_index=3)
    ), None
```

---

## Tasks

A `Task` is an object that encapsulates how to execute a particular kind of
work (movement, chatting, etc.). Tasks are the unit of act-phase logic.

### Interface

```
Task.select_action(belief_state, action_memory) -> ActCommand
```

`ActCommand` is the framework's per-tick transport envelope:

```
@dataclass(frozen=True)
class ActCommand:
    buttons: ActionMask = 0
    chat_text: str | None = None
    reset_input: bool = False
```

- Reads belief state (read-only).
- Reads and mutates action memory directly (task-private state).
- Returns an `ActCommand`:
  - `buttons` is the low-level input mask sent as a `PACKET_INPUT`.
  - `chat_text`, when present, is sent as a `PACKET_CHAT`.
  - `reset_input` sends the protocol reset mask (`0xFF`) instead of `buttons`.

Chat is a first-class packet type, not a simulated button action. Sending chat
does not require pressing A, B, Select, or Enter before or after the chat
packet. The server routes chat by player state: if the player is inside a
whisper, the packet becomes whisper text; otherwise it becomes global room
chat.

`ActCommand` is an internal framework object only; it is never sent directly
to the server. The framework's act phase lowers it into Persephone protocol
packets:

```
def send_act_command(ws, command):
    if command.reset_input:
        send_input(ws, 0xFF)
        return

    send_input(ws, command.buttons)

    if command.chat_text is not None:
        send_chat(ws, command.chat_text)
```

`send_input` sends `[PACKET_INPUT, mask & 0x7F]`. `send_chat` sends
`[PACKET_CHAT] + ASCII(text)`. The framework sends exactly one input packet
per tick, followed by at most one chat packet. `reset_input=True` suppresses
normal button and chat output for that tick.

### Lifecycle

The decide phase (via `select_task`) determines the current task. If
`select_task` returns `None`, the current task is reaffirmed (ActionMemory
preserved, execution continues). If it returns a `Task`, the framework
compares it against the previous tick's task by identity — `(task_type,
params)` equality. Two cases:

- **Task changed** (different type or different parameters): ActionMemory is
  cleared. The new task starts with empty action memory.
- **Task reaffirmed** (same type, same parameters, or `None` returned):
  ActionMemory is preserved. The task continues execution where it left off.

### Task completion

Tasks do **not** signal their own completion. A task can only assert that it
sent an input or chat command, not that the world changed in response. Completion is a
belief-level concept: the mode's `select_task` infers completion from the
belief state (which is updated from perception each tick).

Examples:

- Move-to: perception updates position; `select_task` sees position matches
  target and selects the next task.
- Chat: perception detects the message appearing in the chat window;
  `select_task` observes this and moves on.

If perception cannot detect an action's effect, that is a perception gap to
fix — not a reason to add completion signaling to the task layer.

### ActionMemory

Separate from belief state. Holds control-level execution state needed to
carry out multi-tick tasks:

- Path (A* waypoints, computed when a move-to task begins).
- Commands sent (for timeout/retry/stuck detection).
- Other per-task control state.

ActionMemory is scoped to the current task. It is cleared whenever the task
changes (see lifecycle above).

### Task catalogue

#### Movement

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `move_to` | `x, y` | A* pathfinding to target; outputs directional masks along waypoints | Position matches target |
| `follow` | `player_index` | A* path to target's last-known position; re-paths when target moves | Never — mode switches away |
| `wander` | — | Exploratory movement pattern (random waypoints, avoid revisiting areas) | Never — mode switches away |

#### Chatroom lifecycle

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `create_whisper` | — | Press A/J in current position (mode ensures open space) | View → whisper |
| `request_entry` | `player_index` | A* path to target player, B/K-press when close | View → whisper (or WAITING state) |
| `exit_whisper` | — | Menu navigate: EXIT category → EXIT item → confirm (or Select/L shortcut) | View → overworld |
| `grant_entry` | — | Menu navigate: LEADER category → GRANT item → confirm | System message confirms |

#### Information exchange (require whisper view)

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `offer_color_exchange` | — | Menu navigate: COLOR → C.OFFER → confirm | System msg "offered color" |
| `accept_color_exchange` | `player_index` | Menu navigate: COLOR → C.ACCPT → confirm → target picker → select player → confirm | System msg "swapped colors" |
| `withdraw_color_offer` | — | Menu navigate: COLOR → C.UNOFFR → confirm | Offer cleared |
| `offer_role_exchange` | — | Menu navigate: ROLE → R.OFFER → confirm | System msg "offered role" |
| `accept_role_exchange` | `player_index` | Menu navigate: ROLE → R.ACCPT → confirm → target picker → select player → confirm | System msg "shared roles" |
| `withdraw_role_offer` | — | Menu navigate: ROLE → R.UNOFFR → confirm | Offer cleared |
| `reveal_role` | — | Menu navigate: ROLE → ROLE → confirm | System msg "showed role" |

#### Leadership

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `pass_leadership` | — | Menu navigate: LEADER → PASS → confirm (requires whisper, is leader) | System msg "offered lead" |
| `take_leadership` | — | Menu navigate: LEADER → TAKE → confirm (requires whisper, offer pending) | `is_leader` becomes true |
| `vote_usurp` | `candidate` | Open global chat if needed; navigate usurp selector to candidate; A-press to vote | System msg "voted for..." |

#### Hostage selection (leader only, HostageSelect phase)

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `select_hostages` | `player_indices[]` | In global chat: navigate hostage grid, toggle each target, commit | View transitions / timer expires |

#### Communication

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `send_message` | `text, channel` | Send a `PACKET_CHAT` with `buttons=0`; no button press is required. `channel` is the intended route (`whisper`, `global`, or `auto`) and is checked against belief state because the server routes by whether the player is inside a whisper. Respects chat cooldown internally | Message appears in chat history |

#### View management

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `open_global_chat` | — | Press Select | View → global_chat |
| `open_info_screen` | — | Press B | View → info_screen |
| `close_view` | — | Press Select/L (context-dependent) | View → overworld |

#### Idle

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `idle` | — | No-op (outputs 0x00 mask) | Never — mode switches away |

### Implementation notes

- All whisper menu tasks (information exchange, leadership, grant) share
  internal menu-navigation logic: open menu (B) → navigate category
  (left/right) → navigate item (up/down) → confirm (A) → optionally navigate
  target picker (left/right) → confirm (A). Rising-edge button sequencing
  (press/release alternation) is handled by shared infrastructure in
  ActionMemory.

- `request_entry` bundles approach + button press into one task. The mode
  doesn't need to micromanage proximity — the task handles both pathfinding
  and the A-press.

- `follow` is distinct from repeated `move_to(player_pos)` to avoid clearing
  ActionMemory (and re-computing A*) every tick the target moves. Its identity
  is `("follow", player_index)`, stable regardless of target position.

- `send_message` respects the chat cooldown internally, outputting no-op
  commands until the cooldown expires. When it sends, it emits an `ActCommand`
  with `chat_text` populated and `buttons=0`. The mode can re-affirm the task
  each tick without concern for timing.

---

## Belief state

The belief state is a fixed-schema object with a flexible extension space.
Required fields are populated by the framework (perception + belief update
pipeline). Modes may create and use arbitrary additional fields — the belief
state is essentially a (possibly nested) dict beyond the required schema.

### Player identity model

Players are distinguished by **color** (8 values) and **shape** (12 values).
The mapping from player index `i` is deterministic:

- `color = PLAYER_COLORS[i % 8]`
- `shape = PlayerShape(i % 12)`

Since lcm(8, 12) = 24 and max players is 24, every (color, shape) pair is
unique and can be decoded back to a player index. The canonical player
identifier throughout Orpheus is the **player index**.

Shape detection is implemented in `perception/_sprites.py:detect_sprite_shape()`.
It provides shadow-aware template matching for all 12 shapes. Overworld
speech bubbles, whisper occupants, info screen, exchange screen, and global
chat sprites all report both color and shape. Minimap dots remain color-only
(single pixel, no shape information available).

Source: `~/coding/bitworld/persephones_escape/game/constants.ts`,
`~/coding/bitworld/persephones_escape/game/sim.ts`

### Required fields

**Self identity (static after game start):**
- `my_index` — player index, decoded from own color + shape
- `my_color` — palette index (derived from index, kept for fast matching)
- `my_shape` — shape enum (derived from index, kept for fast matching)
- `my_role` — role name (hades, cerberus, shade, persephone, demeter, nymph)
- `my_team` — "shades" or "nymphs"
- `my_room` — initial room assignment (underworld / mortal_realm)

**Timing:**
- `tick` — monotonic counter, incremented each inner loop cycle. Used for
  cooldown tracking, timeout logic, "ticks since X" calculations.

**Spatial (updated each tick from perception):**
- `position` — own `(x, y)` world coordinates
- `room` — current room
- `room_size` — `(w, h)` in world pixels (learned from role reveal)
- `occupancy_grid` — 2:1 resolution grid of the current room (see spatial
  knowledge section below)

**Player registry:**
- `players` — map of player index → known info per player:
  - `position` — last-known `(x, y, tick)` from minimap or viewport
  - `room` — last-known room
  - `team` — known team (with source, see knowledge provenance below)
  - `role` — known role (with source)
  - `last_seen_in_whisper` — tick when last observed with a speech bubble
    (overworld), or None if never seen in a whisper

  Persephone's Escape has no elimination mechanic; all players remain active
  for the entire match.

  Minimap dots provide color-only sightings, which narrow to up to 3
  candidate indices (those sharing `color mod 8`). Overworld sprite
  observations provide full (color, shape) identification via
  `detect_sprite_shape()`, giving unambiguous player index resolution.

**Game state:**
- `view` — current phase/view enum
- `round` — round number
- `timer_secs` — countdown if visible
- `player_count` — total players in the game
- `winner` — winning team after Reveal, or None

**Game schedule (static after game start):**
- `round_schedule` — list of `(duration_secs, hostage_count)` per round.
  Learned from the RoleReveal schedule panel (if perception extracts it) or
  from observing round timers and hostage counts during play.

**Action state:**
- `cooldowns` — map of action type → tick when next available. Updated by
  the framework when actions are sent. Tasks consult this to respect the
  48-tick rate limit (chat, menu actions).

**Chatroom state:**
- `in_whisper` — whether self is currently in a whisper (derivable from
  `view`, surfaced explicitly since many tasks gate on this)
- `whisper_occupants` — list of player indices in current whisper (empty
  if not in whisper)
- `pending_offers` — active exchange offers visible to us: `{role: bool,
  color: bool}` from the "R!" / "C!" bottom-bar indicators
- `pending_entry` — player index requesting entry to our whisper (from
  "[sprite] WANTS IN" perception), or None
- `menu_state` — current whisper menu state: closed, (category, item), or
  target picker with candidate list. Parsed from perception bottom bar.

**Hostage state (during HostageSelect):**
- `hostage_selections` — current selections and cursor state if we are
  leader. Parsed from `GlobalChatPerception.hostage_grid`.

**Social / knowledge:**
- `chat_history` — recent messages observed (whisper + global + shouts),
  with sender index, tick, channel (whisper/global/shout), and for
  whisper messages: the list of occupant indices present when the message
  was sent. This captures not just who said what, but who they intended to
  hear it.
- `my_exchange_partner` — player index we have completed a mutual role
  exchange with (satisfies win condition), or None

**Knowledge provenance:**

The player registry's role/team fields carry a `source` tag distinguishing
how the information was obtained:

| Source | Meaning | Win condition? |
|--------|---------|----------------|
| `mutual_exchange` | R.OFFER + R.ACCPT completed (sharedWith) | Yes |
| `role_reveal` | One-way ROLE action observed | No |
| `color_exchange` | C.OFFER + C.ACCPT completed | No (team only) |
| `game_display` | Rendered by game UI (info screen, exchange screen, overworld role indicators) | No |
| `chat_claim` | Stated by a player in chat | No (unverified) |
| `inferred` | LLM/mode reasoning | No (speculative) |

The `game_display` source covers any role/team information that the game
renders as a consequence of prior mechanical actions. The info screen,
exchange screen, and overworld role indicators all reflect the game's
internal `revealedTo`/`sharedWith` state and are mechanically truthful.

The `mutual_exchange` source tracks the game's `sharedWith` mechanic — the
only action that satisfies the win condition. Distinguishing mechanical
revelation from chat claims is critical because players may lie in chat but
mechanically revealed information is always truthful.

**Leadership/hostage:**
- `is_leader` — whether self holds the crown
- `leader_colors` — known leader colors per room

**Task (framework-managed, read-only to modes):**
- `current_task` — active task identifier + parameters (set by the framework
  from `select_task`'s return value; exposed for hooks and outer loop
  visibility)

**Flexible space:**
- All other keys are mode-defined. Modes may create arbitrary nested
  structures for their own use.

### Spatial knowledge and map building

The framework maintains a persistent **occupancy grid** as part of the
belief state, covering the full room. This grid is the traversability map
for A* pathfinding.

#### Room geometry

Learned from the role reveal screen (exposes "NP WxH"):
- Room size: W x H (100-200px depending on player count)
- Room border: 1px solid wall at all edges (always present)
- Obstacle count: deterministic from player count (4-14 per room)

Fixed for the duration of the game once observed.

#### Occupancy grid

A 2D grid covering the full room at **2:1 resolution** (one grid cell per
2x2 world-pixel block). For a 200x200 room, this is 100x100 = 10K cells.

Cell states:

| State | Meaning |
|-------|---------|
| `UNKNOWN` | Never observed by viewport |
| `FREE` | Confirmed traversable (static) |
| `WALL` | Confirmed impassable (static) |

**Initialization**: Room border cells marked `WALL`, interior marked
`UNKNOWN`.

#### Observation confidence tiers

The grid distinguishes between **viewport-confirmed** and
**minimap-inferred** knowledge. This distinction only applies to static
terrain (walls/obstacles/floor), not dynamic entities (players).

- **Viewport-confirmed**: cell has been directly observed in the game
  viewport. Static state (`WALL` or `FREE`) is locked — minimap data cannot
  override it.
- **Minimap-inferred**: cell state was estimated from minimap obstacle dots.
  Treated as best-guess until viewport observation replaces it.

Player positions from the minimap always update regardless of whether a cell
is viewport-confirmed, since players are dynamic.

#### Update sources (per tick, during belief update phase)

**1. Viewport observation (primary, exact):**

Walls (color 5) are **exempt from fog-of-war darkening** — the renderer
explicitly skips color 5 when applying shadows. This means walls and
obstacles are always visible as color 5 in the viewport regardless of fog.

Each tick, for every pixel in the game viewport area (y=9 to y=118,
excluding the minimap region at x=106+):
- World coordinate: `(cameraX + sx, cameraY + sy)`
- Map to grid cell: `(world_x // 2, world_y // 2)`
- If pixel is color 5 → mark cell `WALL`, flag viewport-confirmed
- If pixel is a known floor color (RoomA: 12/6, RoomB: 9/10) → mark cell
  `FREE`, flag viewport-confirmed
- Otherwise (shadowed floor, player sprites, indicators) → leave unchanged

Camera position is deterministic from self-position:
```
cameraX = clamp(playerCenterX - 64, 0, roomW - 128)
cameraY = clamp(playerCenterY - 64, -9, roomH - 119)
```

**2. Minimap obstacle hints (coarse, approximate):**

The minimap renders each obstacle as a single color-5 dot at:
```
minimap_x = floor(obstacle.x * 20 / roomW)
minimap_y = floor(obstacle.y * 20 / roomH)
```

Reversing: `obstacle.x ≈ minimap_x * roomW / 20`. Since obstacles are 8x8,
the agent marks a probable 8x8 `WALL` region (4x4 grid cells at 2:1)
around each decoded position.

Minimap hints **only populate `UNKNOWN` cells** — they never override
viewport-confirmed static state. This prevents the minimap's imprecision
(±`roomW/20` px per cell) from corrupting known-good viewport data.

The minimap shows ALL obstacles in the current room without fog, providing
a complete census of approximate obstacle locations from tick 1.

**3. Movement confirmation (implicit):**

If the agent's position changes to `(x, y)`, the 7x7 player bounding box
is traversable. All grid cells within the player's footprint are marked
`FREE` and viewport-confirmed.

#### A* pathfinding

The occupancy grid is the cost map for A*:
- `WALL` → impassable
- `FREE` → cost 1
- `UNKNOWN` → treated as traversable (optimistic pathfinding)

Optimistic handling of `UNKNOWN` is appropriate because rooms are mostly
open space with few obstacles. If movement is blocked by an undiscovered
wall, stuck detection triggers re-pathing with updated knowledge.

**Configuration-space expansion**: the 7x7 player bounding box means the
agent cannot pass through gaps narrower than 7px (~4 grid cells at 2:1).
A* expands walls by the player's half-width (3px → 2 grid cells) to compute
the free configuration space. This ensures paths are physically navigable.

#### Dynamic obstacles (other players)

Other players block movement (the server rejects moves that increase
overlap). They are **not** part of the occupancy grid because they are
transient. Instead:

- Player positions are tracked in the player registry (from minimap and
  viewport observations), updated each tick regardless of viewport-confirmed
  status.
- The `move_to` / `follow` tasks detect "stuck" via ActionMemory (position
  unchanged across N ticks despite movement commands).
- Stuck detection triggers re-pathing around the obstruction, or escalates
  to the mode for a strategy change.

---

## Belief update pipeline

The belief update phase integrates perception output into the persistent
belief state. It runs every tick, after perception and before decide. Its
behavior depends on the perceived view — different views contribute different
information.

**Preservation rule**: fields not mentioned in a view's update rules are
preserved unchanged from the previous tick. The belief update only modifies
what it explicitly specifies.

### Universal updates (every tick, regardless of view)

- `tick` — incremented unconditionally.
- `view` — set to `perception.view`.
- `in_whisper` — set to `(perception.view == View.WHISPER)`. This is the
  single source of truth for whisper presence.
- **On `in_whisper` transition from True to False**: clear
  `whisper_occupants`, `pending_offers`, `pending_entry`, `menu_state`.
  These fields are only meaningful while in a whisper.
- `cooldowns` — tick down toward zero (independent of what's on screen).

### Per-view updates

#### Lobby

- **On first Lobby detection after a non-Lobby view** (game reset): clear
  the entire belief state back to initial values. This handles the
  GameOver → Lobby transition.
- `player_count` — from `perception.lobby.player_count`.

#### RosterReveal

- `players` registry — populate (color, shape, room) for every player shown
  on the roster screen. This is the first opportunity to learn room
  assignments and establish the full player index mapping.

#### RoleReveal

- `my_role` — from `perception.role_reveal.role`.
- `my_team` — from `perception.role_reveal.team`.
- `my_room` — from `perception.role_reveal.room`.
- `room_size` — from `perception.role_reveal.room_size`.
- `round_schedule` — from `perception.role_reveal.schedule` (round durations
  and hostage counts, if perception extracts them).
- `occupancy_grid` — **initialized** once `room_size` is known (border cells
  marked WALL, interior UNKNOWN).
- `my_color`, `my_shape`, `my_index` — from observing own sprite on the role
  reveal screen (rendered centered at x=60, y=8). The player's sprite color
  is `PLAYER_COLORS[index % 8]` and shape is `PlayerShape(index % 12)`.
  Once color and shape are observed, the player index is decoded from the
  `(color, shape)` pair (unique for up to 24 players). All three fields are
  set together.

These fields are set once and not overwritten on subsequent ticks (they are
static for the duration of the game). Note: `my_color` and `my_shape` can
also be learned during Lobby (own sprite is visible) or RosterReveal — the
first successful observation populates them.

#### Overworld family (Playing, HostageSelect, LeaderSummit, WaitingEntry)

All views that show the game world with minimap:

- `position` — from `perception.overworld.self_position`.
- `room` — from `perception.overworld.room`.
- `round` — from `perception.overworld.round`.
- `timer_secs` — from `perception.overworld.timer_secs`.
- `players` registry positions — updated from minimap dots (color → candidate
  indices) and viewport sprite observations (color + shape → exact index).
- `players` registry `last_seen_in_whisper` — for each speech bubble
  observed (from `perception.overworld.speech_bubbles`), set the identified
  player's `last_seen_in_whisper` to the current tick. This signals that the
  player is currently in a whisper and can be approached for entry.
- `players` registry role/team — for each player sprite observed with a role
  indicator (visible below sprites for self and revealed players), update
  role/team fields. Source: `game_display`.
- `occupancy_grid` — updated from viewport pixels and minimap obstacle dots
  (see spatial knowledge section above). **Only runs when an overworld-family
  view is active** — non-overworld frames do not touch the grid.
- `is_leader` — from HUD role text suffix (`*`) or crown indicator on self.
- `leader_colors` — from crown indicators on visible players.
- `chat_history` — if `perception.overworld.last_shout` is present and not
  already recorded (deduplicate by text + sender color), append with
  channel=`shout`, sender identified from `last_shout_color` (color →
  candidate player indices). The shout strip shows the most recent global
  message in the sender's player color.

**HostageSelect-specific:**
- `hostage_selections` — if leader, from hostage grid in global chat view.

**WaitingEntry-specific:**
- Overworld data is still extracted (minimap, position, etc.) alongside the
  waiting state.

#### Whisper

- `whisper_occupants` — from `perception.chatroom.occupant_colors` (mapped
  to player indices via color+shape when available, or color-only candidates
  otherwise).
- `chat_history` — append new messages from `perception.chatroom.messages`
  (deduplicated against already-seen messages by position/content). Each
  appended message is tagged with the current `whisper_occupants` list,
  recording who was present when the message was observed.
- `my_exchange_partner` — when a system message matching "shared roles" is
  observed and one of the two participant sprites is self, set
  `my_exchange_partner` to the other participant's index. Also update the
  player registry for both participants with source `mutual_exchange`.
- `pending_offers` — from `perception.chatroom.bottom_bar` offer indicators.
- `pending_entry` — from `perception.chatroom.has_pending_entry` and
  `pending_entry_color`.
- `menu_state` — from `perception.chatroom.bottom_bar` menu/target state.

#### Global Chat

- `chat_history` — append new global messages from
  `perception.global_chat.messages`.
- `leader_colors` — may be observable from usurp candidate display.
- `hostage_selections` — from `perception.global_chat.hostage_grid` (if
  leader during HostageSelect).

#### Info Screen

- `players` registry — update role/team knowledge from
  `perception.info_screen.known_players` (source: `game_display`).

#### Exchange (HostageExchange)

- `players` registry — update role/team knowledge for all visible exchanged
  players from `perception.exchange.leaders`, `.departing`, `.arriving` (each
  carries a `role_indicator`). Source: `game_display`.
- `players` registry room assignments — hostages departing our room are now
  in the other room; hostages arriving are now in our room.

#### Reveal / GameOver

- `winner` — from `perception.result.winner`.
- No other updates — the framework does not extract the full revealed state
  during these phases (perception limitation, noted as a gap).

#### Lobby (post-game)

- Handled by the reset logic above (first Lobby detection after non-Lobby).

### Movement confirmation (implicit, overworld family only)

If `position` changed from the previous tick, all grid cells covered by the
player's 7x7 bounding box at the new position are marked `FREE` +
viewport-confirmed. This provides traversability data without explicit
viewport scanning.

### What the belief update does NOT do

- It does not make inferences, guesses, or strategic assessments. Those
  belong to modes (via `select_task`) or the outer loop (`meta_decide`).
- It does not filter or interpret chat messages. It records them verbatim.
- It does not track "who might be lying." Provenance tags distinguish
  mechanical revelation from chat claims, but the update phase does not
  evaluate trustworthiness.

---

## Hook API

Hooks allow agents to inject custom logic at phase boundaries in the inner
loop pipeline. Hooks are registered via a framework method and called
serially when the hook event fires.

### Hook points and signatures

Each hook point has a typed signature reflecting exactly what data is
available at that moment in the pipeline.

| Hook point | Arguments | May mutate |
|---|---|---|
| `pre_perception` | `(frame, belief_state)` | frame (in-place), belief_state (direct) |
| `post_perception` | `(frame, perception, belief_state)` | belief_state (direct) |
| `pre_belief_update` | `(perception, belief_state)` | belief_state (direct) |
| `post_belief_update` | `(belief_state)` | belief_state (direct) |
| `pre_decide` | `(belief_state, action_memory)` | belief_state (direct) |
| `post_decide` | `(belief_state, action_memory)` | belief_state (direct) |
| `pre_act` | `(belief_state, action_memory)` | belief_state (direct) |
| `post_act` | `(belief_state, action_memory, act_command)` | belief_state (direct) |

- `frame`: raw pixel array (128x128 uint8). Mutable in-place only in
  `pre_perception`.
- `perception`: the `FramePerception` output. Read-only.
- `belief_state`: current belief state. Mutable — hooks modify fields
  directly. Mutations are immediately visible to subsequent hooks at the
  same hook point.
- `action_memory`: current action memory. Read-only.
- `act_command`: the action output for this tick. Read-only.

### Return value

Hooks return `None`. All mutations are performed directly on the belief
state object passed as an argument. Sequential hooks at the same hook point
see each other's changes immediately (no deferred application).

`pre_perception` is the exception: it returns the frame (possibly modified,
or the original). This allows frame preprocessing (e.g., noise filtering)
without requiring the hook to mutate the frame array in-place, though
in-place mutation is also permitted.

### Registration

Hooks are registered via a framework method:

```
register_hook(hook_point, callback, modes=None)
```

- `hook_point`: which phase boundary to attach to.
- `callback`: the hook function (signature must match the hook point).
- `modes`: optional list of mode names. If provided, the hook fires only
  when the active mode is in this list. If `None`, the hook is agent-level
  and fires regardless of active mode.

### Execution order

1. **Agent-level hooks** fire first, in FIFO registration order.
2. **Mode-level hooks** (for the currently active mode) fire second, in FIFO
   registration order.

No interleaving between agent-level and mode-level hooks.

### Error handling

If a hook raises an exception, the error is caught and logged. The pipeline
continues with the next hook (or next phase). Hooks must not assume prior
hooks succeeded.

---

## Outer loop

The outer loop handles long-term strategic reasoning. It runs
**asynchronously** alongside the inner loop, connected by two buffers.

### Architecture

```
          Inner loop                              Outer loop
         (per-tick)                              (async)

  ... → post_belief_update →─┐
                              │ push (consume old)
                              ▼
                     ┌─────────────────┐
                     │  Belief buffer  │  size-1, consume-on-read
                     └────────┬────────┘
                              │ block until non-empty, then consume
                              ▼
                        meta_decide(belief_state, action_memory)
                              │
                              │ push (consume old)
                              ▼
                     ┌─────────────────┐
                     │  Mode buffer    │  size-1, consume-on-read
                     └────────┬────────┘
                              │ consume if non-empty (non-blocking)
  ... → pre_decide ←─────────┘
```

### Buffers

Both buffers are size-1 with **consume-on-read** semantics. Reading empties
the buffer; the item is gone after consumption. Writing overwrites any
unconsumed item (latest-wins).

**Belief buffer** (inner → outer):
- Contents: deep copy of `(belief_state, action_memory)`.
- Written by the inner loop every tick, after post_belief_update hooks fire.
  Overwrites any prior unconsumed value. The deep copy ensures the outer
  loop reads a consistent snapshot unaffected by subsequent inner-loop
  mutations.
- Read by the outer loop at the start of each iteration. The outer loop
  **blocks** until the buffer is non-empty, then consumes it. This naturally
  throttles the outer loop to at most once per inner-loop tick.

**Mode buffer** (outer → inner):
- Contents: `(ModeDirective, dict | None)`.
- Written by the outer loop after `meta_decide` returns.
- Read by the inner loop each tick, between post_belief_update and pre_decide.
  If the buffer is non-empty, the inner loop consumes it — applies the
  belief state updates (if any) and processes the mode directive. If empty,
  the inner loop continues with the current mode unchanged.

### meta_decide

```
meta_decide(belief_state, action_memory) -> (ModeDirective, dict | None)
```

Called once per outer-loop iteration with the consumed belief state and
action memory snapshots (both read-only — the outer loop cannot mutate the
inner loop's live state). Returns:

- `ModeDirective`: a complete mode specification — mode type + parameters.
  May be the same as the current mode (reaffirmation) or a new mode
  (transition).
- `dict | None`: optional belief state updates to apply when the inner loop
  consumes the mode buffer. Keys are top-level belief state field names;
  values replace the corresponding fields. Used for LLM-derived inferences
  (e.g., `{"players": updated_registry}`) that the outer loop wants to
  inject into the inner loop's live state. `None` means no updates.

The internals of `meta_decide` are **agent-defined**. Implementations may:
- Call an LLM with a summary of belief state + agent directives.
- Run a symbolic rule system.
- Use a hybrid approach.

### Timing and staleness

The outer loop's decision is based on the belief state snapshot it consumed.
If `meta_decide` takes significant time (e.g., 1-2s for an LLM call), the
snapshot may be 24-48+ ticks stale by the time the ModeDirective reaches the
inner loop. This is acceptable because:

1. The inner loop's `select_task` handles changing conditions reactively
   each tick — it is not relying on the outer loop for tactical correction.
2. Mode-level decisions are strategic and should be robust to short-term
   state drift.
3. The framework applies the ModeDirective regardless of staleness — it is
   the outer loop's responsibility to produce decisions that age gracefully.

Agent developers should design their LLM directives and mode definitions
with this latency in mind. Modes should represent durable strategic intents
(e.g., "find Cerberus", "defend against hostage exchange"), not momentary
reactions.

### Initial mode

Before the outer loop produces its first ModeDirective, the inner loop uses
a **default initial mode**. The framework provides a built-in `idle` mode
(returns `IdleTask()` regardless of game phase) as the default. Agents may
override this by specifying a different initial mode at construction.

The initial mode must handle all game phases gracefully — the agent may
connect during Lobby, RosterReveal, RoleReveal, or mid-game. Since the
framework is phase-agnostic, the initial mode receives whatever view
perception detects and must not assume the game is in any particular state.

### Non-blocking guarantee

The inner loop **never blocks** on the outer loop. Each tick it:
1. Pushes to the belief buffer (non-blocking overwrite).
2. Attempts to consume from the mode buffer (non-blocking; proceeds with
   current mode if empty).

If the outer loop is slow, crashes, or is absent entirely, the inner loop
continues operating in its current mode indefinitely.

---

## Mode switching

Mode switching occurs when the inner loop consumes a `ModeDirective` from
the mode buffer that differs from the current mode (type or params).

### Trigger

Each tick, between post_belief_update and pre_decide, the inner loop checks
the mode buffer:

1. **Buffer empty** → no-op; continue with current mode.
2. **ModeDirective identical** to current mode type + params → no-op
   (reaffirmation).
3. **ModeDirective differs** → trigger mode switch (sequence below).

### Mode switch sequence

```
1. Apply belief state updates from mode buffer entry (if any)
2. Run mode-switch callbacks (may mutate belief state, may override directive)
3. Run OLD mode's mode_switch_cleanup (may mutate belief state)
4. Activate new mode
5. Run NEW mode's mode_enter (may mutate belief state, may return initial task)
6. Continue to pre_decide phase
```

**Step 1**: The optional `dict` bundled with the `ModeDirective` in the mode
buffer is applied first (top-level field assignment on the belief state).

**Step 2**: Registered mode-switch callbacks fire in order (agent-level
first, then mode-level for the old mode, FIFO within each group). Each
callback receives:

```
mode_switch_callback(belief_state, action_memory, mode_directive) -> ModeDirective | None
```

- `belief_state`: mutable — callbacks modify fields directly.
- `action_memory`: read-only.
- `mode_directive`: read-only — the currently planned transition target.

Returns `None` to leave the mode directive unchanged, or a new
`ModeDirective` to override it (e.g., intercept a transition and redirect
to a different mode). Returned directives are validated (mode exists in
registry, params type matches) before acceptance — invalid overrides are
logged and discarded. Later callbacks see belief state changes from earlier
ones and receive the potentially-modified directive.

**Step 3**: The old (departing) mode's cleanup method runs:

```
Mode.mode_switch_cleanup(belief_state, action_memory, new_mode_directive) -> None
```

Receives the final mode directive (as potentially modified by callbacks).
Mutates belief state directly for teardown, persisting mode-specific state,
etc. May be a no-op.

**Step 4**: The framework activates the new mode (as specified by the final
`ModeDirective` after all callback modifications).

**Step 5**: The new mode's entry method runs:

```
Mode.mode_enter(belief_state, action_memory) -> Task | None
```

One-time initialization for the mode. Mutates belief state directly to set
up mode-specific fields, reset counters, etc. Returns an optional initial
task — if `None`, the framework waits for `select_task` on the next decide
phase. If a `Task` is returned, it becomes the active task immediately
(avoiding one tick of no-op).

**Step 6**: Pipeline resumes with pre_decide. The new mode's `select_task`
will be called during the decide phase.

### ActionMemory on mode switch

ActionMemory is **not** cleared by a mode switch. It clears only when the
task changes (per the task lifecycle rules). If the new mode's first
`select_task` call selects the same task as the old mode, execution
continues uninterrupted.

### Required mode methods

Every mode must implement:

| Method | Purpose |
|--------|---------|
| `select_task(belief_state, action_memory) -> Task | None` | Per-tick task selection (decide phase) |
| `mode_enter(belief_state, action_memory) -> Task | None` | One-time setup on activation |
| `mode_switch_cleanup(belief_state, action_memory, new_mode_directive) -> None` | Teardown when being replaced |

---

## Open design questions

### Critical (blocks implementation)

1. ~~**`BeliefStateDelta` is undefined.**~~ **Resolved**: eliminated. Modes,
   hooks, and tasks mutate state directly. The outer loop sends a plain
   `dict | None` of top-level field assignments across the async boundary.

2. ~~**`ModeDirective` is partially undefined.**~~ **Resolved**: frozen
   dataclass with `mode` (registry key) and `params` (per-mode frozen
   dataclass subclassing `ModeParams`). Equality is structural. Params are
   validated against the target mode's declared `params_type` at consumption
   time. `ModeDirectiveDelta` eliminated — callbacks return
   `ModeDirective | None` to override.

3. ~~**`select_task` buries task selection in a delta.**~~ **Resolved**:
   `select_task` now returns `Task | None` explicitly. `None` = keep current
   task.

### Significant (requires design decisions before implementation)

4. ~~**No game lifecycle management.**~~ **Resolved**: the framework is
   phase-agnostic. The pipeline runs identically every tick. Phase-specific
   behavior is the responsibility of the belief update pipeline (which
   integrates perception per-view) and agent modes (which decide what to do
   based on `belief_state.view`). Game reset is handled by the belief update
   clearing state on Lobby detection after a non-Lobby view. Identity fields
   are populated when perception returns RoleReveal/RosterReveal data.

5. ~~**No phase-transition awareness.**~~ **Resolved by design**: the
   framework does not special-case phase transitions. Modes observe
   `belief_state.view` changing and adapt (e.g., returning `IdleTask()` when
   the view is non-interactive, or abandoning a whisper menu sequence when
   `in_whisper` becomes `False`). The framework's only responsibility is
   ensuring the belief state accurately reflects the current phase — which
   the belief update pipeline handles.

6. ~~**No task-to-mode escalation channel.**~~ **Resolved — by design.** Tasks
   return `ActCommand` with no status signal, which is correct because tasks
   have no privileged feedback channel from the server. The only evidence of
   whether a command succeeded is what perception observes on subsequent ticks
   — the same evidence available to the mode via belief state. Adding status
   reporting to tasks would duplicate observer logic that belongs in the mode.
   Tasks record what they sent (in ActionMemory); modes infer progress from
   belief state. Stuck detection is a mode responsibility — implemented by
   checking position change, view transitions, or other belief state evidence
   across ticks.

7. ~~**Whisper entry vs. creation ambiguity.**~~ **Resolved.** The
   `request_entry` task checks preconditions from belief state before
   pressing B/K: target player must have a recent `last_seen_in_whisper`
   tick (confirming speech bubble was observed) and must be within
   interaction proximity. If preconditions are not met, the task outputs
   a no-op rather than risking accidental whisper creation. Modes may
   add additional checks before issuing the task, but the task itself
   is not "blindly press B."

8. ~~**Whisper occupant identification gap.**~~ **Resolved.** Perception
   runs shape classification (via `detect_sprite_shape()`) on whisper
   header sprites in addition to color extraction. The header renders
   standard 7x7 sprites at known positions (x=22, stride 9, y=1-7),
   which are the same templates used in overworld detection. With both
   color and shape, perception returns unambiguous player indices for
   whisper occupants. When shape detection fails (e.g., full shadow
   collision), the occupant is reported with color-only candidates —
   the belief update handles this as a narrowed candidate set resolved
   via context (room assignments, prior observations).

9. ~~**`wander` memory doesn't survive task interruption.**~~ **Resolved.**
   The occupancy grid's viewport-confirmed flag already tracks which cells
   the agent has directly observed. Cells lacking viewport-confirmed status
   are "unexplored" — exactly what wander needs to target. This data lives
   in belief state, persists across task and mode changes, and is maintained
   by the framework's belief update pipeline. The `wander` task reads the
   grid from belief state and targets unconfirmed cells. No task-level
   exploration memory needed.

10. ~~**No view-change safety check in act phase.**~~ **Resolved.** Tasks
    declare a `valid_views` field — a set of `View` values in which the
    task can operate. Before calling `task.select_action`, the framework
    checks `belief_state.view` against `task.valid_views`. On mismatch,
    the framework outputs a no-op (`ActCommand()`) for that tick without
    calling the task. The mode's next `select_task` sees the view change
    in belief state and selects an appropriate task. Tasks with broad
    applicability (e.g., `idle`) declare multiple valid views. This is a
    declarative safety net — tasks may still perform additional internal
    checks, but the framework guarantees they never execute in a view
    they weren't designed for.

11. ~~**Outer loop belief dict injection is untyped and unsandboxed.**~~
    **Resolved.** The outer loop's `dict | None` return writes exclusively
    to `belief_state.inferences` — a dedicated namespace for LLM-derived
    or outer-loop-produced data. The dict may be arbitrarily nested (not
    flat). Framework-managed fields (`tick`, `position`, `view`,
    `occupancy_grid`, `players`, etc.) are not writable by the outer loop.
    Modes read `belief_state.inferences` to access outer loop output (e.g.,
    `belief_state.inferences["player_assessments"][3]["suspected_role"]`).
    The framework applies the returned dict as a deep replace of
    `belief_state.inferences` — each outer loop iteration overwrites the
    previous inferences entirely (the outer loop is responsible for
    including anything it wants to persist). `meta_decide` signature
    remains `(ModeDirective, dict | None)` — `None` means no inference
    update; a dict replaces `belief_state.inferences` wholesale.

12. **RosterReveal has no perception specification.** The belief update
    references `RosterReveal` and says it populates the player registry
    with (color, shape, room) for all players. But the perception design
    doc has no `ROSTER_REVEAL` view enum, no detection rule, and no
    `RosterRevealPerception` dataclass. The `_roster_reveal.py` file
    exists in code but the design contract is unspecified.

13. **No outer loop death recovery.** The non-blocking guarantee ensures
    the inner loop continues if the outer loop crashes, but it continues
    in whatever mode was last set — potentially `idle`. No watchdog, no
    fallback mode promotion, no "N ticks without directive → escalate."
    In a 3-minute game, an early outer loop crash means a fully inert
    agent.

14. **Chat history grows unbounded.** `chat_history` accumulates from
    three channels for the entire game with no pruning specification.
    Each entry carries sender, tick, channel, text, and full occupant
    list. At max chat rate across 10 players for 180s, this can reach
    hundreds of entries. The outer loop copies the entire thing every
    tick for the belief snapshot. No max-length, no TTL, no summarization
    boundary defined.

15. **Minimap color→index ambiguity has no resolution model.** Up to 3
    player indices share a color. The belief update says positions are
    "updated from minimap dots" but doesn't specify how ambiguous
    sightings are stored — does it update all candidates? Pick the
    nearest? Create a probabilistic sighting? The player registry has
    a single `position` per player with no representation for "one of
    players {0, 8, 16} is at position X."

16. **`mode_enter` Task vs. `select_task` ordering on the same tick.**
    If `mode_enter` returns a Task, it becomes active immediately (step
    5). Then the pipeline resumes at pre_decide, and `select_task` runs
    during decide phase. Does `select_task` see mode_enter's task as the
    "current task" and return None to affirm it? Or might it replace it
    immediately, wasting the mode_enter setup? The interaction needs
    clarification.

17. **No A* pathfinding parameters specified.** Grid connectivity
    (4-dir vs 8-dir), heuristic function, path smoothing from grid
    waypoints to world coordinates, max search iterations / timeout,
    and behavior on unreachable goals are all unspecified.

18. **Rising-edge button sequencing timing undefined.** Menu navigation
    requires press/release alternation (server reads rising edges). The
    doc says this is "handled by shared infrastructure in ActionMemory"
    but doesn't specify: minimum press duration (1 tick?), guaranteed
    release between presses, or behavior when a mode switch interrupts
    mid-sequence.

19. **Occupancy grid coordinate precision gap.** Viewport→world mapping
    depends on camera position, which derives from self-position, which
    may be a minimap estimate (±roomW/20 px). Config-space expansion
    ("3px → 2 grid cells" at 2:1) involves a rounding decision (1.5
    cells) that isn't specified. Floor vs ceil determines whether the
    agent attempts gaps it can't fit through.

20. **Flexible belief state namespace collisions.** Modes create
    arbitrary keys in the belief state for their own use. No namespacing
    convention exists. Two modes using the same key (e.g., `"target"`)
    stomp each other silently. `mode_switch_cleanup` is expected to
    clean up manually, but nothing enforces it. The outer loop's LLM
    sees all mode-specific state in its belief snapshot — polluting the
    prompt with irrelevant internal bookkeeping.

### Minor (solvable locally but worth noting)

21. **No urgency/interrupt mechanism.** Outer loop may take 1-2s; no "kick"
    to force re-evaluation when something urgent happens (becoming leader
    mid-HostageSelect, key player appearing).

22. **Hook error handling too permissive.** Catch-and-continue means
    half-applied state (now via direct mutation, not partial deltas), silent
    corruption, difficult debugging.

23. **No position precision tracking.** Player registry doesn't distinguish
    ±5px viewport observations from ±(roomW/20)px minimap estimates.

24. **`send_message` channel conflict unspecified.** What happens when
    desired channel (global) conflicts with player state (in whisper)?

25. **Missing task: cancel whisper entry request.** Game supports B-press
    while WAITING_ENTRY. No task exists for giving up on entry.

26. **Missing task: scroll.** Chat messages scroll off screen. No way to
    recover history that perception can't see on the current frame.

27. **Cooldown tracking assumes action acceptance.** Server silently drops
    rate-limited actions. Framework cooldown tracker can drift from reality.

28. **Leader change detection is fragile.** Usurp and PASS/TAKE happen in
    contexts the agent may not be observing. No staleness detection for
    `leader_colors`.

29. **No tracing/debugging specification.** Decision logging, mode transition
    timeline, outer loop staleness visibility — all absent.

30. **ActionMemory read interface unspecified.** Modes receive action_memory
    as read-only but its structure is per-task and never documented. Modes
    can't reliably inspect it for status information.

31. **Leader summit behavioral gap.** The view is detected and spatial data
    extracted, but there are no summit-specific tasks, no guidance on what
    leaders do during the summit, and no specification of the negotiation
    interface (if any).

32. **`follow` task has no proximity threshold.** Unlike `move_to` (complete
    when position matches), `follow` never completes. Unclear when the agent
    stops moving — adjacent? Overlapping? A configurable distance?

33. **Rate limit scope ambiguous.** The 48-tick cooldown applies to "whisper
    actions and chat messages" — but is the rate limit per semantic action
    (e.g., "role offer") or per confirm button press? Does navigating the
    menu (open menu → select category → select item → confirm) count as one
    action or multiple? Are sequential tasks (offer then exit) gated by a
    single shared cooldown?

34. **`select_hostages` depends on perception feedback mid-execution.** The
    task must toggle specific grid cells, but cursor position is only known
    from perception (previous tick's frame). Multi-step sequences with
    visual feedback operate on 1-tick-stale data. For fast sequences this
    may cause misstoggling.

35. **No connection failure or game-full handling.** The framework assumes
    successful WebSocket connection. No retry, no error state, no "game
    full" path.

36. **No testing strategy.** The system has async loops, mutable shared
    state, multi-tick tasks, and LLM integration — but no specification
    for how to unit-test modes, integration-test the inner loop without a
    server, or regression-test mode switching edge cases.

37. **No LLM prompt construction guidance.** `meta_decide` receives the
    full belief state (spatial grid, player registry, chat history) but
    no guidance on how to summarize it for an LLM context window. The
    occupancy grid alone (10K cells) cannot be passed verbatim.
