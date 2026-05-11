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
- A **fallback mode** (activated by the watchdog if the outer loop dies).
- Optional **inter-stage hooks**.

**Scope boundary**: this document specifies the framework only — the
pipeline, the interfaces, the task catalogue, and the execution semantics.
It does not design any concrete agent, mode, or `meta_decide`
implementation. Mode names used in examples (e.g., `FindPlayerMode`,
`ExploreMode`) are illustrative placeholders, not framework-provided
components.

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
| `mode_enter(belief_state, action_memory) -> None` | Once, on activation | One-time setup when mode becomes active |
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
and calling semantics. `mode_enter` performs one-time setup (mutating
belief state to initialize mode-specific fields); it does not select
tasks. `mode_switch_cleanup` handles teardown.

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
    params: ModeParams = field(default_factory=ModeParams)
                          # Defaults to bare ModeParams for parameterless modes
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

Each task also declares:

```
Task.valid_views: set[View]
```

The `valid_views` field specifies which game views the task can operate in.
Before calling `select_action`, the framework checks `belief_state.view`
against `task.valid_views`. On mismatch, the framework outputs a no-op
(`ActCommand()`) for that tick without calling the task — the mode's next
`select_task` sees the view change and selects an appropriate task.

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

**Standard fields** (maintained by the framework, read-only to modes):

| Field | Type | Description |
|-------|------|-------------|
| `ticks_active` | int | Ticks since the current task started |
| `commands_sent` | int | Count of non-noop ActCommands emitted |
| `last_command` | ActCommand | Most recent ActCommand output |
| `command_history` | ring buffer (size 16) | Recent ActCommands for pattern detection |

These are universally available regardless of task type, allowing modes to
detect stuck conditions (e.g., same movement mask repeated 20 times) without
knowing task-specific internals.

**Task-specific fields**: tasks may store additional fields (path waypoints,
menu navigation state, sequence step, etc.). These are documented per-task
type so agent developers can write modes that inspect them when the current
task type is known. Modes receive action_memory as read-only — they inspect
but do not mutate.

**Rising-edge sequencing infrastructure**: ActionMemory includes shared
press/release state management used by all button-sequencing tasks. The
minimum cycle is 2 ticks (1 tick pressed + 1 tick released). This
infrastructure guarantees proper alternation for menu navigation and all
multi-press sequences.

### Task catalogue

#### Movement

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `move_to` | `x, y` | A* pathfinding to target; outputs directional masks along waypoints | Position matches target |
| `follow` | `player_index, stop_distance=10` | A* path to target's last-known position; re-paths when target moves; no-ops within stop_distance | Never — mode switches away |
| `wander` | — | Exploratory movement pattern (random waypoints, avoid revisiting areas) | Never — mode switches away |

#### Chatroom lifecycle

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `create_whisper` | — | Press A/J in current position (mode ensures open space) | View → whisper |
| `request_entry` | `player_index` | A* path to target player, A-press when close. Checks preconditions before pressing: target must have recent `last_seen_in_chatroom` tick and be within interaction proximity. No-ops if preconditions unmet | View → whisper (or WAITING state) |
| `cancel_entry` | — | Press B while WAITING_ENTRY | View → overworld |
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
| `select_hostages` | `player_indices[]` | In the hostage-selection UI (and legacy global-chat grid), navigate hostage grid, toggle each target, commit | View transitions / timer expires |

#### Communication

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `send_message` | `text, channel=auto` | Send a `PACKET_CHAT` with `buttons=0`; no button press is required. `channel` controls routing assertion: `auto` (default) sends regardless of state; `chatroom`/`whisper` require whisper-like state (`in_whisper` or leader summit); `global` no-ops in whisper-like state. Respects chat cooldown internally | Message appears in chat history |

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

- Most whisper menu tasks (information exchange and leadership) share
  internal menu-navigation logic: open menu (B) → navigate category
  (left/right) → navigate item (up/down) → confirm (A) → optionally navigate
  target picker (left/right) → confirm (A). Because the live server samples
  rising-edge inputs and menu OCR is partial, menu navigation holds each
  button for two ticks and releases for two ticks before advancing. `GRANT`
  currently uses a fixed robust sequence for the same reason.

- `request_entry` bundles approach + button press into one task. The mode
  doesn't need to micromanage proximity — the task handles both pathfinding
  and the A-press. The task validates preconditions from belief state before
  pressing A (target's `last_seen_in_chatroom` is recent, target is within
  proximity) to avoid accidentally creating a chatroom in open space.

- `follow` is distinct from repeated `move_to(player_pos)` to avoid clearing
  ActionMemory (and re-computing A*) every tick the target moves. Its identity
  is `("follow", player_index, stop_distance)`, stable regardless of target
  position. Outputs no-op movement when within `stop_distance` of target.

- `send_message` respects the chat cooldown internally, outputting no-op
  commands until the cooldown expires. When it sends, it emits an `ActCommand`
  with `chat_text` populated and `buttons=0`. The mode can re-affirm the task
  each tick without concern for timing.

