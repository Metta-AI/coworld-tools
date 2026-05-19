# Configuration Reference

Date: 2026-02-06
Owner: Docs / Systems
Status: Active

This document is the canonical reference for all Tribal Village configuration options. It covers
runtime parameters (tunable at initialization), compile-time constants, and environment variables.

## Runtime Configuration (EnvironmentConfig)

The `EnvironmentConfig` object controls runtime behavior of the simulation. These parameters can
be adjusted when creating an environment without recompiling.

### Python Usage

```python
from tribal_village_env import make_tribal_village_env

env = make_tribal_village_env(config={
    "max_steps": 5000,
    "heart_reward": 2.0,
    "death_penalty": -10.0,
    # ... other options
})
```

Configuration values are passed through the FFI layer to the Nim engine. Unspecified values use
defaults from `defaultEnvironmentConfig()` in `src/types.nim`.

### Core Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_steps` | int | 3000 | Maximum simulation steps per episode. Episode truncates when this limit is reached. |

**Impact:** Controls episode length. Longer episodes allow more complex strategies but increase
training time. Short episodes (1000-2000) are good for rapid iteration; production training
typically uses 3000-10000.

### Combat Configuration

| Parameter | Type | Default | Range | Description |
|-----------|------|---------|-------|-------------|
| `tumor_spawn_rate` | float | 0.1 | 0.0-1.0 | Probability per step that spawners generate new tumors. |

**Impact:** Higher values increase environmental pressure from clippy/tumors. At 0.0, tumors never
spawn (peaceful mode). At 1.0, spawners attempt to create tumors every step.

### Reward Configuration

Rewards shape agent learning by providing positive or negative signals for specific actions or
outcomes. The default configuration uses the "arena_basic_easy_shaped" reward profile.

#### Active Rewards (Default Profile)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `heart_reward` | float | 1.0 | Reward for depositing bars at an altar (creates hearts). |
| `ore_reward` | float | 0.1 | Reward for mining gold ore from deposits. |
| `bar_reward` | float | 0.8 | Reward for smelting ore into bars at magma pools. |

**Gameplay impact:** These rewards encourage the core resource loop: mine ore -> smelt bars ->
deposit at altar. The relative weights (ore: 0.1, bar: 0.8, heart: 1.0) create increasing rewards
as resources are processed.

#### Disabled Rewards (Set to 0.0 by Default)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `wood_reward` | float | 0.0 | Reward for harvesting wood from trees. |
| `water_reward` | float | 0.0 | Reward for collecting water (fishing, buckets). |
| `wheat_reward` | float | 0.0 | Reward for harvesting wheat. |
| `spear_reward` | float | 0.0 | Reward for crafting spears. |
| `armor_reward` | float | 0.0 | Reward for crafting armor. |
| `food_reward` | float | 0.0 | Reward for producing food (bread, cooked items). |
| `cloth_reward` | float | 0.0 | Reward for producing cloth at weaving looms. |
| `tumor_kill_reward` | float | 0.0 | Reward for destroying tumors. |

**Usage:** Enable these rewards to encourage specific behaviors. For example, set `wood_reward: 0.1`
to incentivize wood gathering for construction-focused training.

#### Penalties

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `survival_penalty` | float | -0.01 | Per-step penalty applied to all alive agents. |
| `death_penalty` | float | -5.0 | One-time penalty when an agent dies. |

**Gameplay impact:**
- `survival_penalty` creates time pressure, encouraging efficient action rather than idle behavior.
  Stronger penalties (-0.05 to -0.1) push agents toward faster resource gathering.
- `death_penalty` discourages risky behavior. Adjust based on whether you want cautious or
  aggressive agents.

### Example Configurations

#### Peaceful Exploration

```python
config = {
    "max_steps": 10000,
    "tumor_spawn_rate": 0.0,
    "survival_penalty": 0.0,
    "death_penalty": 0.0,
}
```

#### Aggressive Combat Training

```python
config = {
    "max_steps": 2000,
    "tumor_spawn_rate": 0.3,
    "tumor_kill_reward": 2.0,
    "death_penalty": -2.0,
}
```

#### Full Economy

