# Movement Primitives

Universal movement patterns for grid-based and spatial games.

## Navigation Stack

The framework provides a layered navigation system. Each layer builds on the one below:

### Layer 1: Raw Actions

The game engine accepts discrete actions per tick. Common:

| Action | Effect |
|---|---|
| `noop` | Do nothing (waste a tick) |
| `move_north/south/east/west` | Move one cell in a cardinal direction |
| `move_to(target)` | High-level: pathfind and step toward target |

### Layer 2: Pathfinding (A*)

Given a start, goal, and passability map, A* finds the shortest path. The framework
provides a reusable `a_star(start, goal, is_passable)` function.

**When to use**: Any time you need to reach a known position through a mapped area.

**Gotchas**:
- A* only works on explored terrain — unknown cells default to impassable
- Recompute the path if the map changes (new walls discovered, obstacles moved)
- Cache paths for 5-10 ticks, then revalidate

### Layer 3: Frontier Exploration

When you don't have a specific target, explore the boundary between known and unknown:

1. **Flood fill** from current position through known-passable cells
2. **Find frontier cells** — known-passable cells adjacent to unknown cells
3. **Pick the best frontier** — closest, or in the least-explored direction
4. **A* to that frontier cell**

This systematically expands map coverage without revisiting explored areas.

### Layer 4: Stuck Detection

An agent is **stuck** when it visits ≤ N unique positions in the last M moves.
Common values: N=2, M=6.

**Recovery**:
1. Clear the pathfinding cache
2. Try a random cardinal move
3. If still stuck after 3 random moves, spiral outward
4. If stuck for 20+ ticks, signal the harness — the LLM may need to intervene

### Layer 5: Spiral Exploration

When frontier exploration is exhausted or the agent needs broad coverage fast:

```
Phase 1: Outward spiral from current position (radius 5, 10, 15, 20)
Phase 2: Clock pattern — waypoints at fixed angles around a center
Phase 3: Directed sweeps — straight lines toward unexplored quadrants
```

## Movement Commands

The brain's `decide()` method returns a `Command` with a `kind` and optional `target`:

```python
Command(kind=CommandKind.NAVIGATE_TO, target=(50, 30), reason="heading to resource")
Command(kind=CommandKind.EXPLORE, reason="frontier expansion")
Command(kind=CommandKind.FLEE, target=(40, 40), reason="retreating from threat")
Command(kind=CommandKind.IDLE, reason="waiting for event")
```

The policy's `execute()` method converts these into raw game actions.

## Universal Tips

- **Don't oscillate.** If the brain keeps switching between two targets, add hysteresis
  (commit to a target for at least N ticks before reconsidering)
- **Wall-hug for exploration.** Following walls reveals room interiors efficiently
- **Energy awareness.** If movement costs energy, plan routes that minimize waste
- **Group movement.** In multi-agent games, avoid agents blocking each other's paths
- **Retreat paths.** Always know how to get back to safety (hub, base, spawn)
