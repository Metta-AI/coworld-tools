# Among Us (MettaGrid)

This is an Among Us style social deduction game implemented on top of MettaGrid.

The short version:
- Crew tries to finish and repair stations.
- Impostors try to sabotage stations and eliminate crew.
- Meetings let agents report bodies, call emergency meetings, and vote.
- The game can be run in the native Mettascope GUI or fully headless for testing and CI.

## Quick Start

Play in the default GUI (native Mettascope):

```bash
metta play among_us
```

Play in GUI with explicit overrides:

```bash
metta play among_us -- max_steps=200 seed=0
```

Play in the alternate Vibescope renderer:

```bash
metta play among_us -- render=vibescope max_steps=200
```

Play without GUI (fast terminal run):

```bash
metta play among_us -- render=none max_steps=200
```

Run a strict ship-readiness audit (headless):

```bash
./tools/run.py amongcogs.audit \
  episodes=120 \
  seed=0 \
  num_agents=12 \
  max_steps=220 \
  gate_profile=ship_strict \
  determinism_repeats=2 \
  determinism_episodes=4 \
  output_json=train_dir/among_us_audit.json \
  print_json=false
```

## What "play" Means in This Repo

Today, this game is run by scripted agents by default.

That means:
- You are launching and observing a full simulation.
- You are not manually controlling one character in real time.
- "Play" here means "run a game episode with rendering on or off."

## Game Identity and Entry Points

Game IDs used in this repo:
- Recipe/game id: `among_us`
- Legacy CLI alias: `amongus`

Main commands:
- `metta play among_us ...`
- `./tools/run.py among_us.play ...`
- `./tools/run.py among_us.train ...`
- `./tools/run.py amongcogs.audit ...`
- `python -m amongcogs.headless ...`

## Variant Tree (Composable Mechanics)

Among Us is now structured as a typed variant tree, following the `cogames` variant-registry pattern used on
`sasmith/variant-framework`.

Code layout:
- Base mission/env wiring lives in `metta/games/among_us/missions/mission.py`.
- Mechanic variants are bundled from `metta/games/among_us/game/__init__.py`.
- `metta/games/among_us/game/game.py` is the thin registration hook used by the shared CLI/game registry.

Default behavior:
- If you run `among_us` with no variants, the game automatically applies `full`.

Variant nodes:
- `roles`: role stations + fallback role assignment
- `tasks`: task/sabotage/repair station interactions
- `station_events`: periodic refill/failure/recovery
- `combat`: impostor kill cooldown + proximity kill
- `meetings`: corpse reports, emergency calls, vote intents, vote resolution
- `win_conditions`: winner checks + episode end on winner
- `metrics`: station/social stat writers for audits
- `full`: depends on all of the above

Examples:
- Full default (same behavior as before):
  - `metta play among_us -- render=none max_steps=200`
- Explicit full:
  - `metta play among_us -- variants=full render=none max_steps=200`
- Slice run (meetings pulls role/combat deps automatically):
  - `metta play among_us -- variants=meetings render=none max_steps=200`
- Recipe form:
  - `./tools/run.py among_us.play variants=roles,meetings render=none max_steps=200`

## Core Rules (Plain English)

### Roles

There are two roles:
- Crew:
  - Complete station tasks.
  - Repair sabotaged stations.
  - Report bodies.
  - Vote in meetings.
- Impostor:
  - Sabotage online stations.
  - Kill nearby living crew (with cooldown).
  - Participate in meetings.

### Stations

Role stations:
- `crew_station`
- `impostor_station`

Task stations:
- `wiring_station`
- `reactor_station`
- `navigation_station`
- `oxygen_station`

### Map

The map is a custom ship layout (`AmongUsShipScene`) inspired by Skeld-style room/corridor flow.

Current room graph:
- Cafeteria
- Weapons
- O2
- Navigation
- Admin
- Storage
- Electrical
- Lower Engine
- Reactor
- Security
- Upper Engine
- MedBay
- Communications
- Shields

This is intentionally close to Skeld rather than a generic arena. The next fidelity passes should focus on vent occupancy and hiding state,
door control, and slightly tighter room proportions before adding more mechanics.

### Event Loop

In addition to agent actions, the game runs periodic events:
- Task refill.
- Station failures (new sabotaged outages).
- Station recovery.
- Impostor kill cooldown ticking.
- Nearby kill checks.
- Meeting/report/voting resolution events.
- Fallback role assignment events so all agents receive a role early.

### Meetings and Voting

Meeting flow in this implementation:
- A crew agent can report a nearby corpse.
- Any alive agent with a meeting token can call an emergency meeting.
- Alive participants are teleported into the meeting ring by engine events so discussion is actually shared.
- During meetings, agents can express vote intents.
- Meeting resolves after a timer.

Vote resolution uses named ballots:
- `vote_target_N` marks a ballot against Agent N.
- The named agent with the highest untied total is ejected if they beat skip.
- Generic accuse state does not eject anyone; voters need a named target.
- Tied target votes, skip-majority votes, and no-vote meetings resolve without ejection.

### Win Conditions

Crew wins if either:
- Crew task progress reaches the task goal.
- All impostors are no longer alive.

Impostor wins if either:
- Impostor sabotage count reaches sabotage goal.
- Crew alive count is reduced low enough (current elimination rule path).