- Task completion is never self-reported. Tasks have no privileged feedback
  channel from the server — the only evidence of whether a command succeeded
  is what perception observes on subsequent ticks. Modes infer progress and
  completion from belief state. Stuck detection is a mode responsibility,
  aided by ActionMemory's standard fields (`ticks_active`, `command_history`).

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
  - `position` — last-known `(x, y, tick)` from viewport sprite observation
    (unambiguous color + shape). Minimap sightings are stored separately
    in `minimap_sightings` due to color ambiguity.
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
  the framework when actions are sent (with conservative padding: server
  cooldown + 2 ticks). Tasks consult this to respect per-action rate limits:
  48 ticks for whisper chat, 240 ticks for menu actions and shout.

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
  leader. Parsed from the hostage-select view; legacy global-chat hostage-grid
  parsing is still accepted.

**Social / knowledge:**
- `chat_history` — all messages observed (whisper + global + shouts),
  with sender index, tick, channel (whisper/global/shout), and for
  whisper messages: the list of occupant indices present when the message
  was sent. This captures not just who said what, but who they intended to
  hear it. The framework stores all messages without pruning — chat history
  management (windowing, summarization, TTL) is an agent-level concern,
  implementable via hooks or the outer loop.
- `my_exchange_partner` — player index we have completed a mutual role
  exchange with (satisfies win condition), or None

**Spatial observations:**
- `minimap_sightings` — list of `(color, position, tick)` tuples from
  minimap dots. Raw observations without index resolution — disambiguation
  is agent-level logic. Appended each tick for each non-self minimap dot
  observed. Agents may prune via hooks.

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
- `leader_last_confirmed_tick` — per room, tick when leadership was last
  confirmed (crown indicator observed or leadership system message
  processed). Agent implementations decide how much to trust stale data.

**Task (framework-managed, read-only to modes):**
- `current_task` — active task identifier + parameters (set by the framework
  from `select_task`'s return value; exposed for hooks and outer loop
  visibility)

**Outer loop inferences (written by outer loop only):**
- `inferences` — dedicated namespace for LLM-derived or outer-loop-produced
  data. Arbitrarily nested dict. Replaced wholesale each time the outer loop
  produces output. Modes read from this to access strategic assessments
  (e.g., `inferences["player_assessments"][3]["suspected_role"]`). Framework-
  managed fields are not writable by the outer loop — this namespace is the
  only channel for outer loop → belief state data (beyond mode directives).

**Flexible space:**
- All other keys are mode-defined. Modes may create arbitrary nested
  structures for their own use. Multiple modes intentionally reading/writing
  the same keys is a valid pattern (e.g., shared counters, cross-mode
  coordination). Agent developers manage their own namespace — standard
  shared-memory discipline applies.

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

**Position source requirement**: self-position is always derived from direct
viewport/camera localization (floor grid dots provide exact camera offset
within 1-2 ticks). Self-position is **never** estimated from the minimap —
the minimap is too imprecise for the grid mapping above. This is an explicit
requirement on the perception module.

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

The occupancy grid is the cost map for A* with **8-directional connectivity**
(matching player movement capabilities):
- `WALL` → impassable
- `FREE` → cost 1 (√2 for diagonals)
- `UNKNOWN` → treated as traversable (optimistic pathfinding)

Optimistic handling of `UNKNOWN` is appropriate because rooms are mostly
open space with few obstacles. If movement is blocked by an undiscovered
wall, stuck detection triggers re-pathing with updated knowledge.

**Configuration-space expansion**: the 7x7 player bounding box means the
agent cannot pass through gaps narrower than 7px (~4 grid cells at 2:1).
A* expands walls by the player's half-width (3px → 2 grid cells) to compute
the free configuration space. This ensures paths are physically navigable.
The expansion value is an implementation tuning parameter.

**Grid resolution**: the default 2:1 ratio (one grid cell per 2x2 world
pixels) is tunable. The map geometry is simple (room-edge walls + regularly
spaced 8x8 pillars) and narrow-gap navigation is unlikely to be a critical
bottleneck.

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
- `players` registry positions — updated from viewport sprite observations
  (color + shape → exact index → position update in registry).
- `minimap_sightings` — append `(color, position, tick)` for each non-self
  minimap dot. These are raw observations; disambiguation into player
  indices is agent-level logic.
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
- `hostage_selections` — if leader, from the hostage-select grid.

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
  leader during HostageSelect in legacy/global-chat rendering).

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

Before invoking each hook, the framework takes a deep copy of the belief
state. If the hook raises an exception:

1. The belief state is **rolled back** to the pre-hook snapshot, undoing any
   partial mutations the hook made before crashing.
2. The error is logged with full context: hook name, hook point, active mode,
   current tick, and exception traceback.
3. The pipeline continues with the next hook (or next phase).

