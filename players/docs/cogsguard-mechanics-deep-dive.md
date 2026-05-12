# CogsGuard Game Mechanics Deep Dive

A comprehensive analysis of CogsGuard game mechanics from the metta source, focused on strategies that maximize
`aligned.junction.held`.

---

## 1. Game Overview

CogsGuard is a territory-control game where a team of **Cogs** agents compete against automated **Clips** opponents to
control **junctions** on an 88x88 procedurally generated map. The primary objective is maximizing the proportion of
junctions held over time.

**Source:** `packages/cogames/src/cogsguard/` (environment),
`packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/` (scripted agents).

### Objective Stat

The single true objective signal is `aligned.junction.held`:

```
Reward per tick = (junctions_held / total_junctions) / max_steps
```

Every tick an agent earns reward proportional to team-controlled territory. Dense feedback, but credit assignment
remains hard because individual actions don't directly produce reward.

**Source:** `cogsguard_reward_variants.py:19` - `_OBJECTIVE_STAT_KEY = "aligned.junction.held"`

---

## 2. Map and Arena

### Machina1 Layout (COGSGUARD_ARENA)

- **Map size:** 88x88 cells
- **Generator:** `SequentialMachinaArena` with `Compound` configuration
- **Agents:** Default 10 (configurable, max 20)
- **Max steps:** 1000 (basic mission) or 10000 (factory function)

**Source:** `sites.py:43-49` (MACHINA_1), `sites.py:78-99` (make_cogsguard_arena_site)

### Hub Structure

Each hub contains (`sites.py:52-64`):

- Corner bundle: `extractors` (one of each resource type in corners)
- Stations: `aligner_station`, `scrambler_station`, `miner_station`, `scout_station`, `chest`
- Cross distance: 7 cells between hub features

### Map Symbols

| Symbol | Object              |
| ------ | ------------------- |
| `#`    | Wall                |
| `.`    | Empty               |
| `@`    | Agent spawn         |
| `A`    | Aligner station     |
| `X`    | Scrambler station   |
| `M`    | Miner station       |
| `S`    | Scout station       |
| `C`    | Carbon extractor    |
| `O`    | Oxygen extractor    |
| `G`    | Germanium extractor |
| `I`    | Silicon extractor   |
| `J`    | Charger (junction)  |
| `&`    | Hub (hub)           |
| `=`    | Chest               |

---

## 3. Agent Configuration

### Base Stats (`cog.py:13-41`)

| Stat      | Base                  | Notes                                      |
| --------- | --------------------- | ------------------------------------------ |
| HP        | 50 initial, 100 limit | Gear modifiers: Scout +400, Scrambler +200 |
| Energy    | 100 initial, 20 limit | Scout gets +100 limit                      |
| Cargo     | 4 limit               | Miner gets +40                             |
| Influence | 0 limit               | Aligner gets +20                           |
| Heart     | 10 limit              | Universal                                  |
| Gear      | 1 slot                | Only one role at a time                    |

### Regen Rates (per tick, `cog.py:35-37`)

| Resource  | Rate                            |
| --------- | ------------------------------- |
| Energy    | +1                              |
| HP        | -1 (drain outside friendly AOE) |
| Influence | -1 (drain outside friendly AOE) |

### Movement

- **Cost:** 3 energy per move (`cog.py:40`)
- **Actions:** MOVE (N/S/E/W) or REST (noop)
- Moving into an occupied cell triggers interaction (bump mechanic)

---

## 4. Area Control: Junctions

### Junction States

Each junction is one of:

- **Neutral** - unclaimed
- **Cogs-aligned** - controlled by your team
- **Clips-aligned** - controlled by enemy

### AOE Effects (radius 10 cells, `stations.py:303-347`)

**Friendly territory (aligned to actor):**

- Influence: +10 (fully restored to capacity)
- Energy: +100 (fully restored)
- HP: +100 (fully restored)

**Enemy territory:**

- HP: -1 per tick
- Influence: -100 (fully drained)

### Critical Implication

**Aligners cannot capture junctions in enemy territory** because influence is instantly drained to 0. Scramblers must
neutralize nearby enemy junctions first to stop the influence drain before Aligners can advance.

This creates the fundamental **Scrambler-then-Aligner sequencing** that drives team coordination.

### Capturing Mechanics

