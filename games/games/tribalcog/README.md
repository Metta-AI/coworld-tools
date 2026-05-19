# Tribal Village

Multi-agent RL environment in Nim with a Python wrapper (PufferLib compatible). Teams of agents gather resources, craft items, build structures, train military units, research technologies, and compete across multiple victory conditions — inspired by Age of Empires II.

<img width="2932" height="1578" alt="Tribal Village screenshot" src="https://github.com/user-attachments/assets/b1736191-ff85-48fa-b5cf-f47e441fd118" />

## Installation

**Requirements:** Python 3.12+, Nim 2.2.6+ (via nimby), OpenGL

```bash
# 1. Install Nim with nimby
curl -L https://github.com/treeform/nimby/releases/download/0.1.11/nimby-$(uname -s)-$(uname -m) -o ./nimby
chmod +x ./nimby && ./nimby use 2.2.6 && ./nimby sync -g nimby.lock

# 2. Install Python package
pip install -e .
```

## Quickstart

```bash
# Play interactively (builds Nim library if needed)
tribalcog play

# Run with random actions (text mode)
tribalcog play --render ansi --random-actions --steps 100

# Train with CoGames/PufferLib
pip install -e .[cogames]
tribalcog train --steps 1000000 --parallel-envs 8 --num-workers 4
```

**Controls:** Left-click (select), Right-click (command), WASD (move/pan), Space (pause/step), scroll (zoom), Ctrl+0-9 (control groups), Tab (cycle teams), F9 (weather), B (build menu)

## Key Features

- **Victory conditions**: Conquest, Wonder, Relic, King of the Hill, Regicide
- **Tech trees**: Blacksmith upgrades, University research, Castle unique techs per civilization
- **Production system**: Batch training, production queues, per-unit training times, rally points
- **Military commands**: Attack-move, patrol, unit stances, control groups, formations (Line/Box/Staggered)
- **Economy**: AoE2-style market trading, Trade Cog dock-to-dock gold generation, biome resource bonuses
- **Unit mechanics**: Garrisoning, Trebuchet pack/unpack, Monk conversion, Scout exploration, unit upgrades
- **AI system**: Role-based agents (Gatherer/Builder/Fighter) with inter-role coordination, shared threat maps, adaptive difficulty
- **Terrain**: Biome zones, elevation with cliffs/ramps, mud and shallow water, terrain movement speed modifiers
- **AoE2-style UI**: Resource bar, minimap, command panel, unit info, drag-box select, right-click commands, building placement
- **Visual effects**: Weather (rain/wind), water ripples, unit trails, torch flicker, damage numbers, ragdolls, debris, spawn effects

## Python API

```python
from tribal_village_env import TribalVillageEnv

env = TribalVillageEnv(config={
    'max_steps': 10000,
    'render_mode': 'rgb_array',  # or 'ansi'
})
obs, info = env.reset()
obs, reward, terminated, truncated, info = env.step(actions)
```

## Documentation

| Topic | Description |
|-------|-------------|
| [Quickstart](docs/quickstart.md) | Prerequisites, building, running, testing |
| [Cogame Template Sync](docs/cogame_template.md) | Template upstream and merge guidance |
| [Game Logic](docs/game_logic.md) | Step loop, actions, entities, episode rules |
| [Action Space](docs/action_space.md) | Discrete 250 actions (verb * 25 + direction/argument) |
| [Observation Space](docs/observation_space.md) | 84 layers, 11x11 grid per agent |
| [Combat](docs/combat.md) | Combat rules, counters, siege, unit commands |
| [Economy & Respawn](docs/economy_respawn.md) | Inventory, stockpiles, markets, trade, hearts |
| [Victory Conditions](docs/victory_conditions.md) | Conquest, Wonder, Relic, KOTH, Regicide |
| [AI System](docs/ai_system.md) | AI roles, coordination, threat maps, behaviors |
| [Terrain & Biomes](docs/terrain_biomes.md) | Biomes, elevation, cliffs, mud, water depth |
| [World Generation](docs/world_generation.md) | Trading hub, rivers, biomes, spawning |
| [Configuration](docs/configuration.md) | Runtime params, compile-time constants, env vars |
| [Architecture](docs/architecture.md) | System components, module layout, build process |
| [Python API](docs/python_api.md) | Python wrapper, PufferLib integration, examples |
| [CLI & Debugging](docs/cli_and_debugging.md) | CLI usage, debugging flags |
| [Training & Replays](docs/training_and_replays.md) | Training entrypoints, replay setup |
| [Asset Pipeline](docs/asset_pipeline.md) | Asset generation workflow |

See [docs/README.md](docs/README.md) for the complete documentation index.

## Project Structure

```
tribal_village.nim          # Entry point
src/
  environment.nim           # Simulation core
  ai_core.nim              # Built-in AI
  renderer.nim             # Rendering
  ffi.nim                  # C interface for Python
tribal_village_env/         # Python wrapper + CLI
data/                       # Sprites, fonts, UI
```

## License

MIT
