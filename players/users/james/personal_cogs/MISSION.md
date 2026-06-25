# MISSION.md

This checkout is now focused on a Coworld-only Among Them workflow.

## Goal

Build, run, inspect, and submit Among Them policies through Coworld using the
public PyPI Coworld interface from a repo-local UV project.

## Non-Goals

- No local Among Them server scripts.
- No legacy bundle upload path.
- No hosted-play shim.
- No direct Coworld CLI usage from a local Metta checkout for this project.
- No new ad hoc run scripts outside the Coworld/UV command surface.

## Current Priority

1. Keep guided_bot runnable through Coworld only.
2. Define the Coworld match command that replaces the deleted local match
   scripts.
3. Validate meeting LLM control with gameplay directives disabled.
4. Use Coworld episode logs and stderr JSONL traces as the runtime source of
   truth.

## Documentation Source Of Truth

For Among Them:

- `among_them/README.md`
- `among_them/guided_bot/README.md`
- `among_them/guided_bot/coworld/README.md`
- `among_them/guided_bot/coworld/INSPECTING_RESULTS.md`
- `among_them/guided_bot/coworld/DC_DEBUGGING_PLAYBOOK.md`

Update these when the Coworld command surface changes.