| Action   | Role Required                             | Cost    | Effect                           |
| -------- | ----------------------------------------- | ------- | -------------------------------- |
| Align    | Aligner (needs aligner gear, 1 influence) | 1 heart | Neutral junction -> Cogs-aligned |
| Scramble | Scrambler (needs scrambler gear)          | 1 heart | Enemy junction -> Neutral        |

**Source:** `stations.py:333-346`

### Deposits

Agents can deposit resources at aligned junctions and hubs (100 of each element capacity). This is how miners feed the
economy from remote extractors.

---

## 5. Role System

### Gear Types and Costs (`stations.py:50-62`)

All gear is acquired at role-specific stations by spending resources from the **collective inventory**:

| Gear      | Primary Cost | Other Costs       | Stat Bonus           |
| --------- | ------------ | ----------------- | -------------------- |
| Aligner   | 3 carbon     | 1 each of O/Ge/Si | +20 influence        |
| Scrambler | 3 oxygen     | 1 each of C/Ge/Si | +200 HP              |
| Miner     | 3 germanium  | 1 each of C/O/Si  | +40 cargo            |
| Scout     | 3 silicon    | 1 each of C/O/Ge  | +400 HP, +100 energy |

**Key insight:** Each gear type requires 6 total resources (3 of one, 1 each of the others). This means the team needs a
steady supply of all four elements.

### Gear Station Mechanics (`stations.py:409-437`)

- `keep_gear`: If agent already has this gear, no-op
- `change_gear`: Clears all gear, deducts collective resources, equips new gear
- Agents can only hold one gear type at a time

### Role Dependencies (Interdependence Chain)

```
Miners -> gather resources -> deposit at aligned buildings
                                      |
                                      v
                            Collective inventory
                                      |
                   +------------------+------------------+
                   |                  |                  |
            Gear stations      Chest (hearts)     Future gear
                   |                  |
                   v                  v
            Scramblers          Aligners
            (neutralize)        (capture)
                   |                  |
                   +-------->---------+
                   Scramble then Align
```

No single role can succeed alone. Miners can't capture territory. Aligners can't enter enemy territory. Scramblers need
hearts from miners' resource deposits.

---

## 6. Resource Economy

### Elements

Four resources mined from extractors in map corners:

| Resource  | Extractor Output | Max Uses | Cooldown  | Notes                            |
| --------- | ---------------- | -------- | --------- | -------------------------------- |
| Carbon    | 2 per use        | 25       | 0         | Time-consuming but easy          |
| Oxygen    | 10 per use       | 5        | 100 ticks | Accumulates over time            |
| Germanium | 2 per use        | 5        | 200 ticks | Rare, benefits from synergy (50) |
| Silicon   | 15 per use       | 10       | 0         | Costs 20 energy input            |

**Source:** `stations.py:122-206`

**Miner bonus:** With miner gear, extractors yield 10x resources (large_amount vs small_amount in `CvCExtractorConfig`,
`stations.py:275-300`).

### Hearts

Hearts are the critical currency for territory control. They're produced at the **chest**:

1. **get_heart handler:** Withdraw existing heart from collective (requires collective has hearts)
2. **make_heart handler:** Convert 1 of each element (C/O/Ge/Si) into 1 heart

**Source:** `stations.py:381-406`

Heart costs:

- Aligning a junction: 1 heart
- Scrambling a junction: 1 heart
- Making a heart: 1 of each element from collective

### Collective Inventory

The team shares a **collective inventory** system:

- Agents deposit resources at aligned junctions/hubs (up to 100 each)
- Gear stations withdraw from collective to equip agents
- Chests convert collective resources into hearts

---

## 7. Clips (Automated Opposition)

Clips are automated opponents without agents. They expand at a configurable rate:

- Neutralize enemy junctions adjacent to Clips territory
- Capture neutral junctions adjacent to Clips territory

This creates constant pressure, forcing Cogs to defend while expanding. Clips territory also projects the same hostile
AOE (HP drain, influence drain) making it dangerous for Cogs agents.

---

## 8. Reward Variants (`cogsguard_reward_variants.py`)

### Available Variants (Stackable)

| Variant        | Effect                                              |
| -------------- | --------------------------------------------------- |
| `objective`    | No-op marker, keeps default `aligned.junction.held` |
| `no_objective` | Disables `aligned.junction.held` reward             |
| `milestones`   | Shaped rewards for junction alignment/scrambling    |
| `credit`       | Dense shaping for precursor behaviors               |

