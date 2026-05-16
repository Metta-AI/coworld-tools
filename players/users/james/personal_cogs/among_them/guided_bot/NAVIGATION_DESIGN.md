# Navigation Design

This design note has been reset to remove obsolete local tooling references.

The current runtime boundary is Coworld-only. The old waypoint editor, navigation
baker script, local live test, and local match trace workflow have been removed.

## Current State

- Navigation data remains part of the guided_bot implementation.
- Runtime validation should happen through Coworld execution and Coworld logs.
- Any future navigation-data regeneration workflow must be added through the
  repo-local UV/Coworld command surface, not as an ad hoc local script.

## Future Work

1. Decide whether navigation assets should remain checked in or be regenerated
   by a Coworld-compatible build step.
2. If regeneration is needed, design it as part of the UV project rather than
   reviving deleted helper scripts.
3. Add Coworld-log checks for stuck movement, localization loss, and movement
   mask distribution once the new match command exists.