```python
config = {
    "max_steps": 5000,
    "heart_reward": 1.0,
    "ore_reward": 0.1,
    "bar_reward": 0.5,
    "wood_reward": 0.1,
    "food_reward": 0.3,
    "cloth_reward": 0.2,
}
```

## Compile-Time Constants

These values are set at compile time in `src/types.nim` and require recompilation to change.
They define the structural parameters of the simulation.

### Map Layout

| Constant | Value | Description |
|----------|-------|-------------|
| `MapLayoutRoomsX` | 1 | Number of rooms horizontally. |
| `MapLayoutRoomsY` | 1 | Number of rooms vertically. |
| `MapBorder` | 1 | Border tiles around the map. |
| `MapRoomWidth` | 305 | Width of each room in tiles. |
| `MapRoomHeight` | 191 | Height of each room in tiles. |
| `MapWidth` | computed | Total map width (rooms * room_width + border). |
| `MapHeight` | computed | Total map height (rooms * room_height + border). |

### Agent Configuration

| Constant | Value | Description |
|----------|-------|-------------|
| `MapRoomObjectsTeams` | 8 | Number of player teams. |
| `MapAgentsPerTeam` | 125 | Agent slots per team. |
| `MapAgents` | 1006 | Total agent slots (8 teams * 125 + 6 goblins). |
| `AgentMaxHp` | 5 | Default max HP for villagers. |
| `MapObjectAgentMaxInventory` | 5 | Maximum inventory slots per agent. |

### Observation System

| Constant | Value | Description |
|----------|-------|-------------|
| `ObservationWidth` | 11 | Width of agent observation window. |
| `ObservationHeight` | 11 | Height of agent observation window. |
| `ObservationRadius` | 5 | Observation radius (width / 2). |
| `ObservationLayers` | 96 | Total observation tensor layers. |

### Unit Stats

#### Health Points

| Unit | Max HP | Notes |
|------|--------|-------|
| Villager | 5 | Default unit. |
| Man-at-Arms | 7 | Frontline infantry. |
| Archer | 4 | Ranged, fragile. |
| Scout | 6 | Fast, medium durability. |
| Knight | 8 | Heavy cavalry. |
| Monk | 4 | Support unit. |
| Battering Ram | 18 | Siege, high HP. |
| Mangonel | 12 | Siege, AoE damage. |
| Goblin | 4 | NPC hostile. |

#### Attack Damage

| Unit | Damage | Range | Notes |
|------|--------|-------|-------|
| Villager | 1 | 1 | Basic attack. |
| Man-at-Arms | 2 | 1 | Strong melee. |
| Archer | 1 | 3 | Ranged attack. |
| Scout | 1 | 1 | Fast attack. |
| Knight | 2 | 1 | Heavy attack. |
| Monk | 0 | - | Heals/converts instead. |
| Battering Ram | 2 | 1 | Siege bonus vs structures (3x). |
| Mangonel | 2 | 3 | AoE damage, siege bonus. |
| Goblin | 1 | 1 | NPC attack. |

### Building Stats

| Building | Max HP | Special |
|----------|--------|---------|
| Wall | 10 | Basic defense. |
| Door | 5 | Passable by team. |
| Outpost | 8 | Vision. |
| Guard Tower | 14 | Auto-attacks (damage: 2, range: 4). Garrison capacity: 5. |
| Town Center | 20 | Garrison capacity: 15. |
| Castle | 30 | Auto-attacks (damage: 3, range: 6). Garrison capacity: 20. |
| Monastery | 12 | Monk training. |
| Wonder | 80 | Victory condition (600 step countdown). |
| House | — | Population cap: +4. Garrison capacity: 5. |

### Wildlife

| Animal | Max HP | Damage | Behavior |
|--------|--------|--------|----------|
| Bear | 6 | 2 | Aggressive, aggro radius: 6. |
| Wolf | 3 | 1 | Pack hunter, pack size: 3-5. |
| Cow | - | - | Passive, herd movement. |

### Resource Costs

| Constant | Value | Description |
|----------|-------|-------------|
| `RoadWoodCost` | 1 | Wood to build road. |
| `OutpostWoodCost` | 1 | Wood to build outpost. |
| `ResourceCarryCapacity` | 5 | Max resources an agent can carry. |
| `ResourceNodeInitial` | 25 | Starting resources in nodes (trees, mines). |
| `MineDepositAmount` | 100 | Resources in mine deposits. |