### Milestone Weights

| Signal                          | Weight | Cap                  |
| ------------------------------- | ------ | -------------------- |
| `aligned.junction` (collective) | 1.0    | 1.0 \* max_junctions |
| `junction.scrambled_by_agent`   | 0.5    | 0.5 \* max_junctions |
| `junction.aligned_by_agent`     | 1.0    | 1.0 \* max_junctions |

### Credit Shaping Weights

| Signal                   | Weight | Cap |
| ------------------------ | ------ | --- |
| `heart.gained`           | 0.05   | 0.5 |
| `aligner.gained`         | 0.2    | 0.4 |
| `scrambler.gained`       | 0.2    | 0.4 |
| Element gained (each)    | 0.001  | 0.1 |
| Element deposited (each) | 0.002  | 0.2 |

---

## 9. Scripted Agent Strategies

### Policy Architecture (`policy.py`)

The scripted agent uses a **vibe-based state machine**:

1. **default** vibe: noop (wait for assignment)
2. **gear** vibe: Smart coordinator picks a role, changes vibe
3. **role** vibe (scout/miner/aligner/scrambler): Get gear if needed, then execute role behavior
4. **heart** vibe: noop

### Smart Role Coordinator (`policy.py:128-356`)

Shared coordinator aggregates team state and assigns roles:

**Priority logic** (`choose_role`, `policy.py:278-311`):

1. If hub/chest unknown -> Scout (need exploration)
2. If no scouts -> Scout
3. If no miners -> Miner
4. If no known junctions -> Scout
5. If no scramblers -> Scrambler
6. If no aligners -> Aligner
7. If clips junctions exist and scramblers <= aligners -> Scrambler
8. If neutral junctions exist -> Aligner
9. If structures_seen < 10 -> Scout
10. Default -> Miner

**Role switch cooldown:** 40 steps (`SMART_ROLE_SWITCH_COOLDOWN`)

### Default Team Composition

URI defaults (`policy.py:1394`): `scrambler=1, miner=4` plus remaining agents on `gear` vibe (smart selection).

### Generalist Policy (`policy.py:1623-1869`)

`CogsguardGeneralistImpl` dynamically switches roles without vibe changes:

- Early game (< 80 steps): Scout if hub unknown or structures < 6
- Target role counts: Scout(1-2), Miner(max(4, N/2)), Scrambler(1-2), Aligner(1-2)
- Priority order for deficits: Scrambler > Aligner > Scout > Miner

### Wombo Policy (`policy.py:1871-1935`)

`CogsguardWomboImpl` prioritizes getting 2+ aligned junctions fast:

- Pushes 2 scouts, 2 scramblers, 2 aligners until TARGET_ALIGNED_JUNCTIONS reached
- Keeps minimum 4 miners for economy

---

## 10. Role-Specific Strategies

### Scout (`scout.py`)

- **Goal:** Explore map, discover structures
- **Strategy:** Frontier-based exploration (BFS for unexplored cells), 25-step persistence per direction
- **Gear bonus:** +400 HP, +100 energy = survives enemy territory, covers more ground

### Miner (`miner.py`)

- **Goal:** Gather resources, deposit at aligned buildings
- **Strategy:**
  - HP-aware: calculates safe operating distance based on HP and drain rate
  - Prefers extractors near aligned buildings (shorter/safer routes)
  - Deposits at nearest aligned building (hub or cogs-aligned junction)
  - Each miner prefers a different resource type (spreads across 4 elements)
  - Without gear: still mines (at 1/10 rate), checks for gear on each deposit cycle
- **Key constants:** Move cost 3 energy, HP drain 1/step outside AOE, enemy AOE adds +1 drain

### Scrambler (`scrambler.py`)

- **Goal:** Neutralize enemy (clips) junctions
- **Strategy:**
  - Finds closest clips-aligned junction
  - Needs scrambler gear + 1 heart
  - After neutralizing enough junctions, **switches to aligner gear** to capture them
    (`SCRAMBLE_TO_ALIGN_THRESHOLD = 1`)
  - Retry failed scrambles up to 3 times
  - HP-aware: returns to hub when HP gets low (12 HP buffer)
  - Multiple scramblers coordinate via SmartRoleCoordinator to target different junctions
- **Scrambler gear priority:** First 25 steps, non-scramblers yield gear station access to scramblers

### Aligner (`aligner.py`)

