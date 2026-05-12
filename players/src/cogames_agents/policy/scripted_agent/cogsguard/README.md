# CoGsGuard Scripted Agent

A vibe-based multi-agent policy for the Cogs vs Clips arena game.

## Vibe-Based Role System

Agents use **vibes** to determine their behavior dynamically:

| Vibe        | Behavior                                                        |
| ----------- | --------------------------------------------------------------- |
| `default`   | Do nothing (noop) - agent is idle                               |
| `gear`      | Pick a role via the smart/evolutionary coordinator, change vibe |
| `miner`     | Get miner gear if needed, then mine resources                   |
| `scout`     | Get scout gear if needed, then explore the map                  |
| `aligner`   | Get aligner gear if needed, then align junctions to cogs        |
| `scrambler` | Get scrambler gear if needed, then scramble enemy junctions     |
| `heart`     | Do nothing (noop)                                               |

This allows external systems (like training policies) to control agent behavior by setting their vibe.

## Game Rules

### Overview

CoGsGuard is a team-based resource management game where the **Cogs** team competes against the **Clips** team. The Cogs
team uses this scripted policy while Clips can be controlled by another policy or bot.

### Resources

- **Elements**: carbon, oxygen, germanium, silicon (gathered from extractors)
- **Energy**: Required for movement (auto-regenerates near aligned structures)
- **Hearts**: Required for align/scramble actions
- **Influence**: Required for aligning supply depots
- **HP**: Health points

### Key Structures

| Structure                  | Owner             | Function                                                     |
| -------------------------- | ----------------- | ------------------------------------------------------------ |
| **Main Nexus**             | Cogs              | Energy AOE regeneration, resource deposits, heart withdrawal |
| **Supply Depot (Charger)** | Clips (initially) | Can be scrambled (→neutral) then aligned (→cogs)             |
| **Gear Stations**          | Cogs              | Dispense role-specific gear (costs commons resources)        |
| **Extractors**             | Neutral           | Gather element resources (in map corners)                    |

### Gear System

Agents must acquire role-specific gear from gear stations before executing their role. Gear costs are paid from the
**cogs commons** inventory:

| Gear      | Cost                                       | Bonus                  |
| --------- | ------------------------------------------ | ---------------------- |
| Miner     | 3 carbon, 1 oxygen, 1 germanium, 1 silicon | +40 cargo capacity     |
| Scout     | 1 carbon, 1 oxygen, 1 germanium, 3 silicon | +100 energy, +400 HP   |
| Aligner   | 3 carbon, 1 oxygen, 1 germanium, 1 silicon | +20 influence capacity |
| Scrambler | 1 carbon, 3 oxygen, 1 germanium, 1 silicon | +200 HP                |

### Supply Depot Mechanics

- **Align**: Convert neutral depot to cogs-aligned (requires aligner gear + 1 influence + 1 heart)
- **Scramble**: Remove depot's alignment (requires scrambler gear + 1 heart)
- Aligned depots provide energy AOE to their team

## Agent Strategy

### Vibe State Machine

```
┌─────────────┐                    ┌─────────────┐
│   default   │ ◄──────────────────│    heart    │
│   (noop)    │                    │   (noop)    │
└─────────────┘                    └─────────────┘

                    External vibe change
                           │
                           ▼
┌─────────────┐   Pick smart role   ┌───────────────┐
│    gear     │ ──────────────────► │  role vibe    │
│             │    role vibe        │ (miner/scout/ │
└─────────────┘                     │  aligner/     │
                                    │  scrambler)   │
                                    └───────────────┘
                                           │
                                           ▼
                                    ┌─────────────┐     ┌──────────────┐
                                    │  GET_GEAR   │ ──► │ EXECUTE_ROLE │
                                    └─────────────┘     └──────────────┘
```

### Phase System (within role vibes)

When an agent has a role vibe (miner/scout/aligner/scrambler):

1. **GET_GEAR**: Find and bump the role-specific gear station
2. **EXECUTE_ROLE**: Perform role-specific behavior

### Role Behaviors

#### 🔨 Miner

```
1. Find nearest extractor (carbon/oxygen/germanium/silicon chests)
2. Navigate to extractor and extract resources
3. When cargo full (40 capacity), return to supply depot to deposit
4. Repeat
```

#### 🔭 Scout

```
1. Explore the map systematically (high energy allows long-range scouting)
2. Discover structures and resources for team knowledge
3. Patrol map edges to maximize coverage
```

#### 🔗 Aligner