This ensures hook failures never corrupt belief state while keeping the agent
operational. Hooks must not assume prior hooks succeeded (a prior hook may
have been rolled back).

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
  inferences update (if any) to `belief_state.inferences` and processes the
  mode directive. If empty, the inner loop continues with the current mode
  unchanged.

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
- `dict | None`: optional inferences to write into `belief_state.inferences`.
  Replaces the entire `inferences` namespace wholesale — the outer loop is
  responsible for including anything it wants to persist from previous
  iterations. `None` means no inference update. The dict may be arbitrarily
  nested. Framework-managed belief state fields are not writable by the outer
  loop; this namespace is the only data channel from outer loop to inner loop
  state (beyond mode directives).

The internals of `meta_decide` are **agent-defined**. Implementations may:
- Call an LLM with a summary of belief state + agent directives.
- Run a symbolic rule system.
- Use a hybrid approach.

How `meta_decide` summarizes the belief state for an LLM (serialization,
filtering, prompt construction) is entirely the agent's responsibility —
different agents may focus on different aspects and require radically
different summarization strategies.

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

### Resilience: watchdog and restart

The framework provides two mechanisms to handle outer loop failure:

**Watchdog**: the framework tracks `ticks_since_last_mode_directive`. If it
exceeds a configurable threshold (default: 120 ticks = 5 seconds), the
framework activates a **fallback mode** specified by the agent at
construction time. The fallback mode is agent-defined (like all modes) and
should provide reasonable default behavior for any game phase (e.g.,
wander + accept exchanges). The watchdog fires once; subsequent outer loop
output resumes normal mode switching.

**Outer loop restart**: the framework monitors the outer loop thread/task.
If it terminates unexpectedly (exception, crash), the framework restarts it.
The restarted instance blocks on the belief buffer as usual and resumes
producing ModeDirectives normally. Restart is logged at the `events` level.

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
5. Run NEW mode's mode_enter (may mutate belief state)
6. Continue to pre_decide phase
```

**Step 1**: The optional `dict` bundled with the `ModeDirective` in the mode
buffer is applied first — it replaces `belief_state.inferences` wholesale.

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
Mode.mode_enter(belief_state, action_memory) -> None
```

One-time initialization for the mode. Mutates belief state directly to set
up mode-specific fields, reset counters, etc. Does not select tasks — the
first task comes from `select_task` during the decide phase on this same
tick.

**Step 6**: Pipeline resumes with pre_decide. The new mode's `select_task`
will be called during the decide phase to select the first task.

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
| `mode_enter(belief_state, action_memory) -> None` | One-time setup on activation |
| `mode_switch_cleanup(belief_state, action_memory, new_mode_directive) -> None` | Teardown when being replaced |

---

## Logging and tracing

The framework provides structured logging (JSONL format) at configurable
granularity. Output is written to a per-agent log file (path configurable at
agent construction).

### Log levels

Each level includes everything from lower levels:

| Level | Contents |
|-------|----------|
| `off` | No logging |
| `events` | Mode transitions (old→new, directive, tick). Task changes (old→new, params). Outer loop cycles (consumed tick, directive produced; staleness delta when the live tick is reachable from the outer loop). Hook failures (with rollback context). View transitions. Game phase changes (lobby reset, round changes). Watchdog activations. Outer loop restarts. |
| `decisions` | `select_task` returns each tick (task type, params, or None). Outer loop `meta_decide` input summary (belief snapshot tick, key fields). `meta_decide` output (directive + inferences dict). `mode_enter` / `mode_switch_cleanup` calls. `valid_views` mismatch no-ops. |
| `verbose` | Full perception output each tick (`FramePerception` serialized). All belief state mutations (field, old value, new value — diffed per tick). All action memory mutations. `ActCommand` output each tick (buttons, chat_text, reset_input). Cooldown state changes. `minimap_sightings` appended. Occupancy grid cells changed (viewport-confirmed transitions). |

### Metadata

All log entries (regardless of level) include: tick number, wall-clock
timestamp, active mode, current task type, and current view.

### Custom log entries

Hooks and modes may emit custom log entries via a framework-provided helper:

```
log_event(logger, category: str, data: dict, level: LogLevel | str = "events")
```

`logger` is a `Logger` instance (from `orpheus.logging`). Agents that wire
a `Logger` into their `Pipeline` constructor pass that same instance to
`log_event` from inside hooks/modes. The helper is a no-op when `logger`
is a plain callable (or anything else not a `Logger`), so hooks that want
structured custom entries opt in by passing the framework's `Logger`. The
entry is written only if the configured log level is ≥ the specified
level. This allows agent-defined tracing without coupling to the framework's
internal categories.

### Post-mortem analysis

JSONL format enables filtering by tick range, event type, mode, or task.
Each line is a self-contained JSON object with a `type` field for
categorization (e.g., `"mode_transition"`, `"task_change"`, `"act_command"`,
`"perception"`, `"belief_diff"`).

---

## Testing

The framework requires an agent implementation to exercise. A minimal **test
agent** should be implemented alongside the framework: a few simple modes
(e.g., idle, wander, approach-nearest-player) and a trivial `meta_decide`
(rule-based, no LLM). This provides scaffolding for unit testing modes/tasks
in isolation, integration testing the inner loop with mocked perception, and
end-to-end testing against a real server with a fixed seed.