- **Goal:** Capture neutral junctions for the team
- **Strategy:**
  - Needs aligner gear + 1 heart + 1 influence
  - Targets neutral junctions (not enemy - influence would drain)
  - Prioritizes recently-scrambled junctions via coordinator
  - 40-step timeout on waiting for hearts, then explores instead
  - Multiple aligners coordinate to target different junctions
  - HP-aware: returns to hub at low HP

---

## 11. Strategies to Maximize `aligned.junction.held`

### Critical Path

1. **Early game (steps 0-100):** Scout to discover hub, chest, stations, extractors, and junction positions
2. **Economy bootstrap (steps 50-300):** Miners gather resources, deposit at hub; collective builds up elements for gear
   and hearts
3. **Gear up (steps 100-200):** Scrambler(s) get gear first (25-step priority window), then aligners/miners
4. **Territory push (steps 200+):** Scramblers neutralize clips junctions -> Aligners capture them -> Miners deposit at
   captured junctions to extend economy reach
5. **Defend and expand:** Maintain territory (AOE heals defenders), continue pushing outward

### Key Strategic Insights

1. **Scrambler-first is essential.** Scramblers must clear enemy territory before aligners can operate. The 25-step gear
   priority reflects this.

2. **Hearts are the bottleneck.** Each junction capture/disruption costs 1 heart. Hearts require 1 of each element. The
   entire economy must flow: mine -> deposit -> make hearts -> capture territory.

3. **Territory compounds.** Each captured junction provides healing AOE, making nearby operations safer. Captured
   junctions also accept deposits, shortening miner routes. More territory = faster economy = more territory.

4. **Position matters.** Agents within friendly AOE (10-cell radius) get full HP/energy/influence restore every tick.
   Agents in enemy AOE lose 1 HP/tick and all influence. Operating near friendly territory is dramatically more
   efficient.

5. **Miners deposit at nearest aligned building.** Captured junctions become deposit points, creating shorter mining
   loops and increasing resource throughput.

6. **Team composition should adapt.** Early: more scouts and miners. Mid-game: scramblers + aligners for the push. Late:
   maintain miners for heart production, fewer scouts needed.

7. **Scrambler-to-Aligner transition.** The scripted scrambler switches to aligner gear after neutralizing 1+ junctions,
   enabling rapid capture of freshly-neutralized territory.

8. **Clips expansion pressure.** Clips automatically capture adjacent neutral junctions. Leaving neutral junctions
   between your territory and clips means clips will recapture them. Capture quickly or defend borders.

### Optimal Team Composition (10 agents)

Based on the scripted agent defaults and generalist logic:

- **4 Miners:** Sustain the economy (resource gathering is rate-limiting)
- **1-2 Scramblers:** Clear enemy territory (transition to aligner after)
- **1-2 Aligners:** Capture neutral junctions
- **1-2 Scouts:** Map discovery (fewer needed after early game)
- **Remaining:** Smart-selected based on game state

### Resource Priority

Germanium is the scarcest resource (2 output, 200-tick cooldown, only 5 uses) but is needed for all gear types and
hearts. Carbon is most abundant (25 uses, no cooldown). A balanced team should prioritize germanium extraction
efficiency (synergy bonus with multiple miners).

---

## 12. Source File Reference

### Core Game Implementation

- `packages/cogames/src/cogsguard/cog.py` - Agent configuration
- `packages/cogames/src/cogsguard/stations.py` - Stations, junctions, gear, extractors
- `packages/cogames/src/cogsguard/sites.py` - Map/arena definitions
- `packages/cogames/src/cogsguard/missions.py` - Mission definitions
- `packages/cogames/src/cogsguard/cogsguard_reward_variants.py` - Reward shaping

### Specifications

- `docs/specs/0009-cogsguard.md` - Core design spec
- `docs/specs/0012-smart-gear-meta-role.md` - Smart role selection spec
- `docs/specs/0019-cogsguard-batteries-included.md` - Training onboarding spec
- `packages/cogames/MISSION.md` - In-universe mission briefing

### Scripted Agent Implementation

- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/policy.py` - Main policy + coordinator
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/types.py` - State types
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/miner.py` - Miner role
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/scout.py` - Scout role
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/aligner.py` - Aligner role
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/scrambler.py` - Scrambler role
- `packages/cogames-agents/src/cogames_agents/policy/scripted_agent/cogsguard/roles.py` - Single-role policies
