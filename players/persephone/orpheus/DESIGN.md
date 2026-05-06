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

### Perception phase

Parses the raw pixel frame into structured symbolic output (the `View`).

### Belief update phase

Integrates the perception output into the persistent belief state.

### Decide phase

Calls the active mode's `select_task` method. This is the only phase where
mode-specific logic runs (aside from hooks).

### Act phase

Translates the current task (set by `select_task`) into a per-tick command
sent to the server. A command may contain button input, a chat packet, or
both. Uses the belief state and an `ActionMemory` object to execute multi-tick
tasks.

---

## Mode interface

All modes are stored in a **mode registry**. The agent is in exactly one mode
at any time.

A mode is a class with three required methods:

| Method | When called | Purpose |
|--------|-------------|---------|
| `select_task(belief_state, action_memory) -> BeliefStateDelta` | Every tick (decide phase) | Task selection and belief state updates |
| `mode_enter(belief_state, action_memory) -> BeliefStateDelta` | Once, on activation | One-time setup when mode becomes active |
| `mode_switch_cleanup(belief_state, action_memory, new_mode_directive) -> BeliefStateDelta` | Once, on deactivation | Teardown when being replaced by another mode |

### select_task

Called during the decide phase every tick. It receives the current belief
state (fixed structure, same for all modes) and the current action memory
(read-only — provides visibility into what commands the active task has been
sending). It returns a delta describing updates to the belief state.
Its responsibilities:

1. Set the `current_task` field (e.g. `"move-to"`, `"chat"`, `"idle"`).
2. Set task parameters in the belief state (e.g. `target = (X, Y)`).
3. Optionally update other belief state fields.

`select_task` does **not** call actions directly.

### mode_enter / mode_switch_cleanup

