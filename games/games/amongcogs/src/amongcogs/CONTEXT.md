# Among Us Context Handoff

Last updated: 2026-03-06 (America/Los_Angeles)

This document is a practical handoff for future work on `among_us`.
It is intentionally focused on what is true right now, what is still risky,
and what to run first when resuming development.

## Current State

- Game ID and entry points are wired:
  - Recipe ID: `among_us`
  - Legacy CLI alias: `amongus`
  - Default policy: `metta://policy/amongcogs_agent`
- Game mechanics are now split into a typed variant tree with default `full` composition, matching the
  `cogames` variant-registry pattern from `sasmith/variant-framework`.
- Base mission wiring is now separated from the mechanic bundle:
  - `metta/games/among_us/missions/mission.py` owns the base env and default variant application.
  - `metta/games/among_us/game/__init__.py` is the local mechanic bundle/export surface.
  - `metta/games/among_us/game/game.py` is the thin registration layer for `metta play among_us`.
- Core mechanics are live:
  - Crew/impostor roles
  - Tasks, sabotages, repairs
  - Kills, corpse reports, emergency meetings
  - Voting + ejection path
  - Win condition events + winner declaration
- Headless audit loop exists and is used as a ship gate.
- Assets are namespaced under Among Us paths (no cross-game asset mixing intended).
- `play` recipe now sets autoplay on by default to avoid idle/hanging starts.

Variant nodes currently implemented:

- `roles`
- `tasks`
- `station_events`
- `combat`
- `meetings`
- `win_conditions`
- `metrics`
- `full` (depends on all above)

## Recent Validation Snapshot

From this branch and latest local checks:

- `pytest -q tests/tools/test_among_us_recipe.py` passed.
- `pytest -q tests/metta/games/among_us/test_variants.py` passed.
- `metta play among_us -- max_steps=20 render=none` completed.
- `metta play among_us -- max_steps=5 render=gui` completed.
- `among_us.play` now defaults to `autostart=True` (regression tested).

Historical strict-audit snapshot (see README for full values):

- `ship_strict` gate passed.
- Determinism replay check passed (`repeats=2`, `episodes=4`).
- Release suite passed (`pass_rate=1.0`).

## Tight Loop Commands (No GUI Required)

Use these commands first before changing game logic:

1. Single fast play smoke:
   - `metta play among_us -- render=none max_steps=120`
2. Headless mechanic audit:
   - `python -m amongcogs.headless --episodes 20 --seed 0 --num-agents 12 --max-steps 220`
3. Strict gate audit:
   - `./tools/run.py amongcogs.audit episodes=120 seed=0 num_agents=12 max_steps=220 gate_profile=ship_strict determinism_repeats=2 determinism_episodes=4 output_json=train_dir/among_us_audit.json print_json=false`
4. Recipe-level tests:
   - `pytest -q tests/tools/test_among_us_recipe.py tests/metta/games/among_us`
5. Variant tree tests:
   - `pytest -q tests/metta/games/among_us/test_variants.py`

GUI sanity (short run):

- `metta play among_us -- render=gui max_steps=120`

## High-Impact Next Slices (Priority Order)

1. Balance and pacing pass:
   - Reduce crew-heavy winner skew while preserving mechanic coverage.
   - Re-run strict audit + release suite after each tuning slice.
2. Scripted policy quality:
   - Improve meeting/vote targeting heuristics and anti-stuck movement.
   - Verify metrics improve in headless audits (not just visual feel).
3. Map flow polish:
   - Keep stations spatially distributed across recognizably Skeld-like rooms/corridors.
   - Re-check travel distance and per-station interaction rates.
4. Asset and render robustness:
   - Keep all required sprites present under Among Us namespace.
   - If GUI shows unknown sprites, regenerate atlas and verify asset tests.
   - Prefer original/generated art rather than importing official game art directly.
5. CI hardening:
   - Keep play/train/audit smoke jobs green on this branch.
   - Add/adjust tests when fixing regressions so behavior stays locked.

## Known Risks / Watch Items

- Balance can drift quickly when map placement or scripted priorities change.
- Sabotage coverage is more seed-sensitive than tasks and reports.
- Asset changes can appear correct in files but fail at runtime until atlas is regenerated.
- Variant subset runs can alter winner-rate balance substantially; always compare against the strict full baseline before shipping.
- `vet` tool currently crashes in this workspace when an untracked `tribal-village`
  symlink exists (known local tooling issue, not specific to Among Us).

## Files You Will Touch Most

- Mission/base env: `metta/games/among_us/missions/mission.py`
- Map layout: `metta/games/among_us/map_scene.py`
- Scripted agent: `metta/games/among_us/agent/amongcogs_agent/policy.py`
- Mechanic bundle: `metta/games/among_us/game/`
- Registration hook: `metta/games/among_us/game/game.py`
- Shared mechanic constants: `metta/games/among_us/constants.py`
- Headless audit and gating: `metta/games/among_us/headless.py`
- Recipe wiring: `recipes/game/among_us.py`
- Game tests: `tests/metta/games/among_us/`
- Recipe tests: `tests/tools/test_among_us_recipe.py`

## Resume Checklist

When resuming work, do this in order:

1. Run non-GUI play smoke and headless audit.
2. Make one logical change slice only.
3. Re-run targeted tests and strict audit.
4. Run GUI short smoke for render sanity.
5. Regenerate atlas if any asset changed.
6. Update this file and README snapshot if behavior/metrics changed.
