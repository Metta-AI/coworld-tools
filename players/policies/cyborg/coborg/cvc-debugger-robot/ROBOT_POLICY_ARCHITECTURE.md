# Robot Controller Architecture

## Control Loop

Every tick follows the same six-step pipeline:

```
PERCEIVE → UPDATE → SNAPSHOT → DECIDE → EXECUTE → RECORD
```

1. **PERCEIVE** — Raw 13x13 egocentric observation tokens parsed into a `FrameScan`
2. **UPDATE** — FrameScan integrated into persistent `SpatialMemory` (walls, entities, territory)
3. **SNAPSHOT** — Memory read into a `WorldSnapshot` (single source of truth for decisions)
4. **DECIDE** — Brain receives WorldSnapshot, returns a `MacroCommand` (high-level intent)
5. **EXECUTE** — Navigator converts MacroCommand into a concrete action via A* pathfinding
6. **RECORD** — Snapshot + action pushed to observability hub for debugging

## File Map (in cogames/robot/)

```
types.py         Coord, enums (MacroKind, NavStatus), dataclasses (MacroCommand, NavState)
perception.py    parse_observation() → FrameScan (only file that reads obs.tokens)
memory.py        SpatialMemory, SelfState, GameClock (persistent state across ticks)
pathfinding.py   a_star(), flood_fill(), find_frontier(), Navigator class
state.py         WorldSnapshot + build_snapshot() (only file that reads memory)
brain.py         RobotBrain.decide(snapshot) → MacroCommand
blackbox.py      BlackBox ring-buffer telemetry recorder
policy.py        RobotAgent (control loop) + RobotPolicy (multi-agent wrapper)
observability.py FastAPI server for debugger connection
```

## Role Draft

Agents negotiate roles via a `DraftBoard` during early ticks. After draft completes, each agent locks into their role permanently.

Draft assignments typically: agent 0 = miner, agent 1 = aligner (or scrambler).

## Brain Decision Logic

The brain runs role-specific strategies:

### Miner Strategy
1. No gear → navigate to miner gear station
2. Miner equipped → navigate to nearest extractor (mine)
3. Any single resource hits 40 (CARGO_DEPOSIT_THRESHOLD) → navigate to hub (deposit)
4. After sufficient deposits → may switch roles

### Aligner Strategy
1. No heart → navigate to hub (pick up heart)
2. Has heart → navigate to nearest neutral/alignable junction (capture)
3. After capture → return to hub for next heart

### Scrambler Strategy
1. No heart → navigate to hub
2. Has heart → navigate to nearest enemy junction (scramble)

### Emergency Overrides (any role)
- HP <= 5 → CRITICAL threat → FLEE to friendly territory
- HP <= 15 or HP runway < 5 ticks → HIGH threat → FLEE
- Energy <= 5 outside friendly territory → HIGH threat → FLEE

## Congestion Detection

`brain.congestion_ticks` counter (0–15) increments when the agent repeats the same command. At 15, forces a "congestion break" explore command. High average congestion = strategy is stuck.

## Navigation

Two-pass A* pathfinding:
1. **Strict** — only cells confirmed as open
2. **Optimistic** — treats unknown cells as passable (enables exploration)

Stuck detection: ≤2 unique positions in last 6 moves → clear path cache + random move.

Nav statuses:
- `IDLE` — no active navigation
- `NAVIGATING` — actively following a path
- `ARRIVED` — reached target
- `STUCK` — pathfinder can't make progress (multiple ticks)
- `UNREACHABLE` — no path exists to target

## Spatial Memory

Persistent map built from observations:
- **Walls** — discovered via tokens and movement failure feedback
- **Open cells** — seen and passable
- **Visited cells** — agent has been there
- **Territory** — AOE values (positive = friendly, negative = enemy)
- **Entities** — tracked with position, type, team, and staleness

Egocentric coordinate system: (0,0) = agent's spawn point. Both agents on the same team share the same coordinate frame.

## Team Coordination

`SharedMap` in policy.py merges spatial memory between teammates after the exploration phase, sharing walls, entities, and open cells.
