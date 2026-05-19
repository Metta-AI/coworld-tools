# bombercog

Bomberman-style multi-agent deathmatch for the
[MettaGrid](https://github.com/metta-ai/metta/tree/main/packages/mettagrid)
environment.

Agents switch into a `bomb` vibe, drop a bomb by moving into an empty cell, and
flee before the fuse expires. Bombs produce a cross-shaped blast that destroys
crates and damages other agents, blocked by walls and crates. Last cog standing
wins.

See `src/bombercog/rules.md` for the full design contract.

## Quickstart

```bash
# Create a venv and install the package in development mode.
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# Run the tests.
pytest

# Play a single episode. Default: MettaScope GUI.
bombercog-play                                  # base 2-player game, GUI
bombercog-play --variant powerups
bombercog-play --variant four_player --num-agents 4
bombercog-play --render none                    # headless smoke run
bombercog-play --render unicode                 # terminal miniscope
```

The MettaScope window is shipped with the `mettagrid` wheel (native Nim binary
plus atlas), so no extra install step is required. You need an X display (or
WSLg / XQuartz / etc.) for `--render gui`; use `--render none` or
`--render unicode` on headless boxes.

## Variants

| name              | description                                                  |
| ----------------- | ------------------------------------------------------------ |
| `chain_reaction`  | Bombs caught in another bomb's blast detonate.               |
| `four_player`     | 4-agent deathmatch on a larger 13x11 map.                    |
| `kickable_bombs`  | Walking into a bomb pushes it one cell forward.              |
| `powerups`        | Special crates drop `range_up` / `count_up` pickups.         |
| `procedural_map`  | Random 2-player map per episode with a seeded layout.        |

Variants stack — pass `-v name` multiple times on the CLI, or
`mission.with_variants([...])` in Python.

## Programmatic use

```python
from mettagrid.simulator.simulator import Simulator
from bombercog import BombercogMission
import bombercog.variants  # side-effect: registers variants by name

mission = BombercogMission.create(num_agents=2, max_steps=500)
mission = mission.with_variants(["powerups"])
env = mission.make_env()

simulator = Simulator()
sim = simulator.new_simulation(env, seed=42)

while not sim.is_done():
    for i in range(sim.num_agents):
        sim.agent(i).set_action("noop")   # or "move_north", "change_vibe_bomb", ...
    sim.step()
```

To add MettaScope rendering, attach the renderer as an event handler before
creating the simulation:

```python
from mettagrid.renderer.renderer import create_renderer

simulator.add_event_handler(create_renderer("gui", autostart=True))
```

## Dependency versions

This package requires **`mettagrid >= 0.25.5`** for two engine features:

- `PushObjectMutation` (used by the `kickable_bombs` variant), and
- the fix that sets `ctx.target_location` in event dispatch (needed by the
  blast pipeline).

Both shipped in mettagrid 0.25.5.

## Rendering

Bombercog-specific sprites (bomb, crate, explosion, range_up, count_up) have
not yet been upstreamed into the published mettagrid atlas, so MettaScope will
fall back to placeholder tiles for those objects. Agents, walls, and the map
render normally; gameplay and tests are unaffected.

## License

MIT — see [LICENSE](./LICENSE).
