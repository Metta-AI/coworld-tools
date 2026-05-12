# Robot Controller -- Philosophy and First Principles

## What This Is

A self-contained robotic controller for the Cogs vs Clips (CvC) game built on MettaGrid. It controls agents on an 88x88 grid to capture and hold territory (junctions) against hostile Clips.

The controller is built from first principles -- it has its own A* pathfinder, flood fill, spatial memory, and perception parser. It does not depend on any existing policy files in this repo (`awareness.py`, `pathfinder.py`, `macro_actions.py`, etc.).

## Core Mental Model

Each game tick is one cycle of a robotic control loop. The agent is a robot. It has sensors (observation tokens), actuators (5 movement actions), and a brain (decision engine). Every tick follows the same six steps:

```
PERCEIVE -> UPDATE -> SNAPSHOT -> DECIDE -> EXECUTE -> RECORD
```

1. **PERCEIVE** -- Raw observation tokens from MettaGrid are parsed into a structured `FrameScan`. This is the only place in the entire codebase that reads `obs.tokens`.

2. **UPDATE** -- The `FrameScan` is integrated into persistent memory: walls discovered, entities tracked, position updated from movement feedback, territory recorded.

3. **SNAPSHOT** -- Memory is read once and assembled into a `WorldSnapshot` -- a complete, serializable picture of everything the agent knows. This is the single source of truth for all downstream logic.

4. **DECIDE** -- The brain receives a `WorldSnapshot` and returns a `MacroCommand` -- a high-level intent like "navigate to carbon extractor" or "flee to friendly territory".

5. **EXECUTE** -- The navigator converts the `MacroCommand` into a concrete action (`move_north`, `move_south`, etc.) using A* pathfinding.

6. **RECORD** -- The snapshot and chosen action are logged to the BlackBox for debugging, replay, and LLM context.

## Why This Architecture

### Separation of concerns

Each file does one thing. `perception.py` only parses tokens. `memory.py` only stores state. `pathfinding.py` only computes paths. `state.py` only builds snapshots. `brain.py` only makes decisions. No file reaches into another's internals.

### State isolation

The `WorldSnapshot` is a hard boundary. Only `state.py` reads from memory. The brain, blackbox, and any future LLM advisor receive a `WorldSnapshot` and nothing else. This means you can swap the decision engine without touching perception, memory, or navigation.

### Everything is serializable

`WorldSnapshot.to_dict()` produces JSON. `WorldSnapshot.to_prompt()` produces natural language. This makes every tick inspectable by humans and LLMs alike. The BlackBox records the full history for post-game analysis.

### Deterministic first

The controller works without any LLM. The brain runs a deterministic cooperation loop (mine -> deposit -> switch to aligner -> capture junction -> repeat). The LLM integration point is `RobotBrain.decide()` -- the exact same interface, just a different implementation.

## The Game Environment

### Observation

Each tick the agent receives a 13x13 egocentric window of sparse tokens. The agent sits at center cell (6, 6). Each token has:

- `location` -- (row, col) in the window, or `None` for global data
- `feature.name` -- what kind of data: `"tag"`, `"territory:here"`, `"territory:east"`, `"inv:carbon"`, `"last_action_move"`, etc.
- `feature.normalization` -- base for power-encoded inventory values
- `value` -- the data: tag ID, territory ownership value, item amount, etc.

The agent cannot see the full map. Fog of war is implicit -- anything outside the 13x13 window produces no tokens at all.

### Actions

There are exactly 5 actions: `noop`, `move_north`, `move_south`, `move_east`, `move_west`.

All interaction happens by moving INTO things. Walk into an extractor to mine. Walk into the hub to deposit. Walk into a gear station to equip. Walk into a junction to capture/scramble.

### Movement feedback

The `last_action_move` token tells the agent whether its previous move succeeded. If value is 0, the agent didn't move -- meaning it hit a wall or impassable structure. This is how the agent discovers walls it can't see directly.

### Roles

Roles are acquired at gear stations by spending resources from the team hub:

| Role | Ability | Key stat |
|------|---------|----------|
| Miner | 10x resource extraction | +40 cargo capacity |
| Aligner | Capture neutral junctions (costs 1 heart) | -- |
| Scrambler | Neutralize enemy junctions (costs 1 heart) | +200 HP |
| Scout | Mobile reconnaissance | +100 energy, +400 HP |

No single role can win alone. The cooperation loop requires miners to gather resources, then aligners to spend hearts capturing junctions.

### Territory

