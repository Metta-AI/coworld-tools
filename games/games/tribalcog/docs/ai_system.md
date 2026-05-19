# AI System Overview

Date: 2026-01-28
Owner: Engineering / AI
Status: Active

## Overview
The built-in AI lives under `src/scripted/` and is wired in through
`src/agent_control.nim`. The system is intentionally lightweight: agents select
from a prioritized list of **behaviors (OptionDef)** rather than running a large
monolithic policy. The gatherer/builder/fighter roles are the current stable
baselines; a separate scripted/evolutionary path exists for generated roles.

## Current AI architecture (module imports)
The AI system uses proper Nim module imports with explicit exports:

- `src/agent_control.nim`
  - imports `scripted/ai_defaults` (re-exports it)
  - imports `formations`
  - Provides the unified action interface for agent control

- `src/scripted/ai_defaults.nim`
  - imports and exports: `ai_build_helpers`, `ai_audit`, `economy`, `evolution`, `settlement`, `replay_analyzer`
  - Contains role catalog management, decision-making, and controller update loop

- `src/scripted/ai_core.nim`
  - imports and exports: `ai_types`, `coordination`, `environment`, `common_types`, `terrain`, `entropy`
  - Provides foundational AI types, pathfinding, threat maps, and utility functions

- `src/scripted/options.nim`
  - imports and exports: `ai_types`, `ai_build_helpers`
  - Defines the OptionDef behavior system and common behavior implementations

Role files (`gatherer.nim`, `builder.nim`, `fighter.nim`, `roles.nim`) import the
core modules and define role-specific behavior option arrays.

## Module architecture

### Import-based design

The AI system now uses proper Nim module imports with explicit exports. This
provides clear symbol boundaries and explicit dependencies.

**Key modules:**

| Module | Purpose |
|--------|---------|
| `ai_types.nim` | Shared types: `AgentRole`, `AgentState`, `Controller`, `PathfindingCache`, `ThreatMap` |
| `ai_core.nim` | Foundational AI: pathfinding, threat maps, utility functions |
| `ai_defaults.nim` | Role catalog, decision-making, controller update loop |
| `options.nim` | `OptionDef` behavior system and common behaviors |
| `coordination.nim` | Inter-role coordination and cooperation |
| `economy.nim` | Economy tracking and resource prioritization |
| `settlement.nim` | Town expansion and settler behavior |
| `ai_build_helpers.nim` | Builder-specific helpers and site selection |
| `ai_audit.nim` | AI decision logging (with `-d:aiAudit`) |
| `evolution.nim` | Role evolution and fitness tracking |

### How imports work

Each module explicitly imports what it needs and exports what downstream modules
should access. For example:

```nim
# ai_core.nim
import ai_types
import coordination
export ai_types, coordination  # Make available to importers
```

This creates a clean dependency graph where:
- `ai_types.nim` is at the root (no AI-specific dependencies)
- `ai_core.nim` builds on types
- `ai_defaults.nim` orchestrates everything

### Implications for developers

**What works:**
- Adding new procs to any module with proper imports
- Adding new `OptionDef` entries to role arrays
- Calling exported procs from imported modules

**What to watch for:**
- **Explicit imports required**: Unlike the old include model, you must import
  modules to use their symbols
- **Export visibility**: Procs/types not marked with `*` or `export` are private
- **Circular dependency prevention**: The module hierarchy prevents cycles

### The module dependency graph

```
src/agent_control.nim
├── imports scripted/ai_defaults (exports it)
│   ├── imports ai_build_helpers (exports it)
│   ├── imports ai_audit (exports it)
│   ├── imports economy (exports it)
│   ├── imports evolution (exports it)
│   ├── imports settlement (exports it)
│   └── imports ../replay_analyzer (exports it)
│
└── imports formations (exports it)

src/scripted/ai_core.nim
├── imports ai_types (exports it)
├── imports coordination (exports it)
├── imports ../environment, ../common_types, ../terrain (exports all)
└── defines: pathfinding, threat maps, utility functions

src/scripted/ai_types.nim
├── imports ../environment, ../types
└── defines: AgentRole, AgentState, Controller, PathfindingCache, ThreatMap

src/scripted/options.nim
├── imports ai_types (exports it)
├── imports ai_build_helpers (exports it)
└── defines: OptionDef, runOptions, behavior implementations

Role files (gatherer.nim, builder.nim, fighter.nim):
├── import options (gets ai_types, ai_core via re-exports)
└── define: role-specific OptionDef arrays (GathererOptions, etc.)

src/scripted/roles.nim
├── imports options
└── defines: RoleDef, RoleCatalog, materializeRoleOptions

src/scripted/evolution.nim
├── imports roles
└── defines: role evolution, scoring, mutation
```

