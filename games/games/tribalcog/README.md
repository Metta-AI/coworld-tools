# Tribal Village

Tribal Village is the Tribal Cog game package in `Metta-AI/games`: a native Nim simulation with a Python/PufferLib wrapper and CoGames training hooks. Teams gather resources, craft items, build structures, train military units, research technologies, and compete across Age of Empires II-inspired victory conditions.

The package now supports both standalone CoGames/PufferLib use and a container-first Coworld runtime. The Coworld shape lives beside the native package: `coworld_manifest.json`, `Dockerfile`, `player/Dockerfile`, and `tribal_village_env/coworld/`.

<img width="2932" height="1578" alt="Tribal Village screenshot" src="https://github.com/user-attachments/assets/b1736191-ff85-48fa-b5cf-f47e441fd118" />

## Installation

**Requirements:** Python 3.11 or 3.12 for the package, Python 3.12 in the root `games` workspace, Nim 2.2.6 via `nimby`, and OpenGL for the GUI.

```bash
# 1. Install Nim with nimby. The Python CLI can also bootstrap this on demand.
# Pick the suffix for your platform: nimby-Linux-X64, nimby-macOS-ARM64, or nimby-macOS-X64.
curl -L https://github.com/treeform/nimby/releases/download/0.1.11/nimby-macOS-ARM64 -o ./nimby
chmod +x ./nimby
./nimby use 2.2.6
./nimby sync -g nimby.lock

# 2. Install Python package
pip install -e .
```

## Quickstart

```bash
# Play interactively (builds Nim library if needed)
tribalcog play

# Run with random actions (text mode)
tribalcog play --render ansi --random-actions --steps 100

# Run from the root Metta-AI/games uv workspace
uv run --package tribalcog tribalcog play --render ansi --steps 100

# Train with CoGames/PufferLib
pip install -e .[cogames]
tribalcog train --steps 1000000 --parallel-envs 8 --num-workers 4

# Run as a Coworld game server
COGAME_CONFIG_URI=file:///tmp/tribalcog-config.json \
COGAME_RESULTS_URI=file:///tmp/tribalcog-results.json \
COGAME_SAVE_REPLAY_URI=file:///tmp/tribalcog-replay.json.z \
tribalcog coworld-server

# Build the optional native Emscripten client served at /clients/wasm/
nimble wasm
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
| [Metta Integration](docs/metta_integration.md) | How Tribal Cog fits `Metta-AI/games`, CoGames, Metta recipes, and future Coworld packaging |
| [Cogame Template Sync](docs/cogame_template.md) | Template upstream and merge guidance |
| [Game Logic](docs/game_logic.md) | Step loop, actions, entities, episode rules |
| [Action Space](docs/action_space.md) | Discrete 308 actions (11 verbs * 28 arguments) |
| [Observation Space](docs/observation_space.md) | 101 layers, 11x11 grid per agent |
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
| [Coworld Play Guide](tribal_village_env/coworld/docs/play_tribalcog.md) | Coworld server, player, certification, and replay workflow |
| [Coworld Rules](tribal_village_env/coworld/docs/rules.md) | Hosted league player slots, scoring, actions, and episode rules |

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
  coworld/                  # Coworld server, reference player, clients, protocol docs
data/                       # Sprites, fonts, UI
coworld_manifest.json       # Hosted Coworld manifest
Dockerfile                  # Game runtime image
player/Dockerfile           # Lightweight reference player image
```

## License

MIT