## Environment Variables

These variables control runtime behavior and are read at process startup.

### Profiling

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_PROFILE_STEPS` | 3000 | Steps to run in headless profile mode. |
| `TV_PROFILE_REPORT_EVERY` | 0 | Log progress every N steps (0 = disabled). |
| `TV_PROFILE_SEED` | 42 | Random seed for profiling runs. |

### Step Timing (requires `-d:stepTiming`)

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_STEP_TIMING` | -1 | Target step to start timing (-1 = disabled). |
| `TV_STEP_TIMING_WINDOW` | 0 | Number of steps to time. |

### AI Decision Timing (requires `-d:stepTiming`)

Instruments agent decision-making loops to identify slow AI evaluations.

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_AI_TIMING` | 0 | Enable AI timing (1 = enabled, 0 = disabled). |
| `TV_AI_TIMING_INTERVAL` | 100 | Print report every N steps. |
| `TV_AI_TIMING_TOP_N` | 10 | Number of slowest agents to show in report. |

Example usage:
```bash
TV_AI_TIMING=1 TV_AI_TIMING_INTERVAL=50 nim r -d:stepTiming -d:release --path:src tribal_village.nim
```

The report shows:
- Total AI decision time (average and max per step)
- Top N slowest agents by cumulative decision time
- Per-agent average and max decision times

### Render Timing (requires `-d:renderTiming`)

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_RENDER_TIMING` | -1 | Target frame to start timing (-1 = disabled). |
| `TV_RENDER_TIMING_WINDOW` | 0 | Number of frames to time. |
| `TV_RENDER_TIMING_EVERY` | 1 | Log every N frames. |
| `TV_RENDER_TIMING_EXIT` | -1 | Exit after this frame (-1 = disabled). |

#### Timing Output Format

When enabled, outputs one line per frame with the following metrics (all times in milliseconds):

| Metric | Description |
|--------|-------------|
| `total_ms` | Full frame time from start of display() to end of swapBuffers |
| **Early Frame Phases** | |
| `input_ms` | Input handling (keyboard, mouse, UI toggles) |
| `sim_ms` | Simulation step(s) - may include multiple steps if catching up |
| `beginframe_ms` | bxy.beginFrame() call |
| `setup_ms` | Transform setup (camera, zoom, viewport) |
| `interaction_ms` | World interaction (selection, drag, minimap, commands) |
| **Render Phases** | |
| `render_ms` | Total rendering time (from after interaction to swapBuffers) |
| `floor_ms` | Floor tile rendering |
| `terrain_ms` | Terrain sprite rendering |
| `walls_ms` | Wall structure rendering |
| `objects_ms` | Agents, buildings, resources rendering |
| `decor_ms` | Combined decoration time (sum of individual below) |
| `agentdecor_ms` | Agent decorations (health bars, control group badges, status icons) |
| `projectiles_ms` | Projectile rendering |
| `damagenums_ms` | Floating damage numbers |
| `ragdolls_ms` | Corpse/ragdoll rendering |
| `debris_ms` | Building debris particles |
| `dust_ms` | Construction dust effects |
| `trails_ms` | Unit movement trails (footprints/dust) |
| `spawn_ms` | Unit spawn effect animations |
| `trade_ms` | Trade route line visualization |
| `weather_ms` | Weather effects (rain particles, wind debris) |
| `visual_ms` | Visual range indicators |
| `grid_ms` | Debug grid overlay |
| `fog_ms` | Fog of war rendering |
| `selection_ms` | Selection highlight |
| `ui_ms` | UI elements (resource bar, minimap, panels) |
| `mask_ms` | Masking/compositing |
| `end_ms` | bxy.endFrame() call |
| `swap_ms` | window.swapBuffers() call |
| **Diagnostics** | |
| `things` | Total thing count |
| `agents` | Agent count |
| `tumors` | Tumor count |

### Render Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_LOG_RENDER` | false | Enable render logging. |
| `TV_LOG_RENDER_WINDOW` | 100 | Window size for render logging. |
| `TV_LOG_RENDER_EVERY` | 1 | Log every N renders. |
| `TV_LOG_RENDER_PATH` | "" | Path for render log output. |

