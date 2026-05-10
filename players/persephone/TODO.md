# TODO

Known issues and planned work for the persephone project.

## Perception Module

### DONE: Shape detection implemented + outline_is_black fix

- **Status**: Complete (commit `93cf58f`)
- Shape classifier matches 7x7 pixel patterns against 12 templates.
  Works for overworld (shadow-aware) and HUD contexts (outline_is_black=True).
  Game renders outlines as color 0 (black), not color 1 — the
  `outline_is_black` parameter handles this for speech bubbles, pending
  entry sprites, and whisper header occupants.

### URGENT: Test imports broken after perception move

- **Status**: Partially fixed (conftest.py updated, test files still broken).
- **Impact**: `tests/conftest.py` was migrated to `orpheus.perception` as
  part of the Stage 0 commit (`4808ccb`). `tests/test_perception_live.py`,
  `tests/test_perception_unit.py`, and `tests/test_sprites.py` still
  import via the old `from perception import ...` path and fail to
  collect under any PYTHONPATH that doesn't put `orpheus/perception` on
  the path as the bare name `perception`.
- **Fix**: Update the three remaining test files to use
  `from orpheus.perception import ...`. Also update any scripts under
  `scripts/` that still reference the old path.

### waiting_entry not testable with current capture setup

- **Status**: No fixture captured
- **Impact**: The `waiting_entry` detection logic exists and matches
  the TS parser, but we cannot generate a test fixture because the
  winner_bot fillers always initiate whispers directly (no opportunity
  for our bot to be the one requesting entry).
- **Fix**: Use less-aggressive filler bots or a two-bot choreography
  where one bot creates a whisper and the other requests entry.

### DONE: Shape classification in chatroom header sprites

- **Status**: Complete (commit `93cf58f`)
- `scan_sprite_row_with_shapes` now used with `outline_is_black=True`.
  Header position updated to x=66 (current renderer), falls back to
  x=22 for legacy fixtures. Returns `(color, shape)` pairs.

### Global chat parser: messages and hostage grid not validated

- **Status**: Partial
- **Impact**: Room name, usurp candidate, and bottom bar are now
  validated. But message parsing, hostage grid parsing (for leaders),
  and committed state detection have not been validated against live
  frames because no fixture exists with those elements active.
- **Fix**: Capture global chat frames with messages visible and with
  the leader hostage-grid active.

## Orpheus Framework

Stages 0-9 are implemented (commits `4808ccb` … `25dc995`). The follow-ups
below are deferred work flagged with `# TODO Stage N follow-up:` /
`# TODO Stage N perception gap:` markers in the source.

### Stage 2: belief update — perception gaps

The belief update pipeline integrates everything perception currently
produces, but several DESIGN.md fields rely on perception data that is
not yet extracted. Each is marked in `orpheus/belief_update.py`:

- **`round_schedule` from RoleReveal** (line ~231):
  `RoleRevealPerception` has no `schedule` field. `belief_state.round_schedule`
  stays `[]`. Fix: extend perception's role-reveal parser to read the
  schedule panel; populate `belief_state.round_schedule` in
  `_apply_role_reveal`.
- **Self color/shape/index from RoleReveal** (line ~243):
  Perception does not surface the centered own-sprite at (60, 8) on the
  role-reveal screen. `my_color`, `my_shape`, `my_index` therefore stay
  `None` until the agent is observed in a non-RoleReveal view.
  Fix: extract own sprite from the role-reveal centered position; use
  `decode_player_index` to resolve `my_index`.
- **Other-room leader colors** (line ~282):
  Only the self-leader color is set when `is_leader and my_room` are
  known. Cross-room leader detection requires perception support that
  doesn't yet exist (the overworld view only shows our own room).
- **Visible-player overworld sprites and role indicators** (line ~289):
  `OverworldPerception.speech_bubbles` only surfaces sprites that have a
  bubble. Belief update only updates `players[i].position` and
  `last_seen_in_whisper` for those sprites. Plain visible sprites (no
  bubble) and role indicators below sprites are not yet extracted by
  perception, so registry positions for non-bubble players come from
  `minimap_sightings` only (color-ambiguous).
- **Whisper `my_exchange_partner` detection** (line ~428):
  Best-effort regex on a "shared roles" system message text. Full
  detection requires identifying the two participant sprites in the
  perception output, which is not yet exposed.
- **Global-chat leader colors** (line ~516):
  Currently approximates "leader == current usurp candidate when no
  usurp is active." Real disambiguation needs more perception state.

### Whisper system messages not structured in belief state

