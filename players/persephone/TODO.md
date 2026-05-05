# TODO

Known issues and planned work for the persephone project.

## Perception Module

### Overworld HUD parsing incomplete

- **Status**: Known bug
- **Impact**: `overworld.round` and `overworld.timer_secs` return `None`
  during the Playing phase, even though the HUD text "R1 0:15" is
  correctly read by the OCR. The overworld parser's HUD extraction
  logic likely has a parsing bug (similar in nature to the role_reveal
  y-offset issue that was fixed).
- **Evidence**: Live test fixture `playing_round1` shows `round=None,
  timer_secs=None` while the OCR reads "R1 0:15" correctly.
- **Fix**: Debug `_overworld.py` HUD parsing against live frames.

### Leader summit misclassified as hostage_select

- **Status**: Known limitation
- **Impact**: The "LEADERS MEET {n}S" phase (where leaders negotiate)
  is detected as `HOSTAGE_SELECT`. This is technically a distinct game
  phase with its own semantics (non-leaders cannot act, the overworld
  is rendered with fog, shout strip is active).
- **Fix**: Add a `LEADER_SUMMIT` view type to the View enum with its
  own detection rule (`hud_norm_1.startswith("LEADERS")`). Currently
  mapped to hostage_select as a pragmatic choice since the overworld
  parser handles both.

### waiting_entry not testable with current capture setup

- **Status**: No fixture captured
- **Impact**: The `waiting_entry` detection logic exists and matches
  the TS parser, but we cannot generate a test fixture because the
  winner_bot fillers always initiate whispers directly (no opportunity
  for our bot to be the one requesting entry).
- **Fix**: Use less-aggressive filler bots or a two-bot choreography
  where one bot creates a whisper and the other requests entry.

### Global chat parser not fully validated

- **Status**: Partial
- **Impact**: The global chat view is detected correctly ("UNDERWORLD
  SHOUT" header), and room_name + usurp_candidate are extracted. But
  message parsing, hostage grid parsing (for leaders), and committed
  state detection have not been validated against live frames.
- **Fix**: Capture more global chat frames with messages and leader
  hostage-grid active.