```
1. Get influence from nexus AOE (stand nearby)
2. Get hearts from nexus (bump to withdraw from commons)
3. Find neutral supply depots (after scrambler has neutralized them)
4. Bump depot to align it to cogs
5. Repeat
```

#### 🌀 Scrambler

```
1. Get hearts from nexus or chest
2. Find clips-aligned supply depots (junctions)
3. Bump depot to scramble (remove alignment → neutral)
4. Repeat
```

### Exploration Strategy

Agents explore systematically by cycling through cardinal directions:

```
East (8 steps) → South (8 steps) → West (8 steps) → North (8 steps) → repeat
```

Starting direction is East (where gear stations are typically located in hub maps).

### Resource Flow

```
Extractors ──► Miners ──► Commons ──► Gear Stations ──► Agents
                              │
                              └──► Hearts ──► Aligners/Scramblers
```

## Known Limitations

1. **Aligner Timing**: Aligners often take too long to find their gear stations. By then, the commons may be depleted of
   resources needed for aligner gear.

2. **No Communication**: Agents don't share discovered locations. Each agent must independently explore to find
   structures.

3. **Random Station Placement**: Gear stations are randomly placed around the hub perimeter, making exploration outcomes
   variable.

## Investigations

- [aligned_junction_held_investigation](aligned_junction_held_investigation.md): AOE energy issues blocking junction
  alignment in `aligned.junction.held`.

## Usage

```bash
# Run with the role policy (default: 1 scrambler, 4 miners)
./tools/run.py recipes.experiment.cogsguard.play policy_uri=metta://policy/role

# With limited timesteps and log rendering
./tools/run.py recipes.experiment.cogsguard.play policy_uri=metta://policy/role render=log max_steps=500
```

### Specifying Initial Vibe Counts

You can control how many agents start with each role using URI query parameters:

```bash
# Custom distribution: 4 miners, 2 scramblers, 1 gear (smart role)
./tools/run.py recipes.experiment.cogsguard.play \
    policy_uri="metta://policy/role?miner=4&scrambler=2&gear=1"

# All miners
./tools/run.py recipes.experiment.cogsguard.play \
    policy_uri="metta://policy/role?miner=10"

# Balanced team
./tools/run.py recipes.experiment.cogsguard.play \
    policy_uri="metta://policy/role?miner=3&scout=2&aligner=2&scrambler=3"
```

**Supported vibe parameters:**

| Parameter   | Description                                                                           |
| ----------- | ------------------------------------------------------------------------------------- |
| `miner`     | Number of agents starting as miners                                                   |
| `scout`     | Number of agents starting as scouts                                                   |
| `aligner`   | Number of agents starting as aligners                                                 |
| `scrambler` | Number of agents starting as scramblers                                               |
| `gear`      | Number of agents starting with gear (smart role)                                      |
| `evolution` | Use evolutionary role selection for `gear` agents (aliases: `evolutionary`, `evolve`) |

**Assignment order:** `scrambler → aligner → miner → scout → gear`

Agents are assigned vibes in order by agent ID. Agents beyond the total count specified get no initial target vibe and
start with the `gear` vibe (smart role selection).

**Default counts** (if no params specified): `scrambler=1, miner=4`, remainder `gear`

### Role Cycle / Fixed Mix

If you want a fixed, repeating role pattern by agent index, use `role_cycle` (comma-separated). This is handy for
hardcoding a mix like 3 aligners, 3 miners, 2 scramblers, 2 scouts when running 10 agents.

```bash
# 10 agents: aligner, miner, scrambler, scout repeating (3/3/2/2)
./tools/run.py recipes.experiment.cogsguard.play \
    policy_uri="metta://policy/role?role_cycle=aligner,miner,scrambler,scout" \
    sim.env.game.num_agents=10 \
    sim.env.game.map_builder.instance.spawn_count=10
```

For a one-off explicit ordering, use `role_order` (comma-separated) to list the exact vibes per agent id.

## File Structure

```
cogsguard/
├── __init__.py      # Exports CogsguardPolicy
├── policy.py        # Base agent logic, vibe state machine, navigation
├── types.py         # State definitions (CogsguardAgentState, Role, Phase)
├── miner.py         # Miner role implementation
├── scout.py         # Scout role implementation
├── aligner.py       # Aligner role implementation
├── scrambler.py     # Scrambler role implementation
├── README.md        # This file
└── AGENTS.md        # AI debugging guide
```

## Debug Mode

Set `DEBUG = True` in `policy.py` to enable detailed logging:

```python
DEBUG = True  # Enable debug logging
```

This will print agent vibe transitions, decisions, discoveries, and phase transitions.