- **Status**: Missing
- **Impact**: The Orpheus belief state tracks `pending_offers` (from "R!" /
  "C!" bottom-bar indicators) and `chat_history` (all messages including
  system messages). But there is NO structured representation of whisper
  interaction state changes derived from system messages. Agents need to
  know:
  - Whether an incoming color/role offer is active (and FROM WHOM when
    multiple occupants are present -- the bottom-bar "R!"/"C!" indicator
    does not identify the offerer)
  - Whether a color/role exchange just completed (system msg "swapped
    colors" / "shared roles")
  - Whether an offer was withdrawn (system msg "withdrew")
  - Whether a leadership offer is pending ("offered lead")

  Currently agents must parse `chat_history` entries for system message
  patterns themselves. This is error-prone and duplicates work across
  agents. The belief update should maintain structured fields like:
  - `active_color_offers: list[PlayerIndex]` -- who has a pending C.OFFER
  - `active_role_offers: list[PlayerIndex]` -- who has a pending R.OFFER
  - `last_exchange_event: ExchangeEvent | None` -- most recent
    completion/withdrawal with tick and participants

  These should be derivable from system messages (color 8 text in whisper
  message area) combined with occupant tracking.
- **Ref**: Eurydice DESIGN.md audit, finding 2.5.

### Intro panel sequence: no panel index tracking

- **Status**: Partial (roster vs role-reveal distinguished; panels 1-3
  conflated)
- **Impact**: The perception detector classifies the 4-panel intro
  sequence into two buckets: `ROSTER_REVEAL` (Panel 0) and `ROLE_REVEAL`
  (Panels 1-3). There is no panel index or sequencing state. This means:
  - Panel 2 (role summary: which roles are in the match, missing roles,
    echo substitutions) is never specifically parsed.
  - Panel 3 (round schedule: durations and hostage counts per round)
    is never specifically parsed (known gap: `round_schedule` stays
    empty).
  - An agent cannot tell whether it's on Panel 1 vs 2 vs 3 from a
    single frame, complicating active navigation of the intro.
- **Fix options**:
  1. Add sub-detection within `_role_reveal.py` based on unique visual
     signatures of each panel (Panel 1 has "YOU ARE", Panel 2 has role
     list, Panel 3 has a table with "ROUND" headers).
  2. Track panel transitions over time in belief state (counting
     forward/back transitions against the known 4-panel sequence).
  Option 1 is simpler and sufficient since each panel has distinct
  visual content.
- **Ref**: Eurydice DESIGN.md audit, finding 3.1.

### Stage 4: task `select_action` approximations

Four tasks ship with simplified `select_action` implementations that
need refinement against a live game. Each is marked
`# TODO Stage 4 follow-up:` in source. The framework contracts (frozen
dataclass shape, `valid_views`, structural equality) are correct for
all 24 tasks — only the per-tick action sequencing needs work.

- **`MenuNavigator` direction-cycling** (`orpheus/tasks/_menu_nav.py:13-16`):
  Always presses Right/Down to advance category/item, never Left/Up.
  Works as long as the menu wraps cyclically; needs validation against
  the actual menu order. Target-picker matching against perceived
  `target_colors` is also heuristic.
- **`WanderTask` exploration bias** (`orpheus/tasks/movement.py:225`):
  Picks blind random `(x, y)` waypoints inside the room. Should bias
  toward known-FREE unvisited cells once the occupancy grid has data.
- **`VoteUsurpTask` candidate selector** (`orpheus/tasks/leadership.py:54`):
  Emits a rising-edge A press only; does not yet navigate the L/R
  candidate selector to the target candidate. Assumes the desired
  candidate is already focused (or that the agent ran an
  approximation-pass first).
- **`SelectHostagesTask` cursor navigation** (`orpheus/tasks/hostage.py:25`):
  Tracks remaining indices in action memory and emits A toggles, but
  does not yet drive the U/D/L/R cursor movement onto each target color
  in the grid.

### Stage 7: outer-loop `staleness` not computed

`orpheus/outer_loop.py:124` records `outer_loop_cycle.staleness=None`
because the `OuterLoop` thread does not have a reference to the live
pipeline tick — it only sees the consumed snapshot's tick. DESIGN.md
§"Logging and tracing" lists "staleness delta" as part of the
`outer_loop_cycle` event payload. Fix: pass a `tick_provider:
Callable[[], int]` (or share the live `BeliefState` for read) into
`OuterLoop`, then compute `staleness = current_tick - consumed_tick`
when emitting the event.

### Stage 8: verbose-level log categories

Five verbose-level entry types from DESIGN.md §"Logging and tracing"
are not yet emitted (marker at `orpheus/pipeline.py:251`):

- `belief_diff` — per-tick diff of belief-state field changes.
- `cooldown_change` — when entries in `belief_state.cooldowns` mutate.
- `minimap_sighting` — when an entry is appended to
  `belief_state.minimap_sightings`.
- `grid_change` — when occupancy-grid cells transition between states.
- `action_memory_mutation` — fine-grained action-memory field changes.

The two big ones (`perception` full dump and `act_command` per tick)
are wired. The remaining five are useful for offline analysis but
require either a periodic-diff implementation or instrumentation hooks
inside the relevant mutation sites.

### `BeliefState.reset()` does not clear ad-hoc attributes

`orpheus/belief_state.py:reset()` iterates `dataclasses.fields(self)` to
restore declared fields to defaults. Attributes set via
`belief_state.foo = ...` (the DESIGN.md "flexible space" pattern) are
NOT cleared by `reset()`. This is a subtle behavior gap relative to
DESIGN.md's "clear the entire belief state back to initial values"
language for the lobby-reset path. Fix: either drop unknown attributes
in `reset()` (`for name in list(self.__dict__): if name not in field_names: delattr(self, name)`)
or document that ad-hoc fields persist across resets. Modes that need
auto-clearing should use `belief_state.extra` (which IS reset because
it's a declared field).

### LOW PRIO: Mutable action mask in post_act hooks

- **Status**: Future direction
- **Impact**: Currently action_mask is read-only in all hooks. Allowing
  post_act hooks to modify the action mask would enable safety overrides
  or emergency interrupts at the hook level.
- **Decision**: Blanket read-only for now. Revisit if a concrete use case
  emerges.

### LOW PRIO: Hook dependency ordering

- **Status**: Future direction
- **Impact**: Hooks at the same point currently fire in FIFO registration
  order. If hooks develop complex interdependencies, a dependency-aware
  ordering system (e.g., "run after hook X") could be added to the
  registration method.
- **Decision**: FIFO is sufficient for now. Revisit if hook count grows
  large or ordering bugs emerge.

## Eurydice Agent — Whisper Interaction

### Agents can't join each other's whispers (fog-of-war visibility)

- **Status**: Partially fixed — all mechanical pieces work, spatial
  coordination doesn't
- **Impact**: Agents create solo whispers and wait (up to 15s). Other
  agents try to join but can only see speech bubbles within fog-of-war
  range (~30-40px). By the time an agent walks close enough to see a
  bubble, the whisper creator may have already timed out.
- **What works**: Whisper creation (A-press), view detection (WHISP at
  42,2), speech bubble detection (100% shape accuracy), entry request
  (B-press → waiting_entry), pending entry detection (WANTS IN at y=111),
  entry grant (GrantEntryTask fixed button sequence). Full chain proven
  with recorded frames.
- **What doesn't**: Spatial coordination. Agents approach via minimap
  (which doesn't show whisper status), so they don't prioritize whisper
  players until within visual range.
- **Fix options**:
  1. Have agents approach to ~30px before deciding create vs join (get
     within bubble-visible range first, then check for bubbles)
  2. Use global chat to announce "I have a whisper" with a position
  3. Designate a meeting point (e.g. room center) where agents cluster
     before initiating whispers
  4. Increase whisper wait timeout further (30+ seconds)
  5. Track "last known whisper position" from minimap + timing heuristic
     (player stopped moving → likely in whisper)

### Remove `_find_player_by_color` fallback

- **Status**: Can be cleaned up
- **Impact**: The color-only fallback in `belief_update.py` is no longer
  needed now that `outline_is_black=True` gives 100% shape detection on
  HUD sprites. The fallback still handles edge cases (players 8-9 with
  shared colors), but with proper shape detection those should resolve
  correctly.
- **Fix**: Remove `_find_player_by_color` and the fallback paths in
  `_apply_overworld_speech_bubbles` and the pending_entry section.
  Verify no regression in shape detection coverage first.

### Visible-player overworld sprites (non-bubble) not tracked

- **Status**: Perception gap
- **Impact**: Only players WITH speech bubbles get their positions
  updated via overworld sprite detection. Plain visible sprites (no
  bubble) are only tracked via minimap dots (color-only, low-resolution
  position). This means we can't detect nearby players' shapes from
  their overworld sprites, only from minimap color.
- **Fix**: Add overworld sprite scanning that finds all visible player
  sprites (not just those with bubbles). This would give precise
  positions and full (color, shape) identification for all visible
  players, enabling much better whisper-join targeting.
