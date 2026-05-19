# Architecture Overview

Date: 2026-02-08
Owner: Systems
Status: Active

This document provides a high-level architectural overview of the Tribal Village codebase.

## System Components

The system consists of three main layers:

```
┌─────────────────────────────────────────────────────────────┐
│                     Python Layer                            │
│  tribal_village_env/environment.py (PufferLib integration) │
│  tribal_village_env/cogames/ (training utilities)          │
└─────────────────────────┬───────────────────────────────────┘
                          │ ctypes FFI
┌─────────────────────────▼───────────────────────────────────┐
│                      FFI Layer                              │
│              src/ffi.nim (exported C functions)             │
└─────────────────────────┬───────────────────────────────────┘
                          │ direct calls
┌─────────────────────────▼───────────────────────────────────┐
│                     Nim Core                                │
│  Environment, Step, Spawn, Combat, Terrain, Renderer, AI   │
└─────────────────────────────────────────────────────────────┘
```

### Nim Core (~37,000 lines)

The core game simulation written in Nim for performance. Key modules:

| Module | Responsibility |
|--------|----------------|
| `types.nim` | Core type definitions, constants, `Environment` struct |
| `environment.nim` | Game state, observation building, stockpiles |
| `step.nim` | Per-tick action execution, entity updates |
| `spawn.nim` | Map generation, entity placement |
| `combat.nim` | Damage calculation, unit interactions |
| `terrain.nim` | Terrain types, movement costs |
| `biome.nim` | Biome definitions, resource bonuses |
| `spatial_index.nim` | Spatial partitioning for O(1) nearest-thing queries |
| `registry.nim` | Building/unit registry (costs, training, sprite keys) |
| `formations.nim` | Unit formation logic (Line/Box/Staggered) |
| `agent_control.nim` | Controller interface (built-in AI or external NN) |
| `renderer.nim` | Visual rendering (Boxy/OpenGL), UI panels |
| `scripted/` | Built-in AI behavior system |

### FFI Layer

`src/ffi.nim` exports C-compatible functions for Python:

**Core Environment:**
- `tribal_village_create()` - Create environment
- `tribal_village_reset_and_get_obs()` - Reset and get observations
- `tribal_village_step_with_pointers()` - Step with direct buffer I/O
- `tribal_village_render_rgb()` / `tribal_village_render_ansi()` - Rendering
- `tribal_village_destroy()` - Cleanup

**Unit Commands:**
- `tribal_village_set_attack_move()` / `tribal_village_set_patrol()` - Movement commands
- `tribal_village_set_stance()` / `tribal_village_garrison()` - Unit stance and garrisoning
- `tribal_village_stop()` / `tribal_village_hold_position()` - Position commands
- `tribal_village_follow_agent()` - Unit following

**Production & Research:**
- `tribal_village_queue_train()` / `tribal_village_queue_train_class()` - Unit training
- `tribal_village_research_blacksmith()` / `tribal_village_research_university()` - Research
- `tribal_village_set_rally_point()` - Building rally points

**Control Groups & Formations:**
- `tribal_village_create_control_group()` / `tribal_village_recall_control_group()`
- `tribal_village_set_formation()` / `tribal_village_get_formation()`

**Economy:**
- `tribal_village_market_buy()` / `tribal_village_market_sell()` - Market trading
- `tribal_village_get_gather_rate_multiplier()` - Economy bonuses

**AI & Difficulty:**
- `tribal_village_set_difficulty_level()` / `tribal_village_enable_adaptive_difficulty()`
- `tribal_village_set_threat_response_enabled()` / `tribal_village_set_coordination_enabled()`

Uses zero-copy buffer communication for performance.

### Python Wrapper

`tribal_village_env/environment.py` provides:

- `TribalVillageEnv` class implementing PufferLib's `PufferEnv`
- Gymnasium-compatible `reset()` / `step()` interface
- Direct numpy buffer passing to Nim (no conversion overhead)
- Cross-platform shared library loading

## Data Flow

### Step Cycle

```
Python                          Nim FFI                    Nim Core
  │                               │                          │
  │ step(actions_dict)            │                          │
  ├──────────────────────────────►│                          │
  │  actions_buffer (uint8[N])    │ step_with_pointers()     │
  │                               ├─────────────────────────►│
  │                               │                          │ env.step()
  │                               │                          │   - decode actions
  │                               │                          │   - execute moves/attacks
  │                               │                          │   - update entities
  │                               │                          │   - rebuild observations
  │                               │◄─────────────────────────┤
  │◄──────────────────────────────┤ write to buffers:        │
  │  obs_buffer, rewards,         │   observations           │
  │  terminals, truncations       │   rewards                │
  │                               │   terminals              │
  │                               │   truncations            │
```

### Observation Tensor

Shape: `[MapAgents, ObservationLayers, 11, 11]`

- 1006 agents total (8 teams × 125 + 6 goblins)
- 96 observation layers (terrain one-hot, thing one-hot, metadata)
- 11×11 viewport centered on each agent

Observations are rebuilt in batch at end of each step for efficiency.

### Action Encoding

Actions are encoded as single uint8:
```
action = verb * 28 + argument
```

11 verbs × 28 arguments = 308 action space.

See `docs/action_space.md` for verb definitions.

## Module Dependencies

