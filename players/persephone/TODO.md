# TODO

Known issues and planned work for the persephone project.

## Perception Module

### Role reveal text extraction fails for centered text
- **Status**: Known bug
- **Impact**: `role`, `room`, `player_count`, `room_size` return `None`
  from the role reveal screen. Team detection works (via border color).
- **Root cause**: `_scan_centered()` in `perception/_role_reveal.py`
  scans x in steps of 2 and/or the hardcoded y offsets (18, 46, 56)
  don't match the actual render layout for all configs.
- **Fix**: Scan x in steps of 1, and verify y offsets against live
  frames from multiple configs. May also need to widen the x scan
  range (currently 0 to SCREEN_WIDTH-10).
- **Evidence**: Live test output:
  ```
  Frame 120: view changed to role_reveal | role=None, team=Shades, room=None, players=None, size=None
  ```
- **Workaround**: Agents can read their role from the HUD during the
  Playing phase (role name appears in the top bar in team color), which
  the overworld parser handles separately.
