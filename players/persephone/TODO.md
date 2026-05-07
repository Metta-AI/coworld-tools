# TODO

Known issues and planned work for the persephone project.

## Perception Module

### URGENT: Shape detection not implemented

- **Status**: Missing
- **Impact**: The `PlayerShape` enum exists in `types.py` and 7x7 sprite
  geometry is defined, but `_sprites.py` only reads the center pixel color.
  There is no shape classifier. Without shape detection, we cannot resolve
  (color, shape) → player index from overworld observations. This blocks
  index-based player identification in the Orpheus belief state.
- **Fix**: Implement a shape classifier that matches 7x7 sprite pixel
  patterns against the 12 known templates. The templates are defined in
  `~/coding/bitworld/persephones_escape/common/sprites.ts` (or can be
  derived from the `PLAYER_SHAPES` constant). Minimap dots are single-pixel
  and inherently color-only — shape detection applies to overworld and any
  other context where full 7x7 sprites are rendered.

### URGENT: Test imports broken after perception move

- **Status**: Broken
- **Impact**: All test files (`tests/test_perception_live.py`,
  `tests/test_perception_unit.py`, `tests/test_sprites.py`,
  `tests/conftest.py`) import from `perception` directly. The module
  moved to `orpheus/perception/`. Tests will fail on import.
- **Fix**: Update all test imports from `from perception import ...` to
  `from orpheus.perception import ...`. May also need to update
  `PYTHONPATH` in any scripts or CI that run tests.

### waiting_entry not testable with current capture setup

- **Status**: No fixture captured
- **Impact**: The `waiting_entry` detection logic exists and matches
  the TS parser, but we cannot generate a test fixture because the
  winner_bot fillers always initiate whispers directly (no opportunity
  for our bot to be the one requesting entry).
- **Fix**: Use less-aggressive filler bots or a two-bot choreography
  where one bot creates a whisper and the other requests entry.

### Shape classification in chatroom header sprites

- **Status**: Not implemented
- **Impact**: The chatroom header renders occupant sprites at known
  positions (x=22, stride 9, y=1-7). Currently `_chatroom.py` only
  extracts the dominant color per slot. Without shape classification,
  `chatroom_occupants` in the Orpheus belief state cannot be resolved
  to unambiguous player indices (up to 3 candidates share a color).
- **Fix**: Run `detect_sprite_shape()` on chatroom header sprites in
  addition to color extraction. The sprites are standard 7x7 templates
  at known positions — the same classifier used in overworld detection
  applies. Return `(color, shape)` pairs from `ChatroomPerception`,
  allowing the belief update to resolve exact player indices. When shape
  detection fails (full shadow collision), report color-only candidates.
- **Ref**: Orpheus DESIGN.md open question #8 resolution.

### Global chat parser: messages and hostage grid not validated

- **Status**: Partial
- **Impact**: Room name, usurp candidate, and bottom bar are now
  validated. But message parsing, hostage grid parsing (for leaders),
  and committed state detection have not been validated against live
  frames because no fixture exists with those elements active.
- **Fix**: Capture global chat frames with messages visible and with
  the leader hostage-grid active.

## Orpheus Framework

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