```
tribal_village.nim (main entry)
    ├── environment.nim
    │       ├── imports:
    │       │   ├── entropy.nim, envconfig.nim
    │       │   ├── terrain.nim, items.nim, common_types.nim, biome.nim
    │       │   ├── types.nim (re-exports constants.nim)
    │       │   ├── registry.nim
    │       │   ├── spatial_index.nim
    │       │   ├── formations.nim
    │       │   ├── state_dumper.nim, arena_alloc.nim
    │       └── includes:
    │           ├── colors.nim, event_log.nim
    │           ├── placement.nim
    │           ├── combat_audit.nim, tumor_audit.nim
    │           ├── action_audit.nim, action_freq_counter.nim
    │           ├── combat.nim
    │           ├── tint.nim
    │           ├── connectivity.nim
    │           ├── spawn.nim
    │           ├── console_viz.nim, gather_heatmap.nim
    │           └── step.nim
    │               └── actions.nim
    ├── renderer.nim
    │       ├── minimap.nim
    │       ├── command_panel.nim
    │       └── tooltips.nim
    ├── agent_control.nim
    │       └── scripted/
    │           ├── ai_core.nim
    │           ├── ai_types.nim, ai_defaults.nim
    │           ├── ai_build_helpers.nim
    │           ├── roles.nim, options.nim
    │           ├── gatherer.nim, builder.nim, fighter.nim
    │           ├── coordination.nim
    │           ├── economy.nim, settlement.nim
    │           ├── evolution.nim
    │           └── ai_audit.nim
    └── tileset.nim

ffi.nim (shared library entry)
    ├── environment.nim
    └── agent_control.nim
```

Note: Several modules are `include`d rather than `import`ed for compile-time inlining.

## Key Entry Points

### `tribal_village.nim`

Main executable entry point for the standalone game/renderer:

1. Creates `Environment` via `newEnvironment()`
2. Initializes windowing (Windy) and rendering (Boxy)
3. Loads assets from `data/`
4. Runs game loop: input → `env.step()` → render

### `src/ffi.nim`

Shared library entry point (`libtribal_village.{dylib,so,dll}`):

1. Exports C-compatible functions with `{.exportc, dynlib.}`
2. Maintains global `Environment` instance
3. Provides direct buffer interface for Python
4. Used by `TribalVillageEnv` in Python

### `tribal_village_env/environment.py`

Python environment wrapper:

1. Loads Nim shared library via ctypes
2. Implements PufferLib's `PufferEnv` interface
3. Allocates numpy buffers for observations/rewards
4. Translates between Python dicts and C buffers

## Build Process

### Prerequisites

- Nim 2.2.4+ (2.2.6+ recommended, install via nimby)
- nimble (Nim package manager)
- Python 3.12+ with pufferlib
- OpenGL (for renderer)

### Building the Shared Library

```bash
# Install Nim dependencies
nimble install

# Build shared library for Python
nimble buildLib
# Produces: libtribal_village.{dylib,so,dll}
```

The nimble task runs:
```
nim c --app:lib --mm:arc --opt:speed -d:danger --out:libtribal_village.{ext} src/ffi.nim
```

### Building the Standalone Game

```bash
nimble run
# Or directly:
nim c -r tribal_village.nim
```

### Build Variants

| Define | Effect |
|--------|--------|
| `-d:danger` | Disable all runtime checks (production) |
| `-d:release` | Optimized build with some checks |
| `-d:renderTiming` | Enable frame timing profiler (main entry only) |
| `-d:stepTiming` | Enable step timing profiler |
| `-d:perfRegression` | Enable performance regression testing |
| `-d:enableEvolution` | Enable AI role evolution |
| `-d:emscripten` | WASM build for web |

### Python Package

```bash
pip install -e .
# Runs setup.py which triggers nimble buildLib
```

## Runtime Configuration

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `TV_LOG_RENDER_PATH` | Path for render logging output |
| `TV_AI_TIMING` | Enable AI timing profiler (set to "1") |
| `TV_AI_TIMING_INTERVAL` | Interval for AI timing reports |
| `TV_AI_LOG` | AI decision logging level |
| `TV_REPLAY_PATH` / `TV_REPLAY_DIR` | Replay output configuration |
| `TV_SCORECARD_ENABLED` | Enable balance scorecard collection |
| `TV_DUMP_INTERVAL` / `TV_DUMP_DIR` | State dumper for debugging |
| `TV_PERF_BASELINE` / `TV_PERF_SAVE_BASELINE` | Performance regression testing |
| `TV_EVENT_FILTER` / `TV_EVENT_SUMMARY` | Event log filtering |
| `TV_ECON_VERBOSE` / `TV_ECON_DETAILED` | Economy audit verbosity |
| `TV_SETTLER_LOG` / `TV_SETTLER_METRICS_INTERVAL` | Settlement system debugging |

### Python Config

`TribalVillageEnv` accepts config dict:
```python
env = TribalVillageEnv(config={
    "max_steps": 10000,
    "render_mode": "rgb_array",
    "victory_condition": 0,
    "tumor_spawn_rate": 0.1,
    # Reward coefficients:
    "heart_reward": 0.0,
    "ore_reward": 0.0,
    "wood_reward": 0.0,
    "food_reward": 0.0,
    "death_penalty": 0.0,
    # ... etc
})
```

Config is passed to Nim via `NimConfig` struct in the FFI layer.

## Code Style

### Nil Checking

Use the UFCS (Uniform Function Call Syntax) form `thing.isNil` rather than the function-call form `isNil(thing)`.

```nim
# Preferred - idiomatic Nim UFCS style
if thing.isNil:
  return
if not agent.isNil and agent.hp > 0:
  doSomething()

# Avoid - function-call style
if isNil(thing):
  return
if not isNil(agent) and agent.hp > 0:
  doSomething()
```

This convention applies throughout the codebase for consistency and readability.

## Related Documentation

- `docs/quickstart.md` - Getting started guide
- `docs/game_logic.md` - Game rules and mechanics
- `docs/observation_space.md` - Observation tensor details
- `docs/action_space.md` - Action encoding
- `docs/ai_system.md` - Built-in AI architecture