### Replay Recording

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_REPLAY_DIR` | "" | Directory for replay files. |
| `TV_REPLAY_PATH` | "" | Explicit replay file path (overrides dir). |
| `TV_REPLAY_NAME` | "tribal_village" | Base name for replay files. |
| `TV_REPLAY_LABEL` | "Tribal Village Replay" | Label metadata in replay. |

### Controller Mode

| Variable | Description |
|----------|-------------|
| `TRIBAL_PYTHON_CONTROL` | Use external neural network controller. |
| `TRIBAL_EXTERNAL_CONTROL` | Use external neural network controller. |

### Build Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TRIBAL_VILLAGE_NIM_VERSION` | 2.2.6 | Nim version for Python build. |
| `TRIBAL_VILLAGE_NIMBY_VERSION` | 0.1.11 | Nimby version for Python build. |
| `TRIBAL_VECTOR_BACKEND` | "serial" | Vector backend for training (serial/ray). |

### Performance Regression Detection (requires `-d:perfRegression`)

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_PERF_BASELINE` | "" | Path to baseline JSON file to compare against. |
| `TV_PERF_THRESHOLD` | 10 | Regression threshold percentage. |
| `TV_PERF_WINDOW` | 100 | Sliding window size in steps. |
| `TV_PERF_INTERVAL` | 100 | Report/check interval in steps. |
| `TV_PERF_SAVE_BASELINE` | "" | Path to save captured baseline (capture mode). |
| `TV_PERF_FAIL_ON_REGRESSION` | "0" | If "1", exit with non-zero code on regression (CI mode). |

**CI usage:**
```bash
# Capture baseline:
TV_PERF_SAVE_BASELINE=baselines/baseline.json \
  nim c -r -d:perfRegression -d:release --path:src scripts/benchmark_steps.nim

# Check for regressions:
TV_PERF_BASELINE=baselines/baseline.json TV_PERF_FAIL_ON_REGRESSION=1 \
  nim c -r -d:perfRegression -d:release --path:src scripts/benchmark_steps.nim
```

## Compile-Time Flags

These flags are passed to the Nim compiler to enable optional features.

| Flag | Purpose |
|------|---------|
| `-d:release` | Enable optimizations. |
| `-d:danger` | Maximum speed (no bounds checks). |
| `-d:stepTiming` | Enable step timing instrumentation. |
| `-d:renderTiming` | Enable render timing instrumentation. |
| `-d:perfRegression` | Enable performance regression detection. |
| `-d:enableEvolution` | Enable AI evolution layer. |
| `-d:audio` | Enable audio system. |
| `-d:aiAudit` | Enable AI decision audit logging. |
| `-d:actionAudit` | Enable action distribution logging. |
| `-d:actionFreqCounter` | Enable action frequency by unit type logging. |

### Step Timing (`-d:stepTiming`)

Instruments the main simulation loop to measure time spent in each phase per step.
Useful for identifying performance bottlenecks in specific subsystems.

**Usage:**
```bash
nim r -d:stepTiming -d:release --path:src tribal_village.nim
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_STEP_TIMING` | -1 | Target step to start timing (-1 = disabled). |
| `TV_STEP_TIMING_WINDOW` | 0 | Number of steps to time around the target. |

**Example:**
```bash
TV_STEP_TIMING=100 TV_STEP_TIMING_WINDOW=50 \
  nim r -d:stepTiming -d:release --path:src tribal_village.nim