Important scaling detail:
- Crew task win target scales with lobby size:
  - `max(4, floor(0.75 * num_agents))`

## Social Intents (Developer Names)

Intent actions are implemented as vibe changes:
- `change_vibe_pin`: report corpse
- `change_vibe_compass`: call emergency meeting
- `change_vibe_vote_agent_N`: vote for Agent N
- `change_vibe_asterisk`: vote skip

## Scripted Agent Behavior

Default policy:
- URI: `metta://policy/amongcogs_agent`
- Package: `amongcogs.agent.amongcogs_agent`

Behavior summary:
- Agents first acquire roles (crew/impostor split is deterministic in policy setup).
- Dead agents noop.
- During meetings, agents vote then wait.
- Crew prioritizes:
  - report nearby corpse
  - repair sabotaged stations
  - complete online task stations
  - explore when needed
- Impostors prioritize:
  - kill opportunities when cooldown allows
  - sabotage online task stations
  - movement/exploration fallback when targets are not nearby

## How To Run and Inspect Mechanics Without GUI

Single headless episode with periodic logs:

```bash
python -m amongcogs.headless --num-agents 12 --max-steps 300 --log-every 25 --verbose
```

This prints a JSON summary with:
- totals (`tasks_completed`, `sabotages`, `repairs`, `kills`, `reports`, `ejections`)
- first-hit timing metrics (`first_task`, `first_kill`, `first_report`, etc.)
- station online/sabotaged timeline snapshots
- winner stats
- performance stats (`sps`, policy time, sim step time)

Run multi-episode reliability audit:

```bash
python -m amongcogs.headless --episodes 20 --seed 0 --num-agents 12 --max-steps 220
```

Enforce gate thresholds and fail on gate failure:

```bash
python -m amongcogs.headless \
  --episodes 200 \
  --seed 0 \
  --num-agents 12 \
  --max-steps 220 \
  --no-end-on-winner \
  --enforce-gate \
  --gate-profile ship_strict \
  --determinism-repeats 2 \
  --determinism-episodes 4 \
  --output-json ./train_dir/among_us_audit_gate.json
```

## Train and Eval Loop

Quick train smoke:

```bash
./tools/run.py among_us.train max_steps=120 trainer.total_timesteps=256 system.device=cpu system.local_only=true evaluator.skip_git_check=true
```

Play smoke:

```bash
./tools/run.py among_us.play render=none max_steps=120 seed=0
```

Strict audit smoke:

```bash
./tools/run.py amongcogs.audit episodes=120 seed=0 num_agents=12 max_steps=220 gate_profile=ship_strict determinism_repeats=2 determinism_episodes=4 output_json=train_dir/among_us_audit.json print_json=false
```

Release suite check:

```bash
./tools/run.py amongcogs.audit run_release_suite=true release_suite=default release_min_pass_rate=1.0 include_scenario_audits=true output_json=train_dir/among_us_release_suite.json print_json=false
```

## Fidelity Notes

This branch is already a solid Among Us-style clone, but it is not a literal 1:1 copy yet.

Highest-value fidelity gaps:
- vent travel has cooldowns, but hidden vent occupancy/state is still simplified
- comms/admin/security are lighter-weight than the original information systems
- tasks are station interactions rather than faithful minigame recreations

## Visual Direction

For a shippable branch, prefer original/generated art under the `amongus` namespace over downloaded official game
art. The current asset pipeline already supports regenerating station sprites and terrain stamps with game-specific
prompts.

## Troubleshooting

### "Unknown" sprites in GUI

If objects render as unknown/missing:
- Rebuild mettascope atlases:

```bash
cd packages/mettagrid/nim/mettascope
nim r tools/gen_atlas.nim
```

- Then rerun the game.

If you changed Among Us art assets, also see:
- `metta/games/among_us/assets/README.md`

### Train smoke complains about git state

If local workspace cleanliness blocks train runs, use:
- `evaluator.skip_git_check=true`

### Lint fails due web workspace dependency resolution

If `metta lint --fix` fails in the `@softmax/website` type-check phase because of missing JS dependencies, run:

```bash
pnpm -C web/softmax.com install --frozen-lockfile
```

Then rerun:

```bash
metta lint --fix
```

## Key Files

Main game config:
- `metta/games/among_us/game/`

Map scene:
- `metta/games/among_us/map_scene.py`

Scripted policy:
- `metta/games/among_us/agent/amongcogs_agent/policy.py`

Headless runner and audit gates:
- `metta/games/among_us/headless.py`

Recipe entrypoints:
- `recipes/game/among_us.py`

## Ship Snapshot (2026-03-06)

Latest strict audit snapshot from this branch:
- Gate passed (`ship_strict`, `failed_count = 0`)
- Determinism passed (`repeats=2`, `episodes=4`)
- Winner rates:
  - crew: `0.775`
  - impostor: `0.2083`
- Coverage rates:
  - kills: `1.0`
  - reports: `1.0`
  - ejections: `1.0`
  - repairs: `0.8833`
  - sabotages: `0.775`
  - winner_declared: `0.9833`
- Release suite passed (`default_ship_strict` + `small_lobby_baseline`, pass rate `1.0`)