### Adding new code

**To add a new behavior:**
1. Define `canStart*` and `opt*` procs in the appropriate role file
2. Export them with `*` so they're accessible to the options system
3. Add an `OptionDef` entry to that role's options array
4. Ensure you import any needed modules (types come via `options` re-export)

**To add a new role file:**
1. Create `src/scripted/newrole.nim`
2. Add `import options` (or `import ai_types` for minimal dependencies)
3. Define your options array
4. Add `import newrole` and `export newrole` in `ai_defaults.nim`
5. Register behaviors in `seedDefaultBehaviorCatalog`

**To add a new utility module:**
1. Create `src/scripted/newmodule.nim`
2. Import `ai_types` for core types
3. Add to appropriate module's imports (e.g., `ai_core.nim` or `ai_defaults.nim`)
4. Export if needed by downstream modules

**Best practice**: Each file should have a header comment like:
```nim
## Description of module purpose
## Imported by: ai_defaults.nim, options.nim
```
This documents the module's role in the dependency graph.

## Roles and controller state
- `AgentRole` (in `src/scripted/ai_types.nim`): `Gatherer`, `Builder`, `Fighter`,
  `Scripted`.
- `Controller` owns per-agent `AgentState` (spiral search state, cached
  resource positions, active option tracking, path hints).
- `agent_control.getActions()` delegates to the controller for BuiltinAI.

## Role model and catalog
Scripted roles use a lightweight catalog model (`src/scripted/roles.nim`):
- **RoleDef**: `tiers`, `origin`, `kind` (Gatherer/Builder/Fighter/Scripted).
- **RoleTier**: ordered behavior IDs with a selection mode:
  - fixed (keep order)
  - shuffle (randomize each materialization)
  - weighted (weighted shuffle)
- **RoleCatalog**: maps behavior names to OptionDefs and holds all roles.

Roles are materialized into an ordered OptionDef list using
`materializeRoleOptions`, then executed via `runOptions`.

## Default role assignment
By default, each team spawns six active agents with fixed roles:
- Slot 0-1: Gatherer
- Slot 2-3: Builder
- Slot 4-5: Fighter

This mapping is defined in `decideAction()` in `src/scripted/ai_defaults.nim`.

## Role highlights (behavior intent)
These are high-level intent summaries; the exact option ordering lives in the
role option lists.

- **Gatherer**: selects a task based on stockpiles and altar hearts; gathers
  food/wood/stone/gold, plants on fertile tiles, and builds small camps near
  dense resources. Uses markets and stockpiles to drop off when carrying.
  Flees when enemies are nearby.
- **Builder**: focuses on pop-cap houses, core infrastructure and tech
  buildings, mills near fertile clusters, and defensive rings (walls/doors/
  outposts) around the altar. Flees when enemies are nearby. Uses adaptive
  wall radius and coordinates with other builders to prevent duplicate
  construction.
- **Fighter**: defends against nearby enemies, retreats on low HP, breaks out
  of enclosures, hunts wildlife, and supports monk/relic behaviors when
  applicable. Uses attack-move and patrol commands. Seeks healers when
  injured. Has emergency heal behavior at low HP. Prioritizes anti-siege
  targets and uses ranged kiting for archers.

## Inter-Role Coordination
The coordination system (`src/scripted/coordination.nim`) enables cross-role
awareness:
- **Gatherer/Fighter/Builder** roles share state about threats and resource needs.
- Agents can signal threats to teammates, triggering defensive responses across roles.
- Coordination reduces redundant work (e.g., multiple builders targeting the same site).

## Shared Threat Map
A team-wide **shared threat map** tracks enemy positions and recent combat events:
- Updated by all agents who observe enemies.
- Fighters use it to prioritize patrol routes and interception points.
- Builders and gatherers use it to avoid dangerous areas.

## Economy Management and Worker Allocation
The AI includes an **economy management** layer that:
- Monitors team stockpile levels to determine resource priorities.
- Adjusts gatherer resource weighting based on current needs.
- Allocates workers between gathering, building, and military tasks dynamically.

## Adaptive Difficulty
An **adaptive difficulty system** adjusts AI behavior based on game state:
- Difficulty levels affect AI reaction time, resource efficiency, and tactical sophistication.
- The system can ramp difficulty during an episode based on player performance.

