# Python API Reference

Date: 2026-05-22
Owner: Engineering / AI
Status: Active

This document covers the Python API for the Tribal Village environment, including the main environment class, configuration options, and PufferLib integration.

## Installation

```bash
# Basic installation
pip install -e .

# With training support (PufferLib, CoGames)
pip install -e .[cogames]
```

## Quick Start

```python
from tribal_village_env import TribalVillageEnv, make_tribal_village_env

# Create environment with factory function
env = make_tribal_village_env(config={"max_steps": 5000})

# Or instantiate directly
env = TribalVillageEnv(config={"max_steps": 5000})

# Standard Gymnasium interface
obs, info = env.reset()
for _ in range(100):
    actions = {f"agent_{i}": env.single_action_space.sample() for i in range(env.num_agents)}
    obs, rewards, terminated, truncated, info = env.step(actions)
env.close()
```

## TribalVillageEnv Class

The main environment class inherits from `pufferlib.PufferEnv` and implements the Gymnasium multi-agent interface.

### Constructor

```python
TribalVillageEnv(config: Optional[Dict[str, Any]] = None, buf=None)
```

**Parameters:**
- `config`: Configuration dictionary (see [Configuration](#configuration))
- `buf`: PufferLib buffer allocation (managed automatically in most cases)

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `num_agents` | `int` | Total number of agents (default: 1006) |
| `total_agents` | `int` | Alias for `num_agents` |
| `agents` | `List[str]` | List of agent IDs (`["agent_0", "agent_1", ...]`) |
| `possible_agents` | `List[str]` | Copy of `agents` list |
| `single_observation_space` | `spaces.Box` | Observation space for one agent |
| `single_action_space` | `spaces.Discrete` | Action space for one agent (308 actions) |
| `action_space` | `JointSpace` | Combined action space for all agents |
| `render_mode` | `str` | Current render mode (`"rgb_array"` or `"ansi"`) |
| `step_count` | `int` | Current step number in episode |
| `max_steps` | `int` | Maximum steps per episode |

### Methods

#### reset

```python
reset(seed: Optional[int] = None, options: Optional[Dict] = None) -> Tuple[Dict, Dict]
```

Reset the environment to initial state.

**Returns:**
- `observations`: Dict mapping agent IDs to observation arrays
- `info`: Dict mapping agent IDs to info dicts (empty by default)

**Example:**
```python
obs, info = env.reset(seed=42)
# obs["agent_0"] is a numpy array of shape (env.obs_layers, 11, 11).
# Current code reports 101 layers.
```

#### step

```python
step(actions: Dict[str, np.ndarray]) -> Tuple[Dict, Dict, Dict, Dict, Dict]
```

Execute one environment step.

**Parameters:**
- `actions`: Dict mapping agent IDs to action integers (0-307)

**Returns:**
- `observations`: Dict mapping agent IDs to observation arrays
- `rewards`: Dict mapping agent IDs to float rewards
- `terminated`: Dict mapping agent IDs to boolean termination flags
- `truncated`: Dict mapping agent IDs to boolean truncation flags
- `infos`: Dict mapping agent IDs to info dicts

**Example:**
```python
actions = {"agent_0": 28, "agent_1": 56}  # Move north, attack north
obs, rewards, terminated, truncated, info = env.step(actions)
```

#### render

```python
render() -> Union[np.ndarray, str]
```

Render the current state.

**Returns:**
- If `render_mode="rgb_array"`: NumPy array of shape `(height, width, 3)` with uint8 RGB values
- If `render_mode="ansi"`: String with ANSI-colored text representation

#### close

```python
close() -> None
```

Clean up environment resources. Always call when done.

## Configuration

Configuration is passed as a dictionary to the environment constructor. Unspecified values use defaults.

The Python wrapper defaults are not identical to the direct Nim executable:
`EnvironmentConfig()` defaults to `max_steps=10000` and `victory_condition=0`
(`VictoryNone`) before sending config through FFI. Direct Nim runs use
`defaultEnvironmentConfig()` in `src/types.nim`, which defaults to
`maxSteps=3000` and `VictoryAll`.

### Core Parameters

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_steps` | int | 10000 | Maximum steps per episode |
| `victory_condition` | int | 0 | Victory condition enum value (`0` is `VictoryNone`) |
| `ai_mode` | str | `"external"` | Controller mode: `"external"`, `"builtin"`, or `"hybrid"` |
| `render_mode` | str | `"rgb_array"` | Render mode (`"rgb_array"` or `"ansi"`) |
| `render_scale` | int | 4 | Scale factor for RGB rendering |

### Reward Shaping

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `heart_reward` | float | 1.0 | Reward for depositing bars at altar |
| `ore_reward` | float | 0.1 | Reward for mining gold ore |
| `bar_reward` | float | 0.8 | Reward for smelting ore into bars |
| `wood_reward` | float | 0.0 | Reward for harvesting wood |
| `water_reward` | float | 0.0 | Reward for collecting water |
| `wheat_reward` | float | 0.0 | Reward for harvesting wheat |
| `spear_reward` | float | 0.0 | Reward for crafting spears |
| `armor_reward` | float | 0.0 | Reward for crafting armor |
| `food_reward` | float | 0.0 | Reward for producing food |
| `cloth_reward` | float | 0.0 | Reward for producing cloth |
| `tumor_kill_reward` | float | 0.0 | Reward for destroying tumors |

### Penalties

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `survival_penalty` | float | -0.01 | Per-step penalty for all alive agents |
| `death_penalty` | float | -5.0 | One-time penalty when agent dies |

### Combat

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `tumor_spawn_rate` | float | 0.1 | Probability per step that spawners create tumors |

### Configuration Examples

```python
# Peaceful exploration
config = {
    "max_steps": 10000,
    "tumor_spawn_rate": 0.0,
    "survival_penalty": 0.0,
    "death_penalty": 0.0,
}

# Combat training
config = {
    "max_steps": 2000,
    "tumor_spawn_rate": 0.3,
    "tumor_kill_reward": 2.0,
    "death_penalty": -2.0,
}

# Full economy
config = {
    "max_steps": 5000,
    "heart_reward": 1.0,
    "ore_reward": 0.1,
    "bar_reward": 0.5,
    "wood_reward": 0.1,
    "food_reward": 0.3,
}
```

## Observation Space

### Shape

```python
env.single_observation_space.shape  # (layers, 11, 11)
env.single_observation_space.dtype  # np.uint8
```

- **Layers**: `env.obs_layers` channels (check `ObservationName` enum in `src/types.nim`)
- **Spatial**: 11x11 tiles centered on the agent (radius 5)
- **Values**: 0-255 (uint8)

### Layer Groups

**Terrain layers (one-hot):** Encode terrain type at each tile position.
- Empty, Water, Bridge, Fertile, Road, Grass, Dune, Sand, Snow
- Ramp directions (up/down for each cardinal direction)

**Thing layers (one-hot):** Encode entity presence at each tile.
- Agents, walls, resources, animals, buildings
- One layer per `ThingKind` enum value

**Meta layers:** Additional information per tile.
- `TeamLayer`: Team ID + 1 (0 = neutral/none)
- `AgentOrientationLayer`: Agent orientation + 1 (0 = no agent)
- `AgentUnitClassLayer`: Unit class + 1 (0 = no agent)
- `AgentIdleLayer`: 1 if agent is idle (NOOP/ORIENT action), 0 otherwise
- `TintLayer`: Action/combat tint codes
- `RallyPointLayer`: 1 if a friendly building has its rally point on this tile
- `BiomeLayer`: Biome type enum value
- `ObscuredLayer`: 1 if tile is above observer elevation (hidden)

See `docs/observation_space.md` for complete layer documentation.

## Action Space

### Encoding

Actions are encoded as a single integer from 0 to 307:

```
action = verb * 28 + argument
```

- **Verbs**: 0-10 (11 action types)
- **Arguments**: 0-27 (28 possible arguments per verb)
- **Total**: 308 discrete actions

### Verb Reference

| Verb | Name | Description | Arguments |
|------|------|-------------|-----------|
| 0 | noop | No operation | Any (ignored) |
| 1 | move | Move in direction | 0-7 (directions) |
| 2 | attack | Attack in direction | 0-7 (directions) |
| 3 | use | Interact with terrain/building | 0-7 (directions) |
| 4 | swap | Swap with teammate | 0-7 (directions) |
| 5 | put | Give items to adjacent agent | 0-7 (directions) |
| 6 | plant_lantern | Plant lantern | 0-7 (directions) |
| 7 | plant_resource | Plant wheat/tree | 0-3 wheat, 4-7 tree |
| 8 | build | Build structure | 0-27 (building index) |
| 9 | orient | Change orientation | 0-7 (directions) |
| 10 | set_rally_point | Set building rally point | 0-7 (directions) |

### Direction Arguments

| Arg | Direction | Delta (x, y) |
|-----|-----------|--------------|
| 0 | North | (0, -1) |
| 1 | South | (0, +1) |
| 2 | West | (-1, 0) |
| 3 | East | (+1, 0) |
| 4 | Northwest | (-1, -1) |
| 5 | Northeast | (+1, -1) |
| 6 | Southwest | (-1, +1) |
| 7 | Southeast | (+1, +1) |

### Common Action Values

| Action | Verb | Arg | Value |
|--------|------|-----|-------|
| Noop | 0 | 0 | 0 |
| Move North | 1 | 0 | 28 |
| Move South | 1 | 1 | 29 |
| Attack North | 2 | 0 | 56 |
| Use North | 3 | 0 | 84 |
| Build House | 8 | 0 | 224 |

See `docs/action_space.md` for complete action documentation.

## Info Dictionary

The info dictionary returned by `step()` and `reset()` is currently empty:

```python
info = {"agent_0": {}, "agent_1": {}, ...}
```

Future versions may include per-agent statistics.

## PufferLib Integration

The environment is designed for high-performance training with PufferLib.

### Direct PufferLib Usage

```python
import pufferlib
from pufferlib import vector as pvector
from tribal_village_env import TribalVillageEnv

# Create vectorized environments
def env_creator(cfg=None, buf=None, seed=None):
    config = cfg or {}
    env = TribalVillageEnv(config=config)
    pufferlib.set_buffers(env, buf)
    return env

vecenv = pvector.make(
    env_creator,
    num_envs=64,
    num_workers=4,
    backend=pvector.Multiprocessing,
)

# Use with PufferLib trainer
from pufferlib import pufferl
trainer = pufferl.PuffeRL(train_args, vecenv, network)
```

### CoGames Training

The recommended way to train is through the CoGames integration:

```bash
# Basic training
tribalcog train --steps 1000000

# With parallel environments
tribalcog train --steps 1000000 --parallel-envs 64 --num-workers 8
```

### Policy Classes

The package includes a default PufferLib-compatible policy:

```python
from tribal_village_env.cogames.policy import TribalVillagePufferPolicy, TribalPolicyEnvInfo

# Create policy environment info
policy_env_info = TribalPolicyEnvInfo(
    observation_space=env.single_observation_space,
    action_space=env.single_action_space,
    num_agents=env.num_agents,
)

# Create policy
policy = TribalVillagePufferPolicy(policy_env_info, hidden_size=256)

# Get network for training
network = policy.network()
```

## Package Exports

```python
from tribal_village_env import (
    TribalVillageEnv,           # Main environment class
    make_tribal_village_env,    # Factory function
    ensure_nim_library_current, # Build utility
)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TRIBAL_VECTOR_BACKEND` | Vector backend (`"serial"` or `"multiprocessing"`) |
| `TV_REPLAY_DIR` | Directory for replay files |
| `TV_REPLAY_PATH` | Explicit replay file path |

## Common Patterns

### Random Agent Loop

```python
from tribal_village_env import make_tribal_village_env

env = make_tribal_village_env(config={"max_steps": 1000})
obs, info = env.reset()

total_reward = 0
done = False
while not done:
    actions = {agent: env.single_action_space.sample() for agent in env.agents}
    obs, rewards, terminated, truncated, info = env.step(actions)
    total_reward += sum(rewards.values())
    done = any(terminated.values()) or any(truncated.values())

env.close()
print(f"Total reward: {total_reward}")
```

### Rendering to Video

```python
import imageio
from tribal_village_env import make_tribal_village_env

env = make_tribal_village_env(config={"render_mode": "rgb_array", "render_scale": 4})
obs, _ = env.reset()

frames = []
for _ in range(200):
    frame = env.render()
    frames.append(frame)
    actions = {agent: env.single_action_space.sample() for agent in env.agents}
    obs, _, terminated, truncated, _ = env.step(actions)
    if any(terminated.values()) or any(truncated.values()):
        break

env.close()
imageio.mimsave("episode.mp4", frames, fps=30)
```

### Custom Reward Configuration

```python
from tribal_village_env import make_tribal_village_env

# Economy-focused training
env = make_tribal_village_env(config={
    "max_steps": 5000,
    "heart_reward": 1.0,
    "ore_reward": 0.1,
    "bar_reward": 0.5,
    "wood_reward": 0.1,
    "survival_penalty": -0.005,
})
```

## Reference Files

- `tribal_village_env/environment.py`: Main environment implementation
- `tribal_village_env/cogames/train.py`: PufferLib training loop
- `tribal_village_env/cogames/policy.py`: Policy classes
- `docs/observation_space.md`: Observation layer details
- `docs/action_space.md`: Action encoding details
- `docs/configuration.md`: Full configuration reference