See the [mode switching](#mode-switching) section for the full lifecycle
and calling semantics.

Modes may also attach logic via the pre/post hooks on any phase.

---

## Tasks

A `Task` is an object that encapsulates how to execute a particular kind of
work (movement, chatting, etc.). Tasks are the unit of act-phase logic.

### Interface

```
Task.select_action(belief_state, action_memory) -> (ActionMemoryDelta, ActCommand)
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
- Reads action memory; returns a delta describing updates to it.
- Returns an `ActCommand`:
  - `buttons` is the low-level input mask sent as a `PACKET_INPUT`.
  - `chat_text`, when present, is sent as a `PACKET_CHAT`.
  - `reset_input` sends the protocol reset mask (`0xFF`) instead of `buttons`.

Chat is a first-class packet type, not a simulated button action. Sending chat
does not require pressing A, B, Select, or Enter before or after the chat
packet. The server routes chat by player state: if the player is inside a
chatroom, the packet becomes chatroom text; otherwise it becomes global room
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

The decide phase (via `select_task`) sets the current task. The framework
compares it against the previous tick's task by identity — `(task_type,
params)` equality. Two cases:

- **Task changed** (different type or different parameters): ActionMemory is
  cleared. The new task starts with empty action memory.
- **Task reaffirmed** (same type, same parameters): ActionMemory is
  preserved. The task continues execution where it left off.

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
| `create_chatroom` | — | Press A in current position (mode ensures open space) | View → chatroom |
| `request_entry` | `player_index` | A* path to target player, A-press when close | View → chatroom (or WAITING state) |
| `exit_chatroom` | — | Menu navigate: EXIT category → EXIT item → confirm | View → overworld |
| `grant_entry` | — | Menu navigate: LEADER category → GRANT item → confirm | System message confirms |

#### Information exchange (require chatroom view)

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
| `pass_leadership` | — | Menu navigate: LEADER → PASS → confirm (requires chatroom, is leader) | System msg "offered lead" |
| `take_leadership` | — | Menu navigate: LEADER → TAKE → confirm (requires chatroom, offer pending) | `is_leader` becomes true |
| `vote_usurp` | `candidate` | Open global chat if needed; navigate usurp selector to candidate; A-press to vote | System msg "voted for..." |

#### Hostage selection (leader only, HostageSelect phase)

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `select_hostages` | `player_indices[]` | In global chat: navigate hostage grid, toggle each target, commit | View transitions / timer expires |

#### Communication

| Task | Params | Operation | Completion signal |
|------|--------|-----------|-------------------|
| `send_message` | `text, channel` | Send a `PACKET_CHAT` with `buttons=0`; no button press is required. `channel` is the intended route (`chatroom`, `global`, or `auto`) and is checked against belief state because the server routes by whether the player is inside a chatroom. Respects chat cooldown internally | Message appears in chat history |

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

- All chatroom menu tasks (information exchange, leadership, grant) share
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
speech bubbles, chatroom occupants, info screen, exchange screen, and global
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
  - `alive` — alive/dead status

  Minimap dots provide color-only sightings, which narrow to up to 3
  candidate indices (those sharing `color mod 8`). Overworld sprite
  observations provide full (color, shape) identification via
  `detect_sprite_shape()`, giving unambiguous player index resolution.

**Game state:**
- `view` — current phase/view enum
- `round` — round number
- `timer_secs` — countdown if visible

**Action state:**
- `cooldowns` — map of action type → tick when next available. Updated by
  the framework when actions are sent. Tasks consult this to respect the
  48-tick rate limit (chat, menu actions).

**Chatroom state:**
- `in_chatroom` — whether self is currently in a chatroom (derivable from
  `view`, surfaced explicitly since many tasks gate on this)
- `chatroom_occupants` — list of player indices in current chatroom (empty
  if not in chatroom)
- `pending_offers` — active exchange offers visible to us: `{role: bool,
  color: bool}` from the "R!" / "C!" bottom-bar indicators
- `pending_entry` — player index requesting entry to our chatroom (from
  "[sprite] WANTS IN" perception), or None
- `menu_state` — current chatroom menu state: closed, (category, item), or
  target picker with candidate list. Parsed from perception bottom bar.

**Hostage state (during HostageSelect):**
- `hostage_selections` — current selections and cursor state if we are
  leader. Parsed from `GlobalChatPerception.hostage_grid`.

**Social / knowledge:**
- `chat_history` — recent messages observed (chatroom + global + shouts),
  with sender index, tick, channel (chatroom/global/shout), and for
  chatroom messages: the list of occupant indices present when the message
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
| `info_screen` | Seen on info screen (reflects above) | No |
| `chat_claim` | Stated by a player in chat | No (unverified) |
| `inferred` | LLM/mode reasoning | No (speculative) |

The `mutual_exchange` source tracks the game's `sharedWith` mechanic — the
only action that satisfies the win condition. Distinguishing mechanical
revelation from chat claims is critical because players may lie in chat but
mechanically revealed information is always truthful.

**Leadership/hostage:**
- `is_leader` — whether self holds the crown
- `leader_colors` — known leader colors per room

**Task (framework-managed):**
- `current_task` — active task identifier + parameters

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

## Hook API

Hooks allow agents to inject custom logic at phase boundaries in the inner
loop pipeline. Hooks are registered via a framework method and called
serially when the hook event fires.

### Hook points and signatures

Each hook point has a typed signature reflecting exactly what data is
available at that moment in the pipeline.

| Hook point | Arguments | May mutate |
|---|---|---|
| `pre_perception` | `(frame, belief_state)` | frame, belief_state (via delta) |
| `post_perception` | `(frame, perception, belief_state)` | belief_state (via delta) |
| `pre_belief_update` | `(perception, belief_state)` | belief_state (via delta) |
| `post_belief_update` | `(belief_state)` | belief_state (via delta) |
| `pre_decide` | `(belief_state, action_memory)` | belief_state (via delta) |
| `post_decide` | `(belief_state, action_memory)` | belief_state (via delta) |
| `pre_act` | `(belief_state, action_memory)` | belief_state (via delta) |
| `post_act` | `(belief_state, action_memory, action_mask)` | belief_state (via delta) |

- `frame`: raw pixel array (128x128 uint8). Mutable only in `pre_perception`.
- `perception`: the `FramePerception` output. Read-only.
- `belief_state`: current belief state. Read-only within the hook body;
  mutations are expressed via the returned `BeliefStateDelta`.
- `action_memory`: current action memory. Read-only.
- `action_mask`: the action output for this tick. Read-only.

### Return value

All hooks return a `BeliefStateDelta` (or `None` for no changes). The
framework applies the delta to the belief state after the hook returns and
before the next hook in the chain fires. This means sequential hooks at the
same hook point can see and build on each other's changes.

`pre_perception` additionally returns the (possibly modified) frame.

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
- Contents: `(belief_state, action_memory)` snapshot.
- Written by the inner loop every tick, after post_belief_update hooks fire.
  Overwrites any prior unconsumed value.
- Read by the outer loop at the start of each iteration. The outer loop
  **blocks** until the buffer is non-empty, then consumes it. This naturally
  throttles the outer loop to at most once per inner-loop tick.

**Mode buffer** (outer → inner):
- Contents: `(ModeDirective, BeliefStateDelta | None)`.
- Written by the outer loop after `meta_decide` returns.
- Read by the inner loop each tick, between post_belief_update and pre_decide.
  If the buffer is non-empty, the inner loop consumes it and applies the
  mode directive and belief state delta. If empty, the inner loop continues
  with the current mode unchanged.

### meta_decide

```
meta_decide(belief_state, action_memory) -> (ModeDirective, BeliefStateDelta | None)
```

Called once per outer-loop iteration with the consumed belief state and
action memory. Returns:

- `ModeDirective`: a complete mode specification — mode type + parameters.
  May be the same as the current mode (reaffirmation) or a new mode
  (transition).
- `BeliefStateDelta | None`: optional direct belief state mutations (e.g.,
  LLM-derived inferences like "player 3 is likely Hades").

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
a **default initial mode**. The framework provides a built-in `explore` mode
(uses `wander` task; approaches and engages other players opportunistically)
as the default. Agents may override this by specifying a different initial
mode at construction.

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
1. Apply BeliefStateDelta from mode buffer entry
2. Run mode-switch callbacks (return BeliefStateDelta + ModeDirectiveDelta each)
3. Run OLD mode's mode_switch_cleanup (returns BeliefStateDelta)
4. Activate new mode
5. Run NEW mode's mode_enter (returns BeliefStateDelta)
6. Continue to pre_decide phase
```

**Step 1**: The optional `BeliefStateDelta` bundled with the `ModeDirective`
in the mode buffer is applied first.

**Step 2**: Registered mode-switch callbacks fire in order (agent-level
first, then mode-level for the old mode, FIFO within each group). Each
callback receives:

```
mode_switch_callback(belief_state, action_memory, mode_directive)
    -> (BeliefStateDelta, ModeDirectiveDelta)
```

- `belief_state`: read-only; mutations via returned `BeliefStateDelta`.
- `action_memory`: read-only.
- `mode_directive`: read-only; modifications via returned `ModeDirectiveDelta`.

The framework applies both deltas after each callback returns, before the
next callback fires. Later callbacks see accumulated changes from earlier
ones.

**Step 3**: The old (departing) mode's cleanup method runs:

```
Mode.mode_switch_cleanup(belief_state, action_memory, new_mode_directive)
    -> BeliefStateDelta
```

Receives the final mode directive (as potentially modified by callbacks).
Returns a belief state delta only — cannot modify the directive. Used for
teardown, persisting mode-specific state, etc. May be a no-op.

**Step 4**: The framework activates the new mode (as specified by the final
`ModeDirective` after all callback modifications).

**Step 5**: The new mode's entry method runs:

```
Mode.mode_enter(belief_state, action_memory) -> BeliefStateDelta
```

One-time initialization for the mode. Sets up mode-specific belief state
fields, resets counters, etc. May be a no-op.

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
| `select_task(belief_state, action_memory) -> BeliefStateDelta` | Per-tick task selection (decide phase) |
| `mode_enter(belief_state, action_memory) -> BeliefStateDelta` | One-time setup on activation |
| `mode_switch_cleanup(belief_state, action_memory, new_mode_directive) -> BeliefStateDelta` | Teardown when being replaced |

---

## Open design questions

(None remaining. All major framework components are specified.)