## Scout Exploration
Scout units implement **line-of-sight exploration**:
- Scouts track which tiles have been revealed and prioritize unexplored areas.
- Enemy positions discovered by scouts are shared via the threat map.

## The behavior (OptionDef) system
`src/scripted/options.nim` defines the minimal behavior contract:

- `OptionDef` fields:
  - `name`
  - `canStart(controller, env, agent, agentId, state)`
  - `shouldTerminate(controller, env, agent, agentId, state)`
  - `act(controller, env, agent, agentId, state) -> uint8`
  - `interruptible`

`runOptions()` applies these rules:
1) If an active option exists, it may be pre-empted by a higher-priority option
   **only if** the active option is `interruptible`.
2) The active option’s `act()` is called. If it returns 0 or
   `shouldTerminate()` is true, the active option is cleared.
3) Otherwise, options are scanned in priority order; the first option that both
   `canStart()` and returns a non-zero action wins that tick.

This means options should **return 0** when they cannot act, so the scan can
continue.

## Where behaviors live
- **Behavior pool:** `src/scripted/options.nim`
- **Role composition:** `src/scripted/gatherer.nim`, `builder.nim`,
  `fighter.nim`, plus defaults in `ai_defaults.nim`
- **Role catalog + evolution:** `src/scripted/roles.nim`,
  `src/scripted/evolution.nim`

## Runtime assignment
`initScriptedState` seeds the catalog from default behaviors and sets up the
core roles. When compiled with `-d:enableEvolution`, it also loads history,
creates sampled roles, and builds the weighted role pool.

At assignment time:
- Core roles use their RoleDef entries.
- Scripted roles are selected from the role pool (weighted by fitness).
- Exploration can force a newly generated role.

## Evolution toggle and persistence
Evolution is gated behind `-d:enableEvolution`:
- Disabled: only core roles are used; no role history is loaded.
- Enabled: role history is loaded and updated; generated roles enter the pool.

Role and behavior fitness are saved to `data/role_history.json` after scoring
(default: step 5000). This file is intended to be committed so role genomes
are easy to diff and audit.

## Adding a new behavior (recommended pattern)
1) Implement `canStart` (fast, side-effect free).
2) Implement `act` (moves or uses an action; return 0 when you can’t act).
3) Decide termination:
   - stateless behaviors can use `optionsAlwaysTerminate`.
   - long-running behaviors should implement `shouldTerminate`.
4) Add an `OptionDef` to the appropriate role list, near similar priority.
5) Keep the behavior **focused** (one goal) so future meta-roles can re-order
   it safely.

## Modularization (completed)
The include-to-import refactoring has been completed. The current module structure:

- `ai_types.nim`: shared types (`AgentRole`, `AgentState`, `Controller`, `PathfindingCache`, `ThreatMap`)
- `options.nim`: `OptionDef`, `runOptions`, and common behavior implementations
- `ai_core.nim`: pathfinding, threat maps, and core utility functions
- `ai_defaults.nim`: `decideAction`, controller update logic, role catalog management
- Role files: `gatherer.nim`, `builder.nim`, `fighter.nim` (behavior option arrays)
- `roles.nim`: `RoleDef`, `RoleCatalog`, role materialization
- `evolution.nim`: role evolution, scoring, and mutation

Additional specialized modules:
- `coordination.nim`: inter-role coordination and team cooperation
- `economy.nim`: resource tracking and economy-driven decisions
- `settlement.nim`: town expansion and settler management
- `ai_build_helpers.nim`: builder site selection and construction helpers
- `ai_audit.nim`: AI decision logging for debugging

## Debugging and profiling hooks

### Quick profiling scripts
- `scripts/benchmark_steps.nim`: measure steps/second with perf regression detection (`make benchmark`)

### Compile-time instrumentation flags
All flags are zero-cost when disabled (code is compiled out entirely):

| Flag | Purpose |
|------|---------|
| `-d:stepTiming` | Per-subsystem step timing breakdown (11 subsystems) |
| `-d:perfRegression` | Sliding-window regression detection with baseline comparison |
| `-d:actionFreqCounter` | Action distribution by unit type per step |
| `-d:renderTiming` | Per-frame render timing |
| `-d:spatialAutoTune` | Density-based spatial index cell size adaptation |
| `-d:spatialStats` | Spatial query efficiency metrics |
| `-d:flameGraph` | CPU sampling in collapsed stack format |
| `-d:aiAudit` | AI decision logging (with `TV_AI_LOG=1`) |

See `docs/recently-merged-features.md` for full environment variable reference.