```

This will output detailed per-phase timing (in milliseconds) for steps 100-150, showing
time spent in combat, movement, pathfinding, economy, and other simulation subsystems.

**Performance impact:** Minimal when timing is disabled (TV_STEP_TIMING=-1). When active,
adds overhead from `getMonoTime()` calls at each phase boundary.

### AI Audit (`-d:aiAudit`)

Instruments AI decision-making to track which code paths agents take and what actions
they choose. Useful for debugging AI behavior and understanding agent decision patterns.

**Usage:**
```bash
nim r -d:aiAudit -d:release --path:src tribal_village.nim
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_AI_LOG` | 0 | Logging level: 0=off, 1=summary every 50 steps, 2=verbose per-agent per-step. |

**Example:**
```bash
TV_AI_LOG=1 nim r -d:aiAudit -d:release --path:src tribal_village.nim
```

**Output (summary mode, every 50 steps):**
- Action distribution: counts and percentages for each action verb (move, attack, build, etc.)
- Role distribution per team: breakdown by agent role (Gatherer, Builder, Fighter, Scripted)
- Decision branches: which code paths led to each decision (escape mode, patrol, attack-move, etc.)

**Performance impact:** Low when disabled (TV_AI_LOG=0). Summary mode (level 1) adds minimal
overhead from counter increments. Verbose mode (level 2) has higher impact due to per-decision
string formatting and output.

### Action Audit (`-d:actionAudit`)

Tracks per-step and per-team action distributions. Provides aggregate reports showing
how actions are distributed across the simulation.

**Usage:**
```bash
nim r -d:actionAudit -d:release --path:src tribal_village.nim
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_ACTION_AUDIT_INTERVAL` | 100 | Steps between aggregate reports. |

**Example:**
```bash
TV_ACTION_AUDIT_INTERVAL=50 nim r -d:actionAudit -d:release --path:src tribal_village.nim
```

**Output:**
- Per-step action counts by verb (noop, move, attack, use, swap, put, build, orient, etc.)
- Per-team breakdown showing idle%, move%, attack%, build% for each team
- Aggregate reports every N steps showing trends over the reporting window

**Performance impact:** Adds counter increment per action (~1000 agents × 1 step = ~1000 increments).
Negligible overhead in release builds. Report printing adds I/O overhead at intervals.

### Action Frequency Counter (`-d:actionFreqCounter`)

Tracks action frequency broken down by unit type (villager, archer, knight, etc.).
Useful for understanding which unit types are performing which actions.

**Usage:**
```bash
nim r -d:actionFreqCounter -d:release --path:src tribal_village.nim
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TV_ACTION_FREQ_INTERVAL` | 100 | Steps between aggregate reports. |

**Example:**
```bash
TV_ACTION_FREQ_INTERVAL=50 nim r -d:actionFreqCounter -d:release --path:src tribal_village.nim
```

**Output:**
```
===============================================================================
  ACTION FREQUENCY BY UNIT TYPE - Steps 1-100 (100 steps)
===============================================================================

Unit Type          noop   move attack    use   swap    put     pl     pr  build orient  rally   Total
--------------------------------------------------------------------------------------------------
Villager            523   1245    102     45     12      8      0      0    234      0      0    2169
Man-at-Arms          45    312    456      0      0      0      0      0      0     23      0     836
...
```

**Performance impact:** Similar to actionAudit. Adds counter increment per action indexed by
unit type. Negligible overhead in release builds.

### Combining Audit Flags

Multiple audit flags can be combined for comprehensive analysis:

```bash
nim r -d:stepTiming -d:aiAudit -d:actionAudit -d:actionFreqCounter \
  -d:release --path:src tribal_village.nim
```

Set environment variables to control output verbosity:
```bash
TV_STEP_TIMING=100 TV_STEP_TIMING_WINDOW=200 \
TV_AI_LOG=1 \
TV_ACTION_AUDIT_INTERVAL=100 \
TV_ACTION_FREQ_INTERVAL=100 \
  nim r -d:stepTiming -d:aiAudit -d:actionAudit -d:actionFreqCounter \
  -d:release --path:src tribal_village.nim
```

**Note:** When compiled without these flags (`-d:actionAudit`, etc.), the audit code is
completely eliminated by the compiler. There is zero runtime cost for disabled features.

## Reference Files

- `src/types.nim`: EnvironmentConfig definition and compile-time constants.
- `src/constants.nim`: Balance constants (building HP, unit stats, tech costs, combat AI).
- `src/config.nim`: Centralized runtime configuration with validation and help generation.
- `src/perf_regression.nim`: Performance regression detection system.
- `src/action_audit.nim`: Action distribution logging (requires `-d:actionAudit`).
- `src/action_freq_counter.nim`: Action frequency by unit type (requires `-d:actionFreqCounter`).
- `src/scripted/ai_audit.nim`: AI decision audit logging (requires `-d:aiAudit`).
- `src/ffi.nim`: FFI layer for Python config passing.
- `tribal_village_env/environment.py`: Python configuration interface.
- `Makefile`: Build/test/benchmark targets.
- `docs/quickstart.md`: Additional environment variable documentation.
