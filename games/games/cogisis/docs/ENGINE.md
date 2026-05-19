# Cogisis Engine Notes

Cogisis uses a graph engine rather than a tile/grid renderer. The simulator is
the public boundary for policies and future viewers.

## Core Types

- `World`: full mutable game state.
- `Room`: ship node with numbered exits and search count.
- `Character`: crew state, wounds, contamination, ammo, inventory, objectives,
  and survival status.
- `Intruder`: hostile state, kind, room, damage, and health.
- `ShipStatus`: destination, engine states, time track, hibernation opening,
  and self-destruct state.
- `CogisisSimulator`: action parser, rules executor, event phase, observations,
  snapshots, rendering, and stats.

## Policy Boundary

Policies receive `CogisisSimulator` and return `{character_id: action_string}`.
The action string grammar is documented in `RULES.md`. Policies should use
`sim.observation(character_id)`, `world.shortest_path(...)`, and public world
collections rather than private helpers.

The CLI runs a game directly with `cogisis`; use `--cogs N` to choose the number
of player characters.

## Source Notes

The engine models the main concepts from the official Nemesis rulebook:
objectives plus survival, two-phase round structure, movement/noise/encounters,
intruder bag, wounds and contamination, ship engines/destination, hibernation,
escape pods, and endgame objective checks.

The implementation is a code model, not a reproduction of rulebook prose,
components, card text, or artwork.
