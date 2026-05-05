# TODO

Known issues and planned work for the persephone project.

## Perception Module

### waiting_entry not testable with current capture setup

- **Status**: No fixture captured
- **Impact**: The `waiting_entry` detection logic exists and matches
  the TS parser, but we cannot generate a test fixture because the
  winner_bot fillers always initiate whispers directly (no opportunity
  for our bot to be the one requesting entry).
- **Fix**: Use less-aggressive filler bots or a two-bot choreography
  where one bot creates a whisper and the other requests entry.

### Global chat parser: messages and hostage grid not validated

- **Status**: Partial
- **Impact**: Room name, usurp candidate, and bottom bar are now
  validated. But message parsing, hostage grid parsing (for leaders),
  and committed state detection have not been validated against live
  frames because no fixture exists with those elements active.
- **Fix**: Capture global chat frames with messages visible and with
  the leader hostage-grid active.