Junctions and hubs project an area-of-effect. Inside friendly territory, HP and energy regenerate. Outside, the agent takes 1 HP damage per tick and energy drains. This creates natural pressure to expand from the hub outward.

### Scoring

Reward per tick = `junctions_held / max_steps`. More junctions = more reward. Games run for 10,000 ticks.

## File Map

```
robot/
  __init__.py      Exports RobotPolicy
  types.py         Coord, enums (MacroKind, NavStatus), dataclasses (MacroCommand, NavState)
  perception.py    parse_observation() -> FrameScan (the only file that reads obs.tokens)
  memory.py        SpatialMemory, SelfState, GameClock (persistent state across ticks)
  pathfinding.py   a_star(), flood_fill(), find_frontier(), Navigator class
  state.py         WorldSnapshot + build_snapshot() (the only file that reads memory)
  brain.py         RobotBrain.decide(snapshot) -> MacroCommand
  blackbox.py      BlackBox ring-buffer telemetry recorder
  policy.py        RobotAgent (control loop) + RobotPolicy (multi-agent wrapper)
```

### Import order (no cycles)

`types` -> `perception` -> `memory` -> `pathfinding` -> `state` -> `brain` / `blackbox` -> `policy`

## Key Algorithms

### A* pathfinding (`pathfinding.py`)

Standard A* with manhattan distance heuristic. Takes a start position, a set of goal positions, and an `is_passable` predicate. Returns the shortest path as a list of coordinates, or `None` if unreachable.

The navigator runs A* in two passes:
1. **Strict** -- only considers cells confirmed as open (seen and passable)
2. **Optimistic** -- treats unknown cells as passable

This handles partial map knowledge gracefully: strict mode uses known-safe routes, optimistic mode allows exploration through unmapped areas.

### Flood fill (`pathfinding.py`)

BFS from a starting cell, expanding through all passable neighbors. Returns the set of all reachable cells. Useful for computing connected regions and reachability.

### Frontier exploration (`pathfinding.py`)

BFS to find the nearest unexplored cell -- one that is not in `known_open`, not in `visited`, not blocked, and adjacent to at least one known open cell. This drives systematic exploration of the map.

### Stuck detection (`pathfinding.py`)

If the agent occupies 2 or fewer unique positions in the last 6 moves, it's stuck. Recovery: clear the path cache and make a random valid move.

### Movement feedback wall discovery (`memory.py`)

When the agent tries to move but `last_action_move` reports failure, the target cell is added to the wall map. This discovers walls that might not be visible as tag tokens (e.g., trying to walk through a structure).

## The Cooperation Loop (`brain.py`)

The default solo-agent strategy:

1. No gear -> navigate to miner gear station
2. Miner equipped -> navigate to nearest extractor (mine resources)
3. Cargo >= 7 -> navigate to hub (deposit resources)
4. After 3 deposits -> navigate to aligner gear station (switch role)
5. Aligner equipped, no heart -> navigate to hub (pick up heart)
6. Aligner with heart -> navigate to nearest neutral junction (capture it)
7. Junction captured -> back to step 1

Emergency overrides interrupt at any point:
- HP <= 5 -> CRITICAL threat -> FLEE
- HP <= 15 or HP runway < 5 ticks -> HIGH threat -> FLEE
- Energy <= 5 outside friendly territory -> HIGH threat -> FLEE

## LLM Integration Point

The `RobotBrain.decide(snapshot: WorldSnapshot) -> MacroCommand` interface is designed for LLM override. The snapshot's `to_prompt()` method produces natural language like:

> Tick 450/10000 (EARLY). Pos (12, -5). Gear: miner, cargo: 6 carbon. HP 180, Energy 18. Friendly territory. Nav: NAVIGATING -> (15, -3), 4 steps. Junctions: 0 own, 2 neutral, 1 enemy. Threat: NONE. Doing: mining resources

An LLM can read this, reason about strategy, and return a `MacroCommand` that the navigator will execute. The deterministic brain serves as the fallback when no LLM is available.

## Extending This Controller

To add new behavior:

- **New macro commands** -- Add a variant to `MacroKind` in `types.py`, handle it in `Navigator.execute()` in `pathfinding.py`
- **Better decisions** -- Modify `RobotBrain.decide()` in `brain.py`, or subclass it
- **New state tracking** -- Add fields to `WorldSnapshot` in `state.py`, populate them in `build_snapshot()`
- **Multi-agent coordination** -- Share state between `RobotAgent` instances through the `RobotPolicy` wrapper
- **LLM advisor** -- Implement a class with `decide(snapshot) -> MacroCommand` and wire it into `policy.py`
