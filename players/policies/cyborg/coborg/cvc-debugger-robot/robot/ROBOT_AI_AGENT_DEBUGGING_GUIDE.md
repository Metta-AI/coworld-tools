# ROBOT AI Coding Agent Debugging Guide

How to use the robot policy's observability tooling and test games to diagnose, verify, and improve cog agent behavior.

## Architecture at a Glance

```
cogames play CLI
  └── RobotPolicy (multi-agent)
        └── RobotAgent × N (one per cog)
              ├── PERCEIVE  → parse_observation()
              ├── UPDATE    → SpatialMemory
              ├── SNAPSHOT  → WorldSnapshot
              ├── DECIDE    → RobotBrain → MacroCommand
              ├── EXECUTE   → Navigator → action_name
              ├── RECORD    → BlackBox (ring buffer)
              └── OBSERVE   → ObservabilityHub → WebSocket → Dashboard
```

Key files:

| File | Purpose |
|---|---|
| `robot/policy.py` | Control loop — runs one PERCEIVE→DECIDE→EXECUTE cycle per tick |
| `robot/brain.py` | Decision engine — role-locked strategy producing `MacroCommand`s |
| `robot/pathfinding.py` | Navigator — A*, stuck detection, bump interaction |
| `robot/memory.py` | `SpatialMemory`, `SelfState`, `GameClock` |
| `robot/state.py` | `WorldSnapshot` builder + `to_dict()` / `to_prompt()` |
| `robot/perception.py` | Raw observation token parser |
| `robot/blackbox.py` | Per-agent ring buffer for tick-level telemetry |
| `robot/observability.py` | FastAPI server, WebSocket broadcasting, dashboard |
| `robot/roster.py` | Draft negotiation and team composition |
| `robot/launcher.py` | Standalone debugger server (start UI, then launch game from browser) |

---

## 1. Running Test Games

### Basic Command

```bash
ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000
```

This runs the **tournament environment** — an 88×88 Machina-1 map with 8 cogs, 10,000 ticks, clips ships in all four corners, and the full gear/junction/territory ruleset. Both live tournaments (`beta-cvc` freeplay and `beta-teams-tiny-fixed` team) use this exact configuration.

| Flag | Meaning |
|---|---|
| `-m machina_1` | Mission/map — use `machina_1` to match tournament config (88×88, clips, gear) |
| `-p class=robot.RobotPolicy` | Use the robot policy for team 1 |
| `-s 1000` | Run for 10,000 ticks (tournament default) |
| `-c 4` | 8 cogs (tournament default) |
| `--seed 42` | Deterministic RNG seed for reproducibility |
| `-r log` | Render mode: `log` (metrics only), `unicode` (terminal), `gui` (MettaScope) |
| `-v talk` | Apply variant modifier (e.g. enable talk channel) |

### With Debug Logging

Prefix with `ROBOT_DEBUG=1` to enable console trace output and the live dashboard:

```bash
ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000
```

This does two things:
1. Prints per-tick decision traces to stdout (see [section 2](#2-reading-debug-traces))
2. Starts the observability dashboard at `http://localhost:8777` (see [section 3](#3-live-dashboard))

### Standalone Launcher (UI-first)

Start the dashboard server first, then launch games from the browser:

```bash
python robot/launcher.py --port 8777
```

The browser opens automatically. Click "Launch Game" in the UI to configure map, steps, seed, and start the simulation.

### Choosing Step Counts

| Purpose | Steps | Why |
|---|---|---|
| Role adoption smoke test | 15-30 | Verify draft negotiation + gear equip |
| Single-behavior check | 80-200 | Enough for one mine→deposit or heart→scramble cycle |
| Full lifecycle test | 500-1000 | Multiple cycles, hub returns, territory expansion |
| Mid-game strategy | 2000-4000 | Junction control, clips pressure, resource economy |
| Tournament-length | 1000 | Full match — use to test endurance and late-game |

### Seed Selection

Seeds produce deterministic map layouts and spawn positions. When debugging:

- **Keep the same seed** when iterating on a fix to compare apples-to-apples.
- **Try 3+ different seeds** after a fix lands to confirm it generalizes.
- **Document seeds** that reproduce specific failure modes (e.g. "seed 7 spawns scrambler far from enemy territory").

---

## 2. Reading Debug Traces

When `ROBOT_DEBUG=1` is set, every agent prints a one-line trace per tick after the draft phase:

```
  [A0 t30] pos=(5, 12) cargo={'ore': 40} cmd=NAVIGATE_TO:depositing d=3 target=(5, 9)
  [A1 t30] pos=(-8, 4) gear=aligner HEART cmd=NAVIGATE_TO:capturing junction d=7 target=(-15, 4) tags=['junction', 'neutral']
  [A2 t30] pos=(3, -6) gear=scrambler cmd=EXPLORE:in enemy aoe, searching for junction t30
```

### Trace Format

```
[A{agent_id} t{tick}] pos={position} {label} cmd={kind}:{reason} target={target}{extra}
```

| Field | Source | What to look for |
|---|---|---|
| `agent_id` | `self._agent_id` | Filter by agent to isolate one cog's behavior |
| `tick` | `self._clock.tick` | Correlate with game phase (draft ends at tick 14) |
| `pos` | `snapshot.position` | Ground truth position from `local_position` token |
| `label` | `cargo=` (miner) or `gear=` (others) | `HEART` suffix means agent is carrying a heart |
| `cmd` | `MacroCommand.kind` | `NAVIGATE_TO`, `EXPLORE`, `FLEE` |
| `reason` | `MacroCommand.reason` | The "why" — human-readable, includes dynamic values |
| `target` | `MacroCommand.target` | `(row, col)` destination, or `None` for EXPLORE |
| `extra` | Tags / ON_TARGET | `ON_TARGET!` means agent is already at its destination |

### What to Grep For

```bash
# All decisions for agent 2
ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000 2>&1 | grep '\[A2'

# All EXPLORE commands (stuck / searching)
... | grep 'cmd=EXPLORE'

# Congestion events
... | grep 'CONGESTION'

# Heart-related activity
... | grep 'HEART\|heart'

# Position oscillation (same pos appearing repeatedly)
... | grep '\[A1' | awk '{print $2, $3}' | uniq -c | sort -rn | head
```

### Diagnosing Common Problems

| Symptom in Trace | Likely Cause | Where to Look |
|---|---|---|
| Same `cmd` reason repeating > 15 ticks | Congestion timeout about to fire | `brain.py` `CONGESTION_TIMEOUT`, check if `reason` string is static |
| `ON_TARGET!` but no state change | Agent on target but interaction failing | `pathfinding.py` bump logic, check `BUMP_FAIL_THRESHOLD` |
| Position not changing despite `NAVIGATE_TO` | Stuck detection should trigger | `pathfinding.py` `_is_repeat`, `RECENT_ACTION_WINDOW` |
| `gear=None` after tick 30 | Failed to equip gear | Check if gear station is in `nearby_entities`, verify position ground truth |
| `EXPLORE` when enemy junction is known | `_find_enemy_junction` returning `None` | Check junction classification in `state.py` `_classify_junctions` |
| Oscillating between two positions | Anti-repeat logic + pathfinding conflict | `pathfinding.py` `_emit`, navigator state |
| `hub empty, exploring` repeated | Hub has no resources for hearts | Economic bottleneck — check other agents' deposit behavior |

---

## 3. Live Dashboard

The observability dashboard at `http://localhost:8777` provides real-time visualization.

### What it Shows

- **Agent cards**: One per cog with role, gear, HP, energy, cargo, position, current command
- **Map view**: Walls, entities, territory, agent positions, navigation paths
- **Tick timeline**: Scrub through past ticks to replay decision history
- **Brain state panel**: Internal counters from `brain.debug_state()`:
  - `deposit_count` — total resource deposits
  - `junctions_captured` / `junctions_scrambled`
  - `congestion_ticks` — how close to `CONGESTION_TIMEOUT`
  - `last_cmd_reason` — what the brain decided and why
  - `heart_cooldown` — ticks remaining before next heart pickup
- **Memory stats**: Entity count, wall count, visited cells, territory coverage
- **Navigation path length**: Current A* path distance

### API Endpoints (for Programmatic Access)

| Endpoint | Method | Returns |
|---|---|---|
| `/api/status` | GET | Game state, tick, agent count, config |
| `/api/state` | GET | Latest tick data for all agents |
| `/api/history/{agent_id}?n=200` | GET | Last N ticks for one agent |
| `/api/map/{agent_id}` | GET | Spatial memory grid (walls, entities, territory) |
| `/api/maps` | GET | All agent maps + coordinate offsets |
| `/ws` | WebSocket | Real-time tick stream |

### Using the API from an AI Agent

```bash
# Get current state of all agents
curl -s http://localhost:8777/api/state | python -m json.tool

# Get last 50 ticks for agent 0
curl -s 'http://localhost:8777/api/history/0?n=50' | python -m json.tool

# Check if game is still running
curl -s http://localhost:8777/api/status | python -m json.tool
```

---

## 4. Data Structures for Analysis

### WorldSnapshot (`to_dict()`)

Every tick produces a `WorldSnapshot` with these fields. This is what gets pushed to the dashboard and recorded by the BlackBox:

```python
{
  "tick": 45,
  "max_steps": 200,
  "phase": "OPENING",       # OPENING < 200, EARLY < 500, MID < 2000, LATE < 4000, CLOSING
  "position": [5, 12],
  "role": "miner",
  "agent_id": 0,
  "gear": "miner",
  "hp": 85,
  "energy": 120,
  "cargo": {"ore": 30, "crystal": 10},
  "cargo_total": 40,
  "has_heart": false,
  "in_friendly_territory": true,
  "nav_status": "MOVING",    # IDLE, MOVING, STUCK, ARRIVED
  "nav_target": [5, 9],
  "nav_distance": 3,
  "threat_level": "none",    # none, low, medium, high, critical
  "enemy_count": 0,
  "junctions": [
    {"pos": [-15, 4], "owner": "neutral", "dist": 22},
    {"pos": [10, -3], "owner": "own", "dist": 8}
  ],
  "entities_nearby": 5,
  "entities": [
    {"pos": [5, 9], "tags": ["hub", "team:cogs"], "dist": 3, "stale": 0}
  ],
  "teammates": {1: "aligner", 2: "scrambler"},
  "teammate_positions": [[-8, 4], [3, -6]],
  "active_command": "depositing d=3"
}
```

### Brain Debug State

```python
{
  "role": "scrambler",
  "deposit_count": 0,
  "junctions_captured": 0,
  "junctions_scrambled": 1,
  "congestion_ticks": 3,       # resets at 0, fires EXPLORE at 15
  "last_cmd_reason": "scrambling enemy junction d=4",
  "heart_cooldown": 0,
  "explore_reported": false
}
```

### Memory Map Data

```python
{
  "walls": [[1, 0], [1, 1], ...],
  "open": [[0, 0], [0, 1], ...],
  "visited": [[0, 0], [0, 1], ...],
  "territory": [[5, 3, 1], [5, 4, 1], [10, 8, 2], ...],  # [row, col, value] — 1=friendly, 2=enemy
  "entities": [
    {"pos": [5, 9], "type": "hub", "team": "cogs", "stale": 0, "tags": ["hub", "team:cogs"]}
  ],
  "position": [5, 12]
}
```

### SelfState Fields

| Field | Type | Meaning |
|---|---|---|
| `gear` | `str \| None` | Equipped gear type (`miner`, `aligner`, `scrambler`, `None`) |
| `hp` | `int` | Current health points |
| `energy` | `int` | Current energy |
| `cargo` | `dict[str, int]` | Resources carried by name |
| `cargo_total` | `int` | Sum of all cargo values |
| `has_heart` | `bool` | Whether agent has a heart item |
| `hp_delta` | `int` | HP change since last tick (negative = taking damage) |
| `energy_delta` | `int` | Energy change since last tick |

---

## 5. The Debugging Workflow

### Step-by-Step Process

```
1. OBSERVE    — Run a test game, read the traces
2. IDENTIFY   — Find the tick range where behavior deviates from expectation
3. CORRELATE  — Match the trace to the deciding code path in brain.py
4. HYPOTHESIZE — Form a theory about why the wrong branch was taken
5. VERIFY     — Add targeted print() or check dashboard data to confirm
6. FIX        — Edit the relevant decision logic
7. RETEST     — Run with the same seed to confirm the fix
8. GENERALIZE — Run with 3+ different seeds to check for regressions
```

### Example: Scrambler Not Entering Enemy Territory

**1. OBSERVE** — Run a game and watch the scrambler:
```bash
ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000 --seed 2 2>&1 | grep '\[A2'
```

**2. IDENTIFY** — Scrambler oscillates between two positions in neutral territory:
```
[A2 t40] pos=(3, -6) gear=scrambler HEART cmd=EXPLORE:exploring for enemy junctions t40
[A2 t41] pos=(4, -6) gear=scrambler HEART cmd=EXPLORE:exploring for enemy junctions t41
[A2 t42] pos=(3, -6) gear=scrambler HEART cmd=EXPLORE:exploring for enemy junctions t42
```

**3. CORRELATE** — The reason `"exploring for enemy junctions"` comes from the last fallback in `_decide_scrambler()`. This means:
- `_find_enemy_junction()` returned `None`
- `_is_in_enemy_territory()` returned `False`
- `_last_enemy_area` is `None`

**4. HYPOTHESIZE** — The scrambler might not be detecting enemy territory because `_is_in_enemy_territory` is checking the wrong signal.

**5. VERIFY** — Add a temporary print to `_decide_scrambler`:
```python
junctions = [j for j in snapshot.known_junctions if j.owner in ("clips", "enemy")]
print(f"  [A{self._agent_id} DEBUG] enemy junctions={len(junctions)}, "
      f"hp_delta={snapshot.self_state.hp_delta}, "
      f"in_friendly={snapshot.in_friendly_territory}")
```

**6. FIX** — Update the detection logic based on findings.

**7-8. RETEST** — Same seed first, then others:
```bash
for seed in 2 7 13 42 99; do
  echo "=== Seed $seed ==="
  ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000 --seed $seed 2>&1 | grep '\[A2.*scrambl'
done
```

---

## 6. Important Constants and Thresholds

These values in `brain.py` control behavior. When tuning agent behavior, these are the primary knobs:

| Constant | Value | Effect |
|---|---|---|
| `EXPLORE_PHASE_END` | 50 | Ticks of initial exploration before role-focused behavior |
| `CARGO_DEPOSIT_THRESHOLD` | 40 | Cargo level that triggers miner return to hub |
| `CONGESTION_TIMEOUT` | 15 | Ticks of same command before forced EXPLORE |
| `HEART_COOLDOWN_TICKS` | 10 | Aligner wait after using a heart (scramblers: 0) |
| `JUNCTION_AOE_RANGE` | 10 | Manhattan distance defining "within enemy AOE" |
| `DRAFT_DEADLINE` | 14 | Tick when role negotiation finalizes |

In `pathfinding.py`:

| Constant | Value | Effect |
|---|---|---|
| `BUMP_FAIL_THRESHOLD` | 8 | Failed bumps before abandoning a target |
| `RECENT_ACTION_WINDOW` | 2 | Ticks of recent action memory for anti-repeat |

---

## 7. Role-Specific Behavior Checklist

When verifying agent behavior, check these role-specific requirements:

### Miner
- [ ] Equips miner gear from gear station
- [ ] Navigates to extractors in **friendly territory only**
- [ ] Bumps into extractor **4 consecutive times** to fill cargo (40 units)
- [ ] Returns to hub to deposit when cargo >= `CARGO_DEPOSIT_THRESHOLD`
- [ ] Deposits successfully (cargo goes to 0 after hub interaction)
- [ ] Does not mine in neutral or enemy territory

### Aligner
- [ ] Equips aligner gear from gear station
- [ ] Acquires heart from hub (costs 28 resources total)
- [ ] Navigates to neutral junctions
- [ ] Captures junction (changes owner to "own")
- [ ] Returns to hub for another heart after capture
- [ ] Waits `HEART_COOLDOWN_TICKS` between heart uses

### Scrambler
- [ ] Equips scrambler gear from gear station
- [ ] Acquires heart from hub
- [ ] Navigates toward enemy territory (not column-by-column)
- [ ] Uses `_is_in_enemy_territory` (territory label 2 + junction proximity + HP drain) to detect enemy zones
- [ ] Finds and neutralizes enemy junctions
- [ ] Returns to hub for another heart after scrambling (no cooldown)
- [ ] Remembers `_last_enemy_area` for efficient return trips
- [ ] Does not oscillate in neutral territory

---

## 8. Key Observation Tokens

The agent perceives the world through observation tokens. Understanding what they report is critical for diagnosing perception issues.

| Token | What It Reports | Gotchas |
|---|---|---|
| `local_position` | Ground truth `(row, col)` of the agent | Always trust this over inferred movement |
| `last_action_move` | Whether the last action was a move **type** | Does NOT mean the move succeeded or position changed |
| `territory:here` + `territory:*` | Territory overlay | `territory:here` labels the current cell and edge tokens reconstruct nearby labels |
| `inventory` | All items the agent carries | Hearts, gear, resources, HP, energy |
| `nearby_entity_*` | Entities within the 13×13 view | Tags identify type and team alignment |

### Territory Observation Interpretation

The territory observation surface reports:
- `territory:here` for the current cell
- `territory:north`, `territory:south`, `territory:east`, and `territory:west` edge tokens for visible territory boundaries

The robot reconstructs nearby territory labels with the same mapping as before:
- `1` = **friendly** territory
- `2` = **enemy** territory
- `0` = **neutral**

The robot policy uses these values to:
- Determine if the agent is in friendly territory (affects threat assessment, mining decisions)
- Detect enemy territory directly (scramblers can navigate toward enemy territory without relying solely on junction proximity)
- Guide flee behavior (navigate toward cells with value 1)

---

## 8b. Inter-Agent Talk Protocol

Agents share tactical intel over the 140-character talk channel. Messages use compact prefixes:

| Prefix | When Sent | Payload Format | Example |
|---|---|---|---|
| `draft:` | Tick 0 | `draft:{role}` | `draft:miner` |
| `switch:` | During draft | `switch:{role}` | `switch:aligner` |
| `role:` | Tick 14 (deadline) | `role:{role}` | `role:scrambler` |
| `report:` | Tick 51 (post-explore) | Junction/extractor/hub positions | `report:r:miner,jo@-14,-1,jn@-15,4,9ext,hub@3/0,...` |
| `intel:` | After deposit/heart use, periodic | Hub + extractor positions + deposit totals | `intel:hub@2/-1,cX@-5/3,oX@-8/2,low:carbon,d:c0/o40/g120/s0,...` |
| `need:` | When hub starved (<7 of any element) | Starved resource + known extractor locations | `need:oxygen,oX@-17/-2,dep:c:40,o:0,...` |

### Intel Message Fields

| Token | Meaning |
|---|---|
| `hub@r/c` | Hub position (row/col) |
| `cX@r/c` | Carbon extractor at (r,c) |
| `oX@r/c` | Oxygen extractor at (r,c) |
| `gX@r/c` | Germanium extractor at (r,c) |
| `sX@r/c` | Silicon extractor at (r,c) |
| `low:{element}` | Hub is below 7 of this element (can't craft hearts) |
| `d:c0/o40/g120/s0` | Deposit totals per element (carbon/oxygen/germanium/silicon) |
| `jo@r,c` / `jn@r,c` / `je@r,c` | Junction position: own/neutral/enemy |

### How Intel Is Consumed

- **`_find_hub(snapshot)`** checks own observations first, falls back to `snapshot.shared_hub` from teammate broadcasts
- **`_find_shared_extractor(snapshot, resource)`** searches teammate-reported extractor positions for a specific or any resource
- **`_choose_mining_target(ss, snapshot)`** prioritizes teammate `need:` alerts over round-robin when cargo is empty
- **`TeammateMemory`** parses `intel:` and `need:` messages automatically, pruning stale data (>200 ticks for extractors, >100 ticks for needs)

---

## 9. Adding Temporary Debug Prints

When investigating specific behavior, add targeted prints inside decision methods. Follow this pattern to keep output parseable:

```python
# In brain.py, inside a decision method:
print(f"  [A{self._agent_id} DEBUG] {description}: {values}")
```

Prefix with `  [A{id} DEBUG]` so you can grep for them and they align with standard trace output. Remove these after the investigation.

### Useful Debug Points

**Miner not depositing:**
```python
# In _decide_miner, before the deposit check:
print(f"  [A{self._agent_id} DEBUG] cargo_check: total={ss.cargo_total}, "
      f"threshold={CARGO_DEPOSIT_THRESHOLD}, any_at_thresh={_any_resource_at_threshold(ss)}")
```

**Scrambler territory detection:**
```python
# In _decide_scrambler, before junction search:
enemy_j = [j for j in snapshot.known_junctions if j.owner in ("clips", "enemy")]
in_enemy_ter = snapshot.is_enemy_territory(snapshot.position)
print(f"  [A{self._agent_id} DEBUG] enemy_junctions={len(enemy_j)}, "
      f"in_enemy_territory={in_enemy_ter}, "
      f"in_enemy_territory={self._is_in_enemy_territory(snapshot)}, "
      f"hp_delta={ss.hp_delta}, last_enemy_area={self._last_enemy_area}")
```

**Navigator stuck detection:**
```python
# In pathfinding.py navigate_to, when dist == 1:
print(f"  [NAV A{self._agent_id} DEBUG] bump attempt: target={target}, "
      f"pos={self._memory.position}, fail_count={self._bump_fail_count}")
```

---

## 10. Verifying Fixes Across Seeds

After making a change, validate it systematically:

```bash
# Quick smoke test — single seed
ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000 --seed 42

# Multi-seed regression check
for seed in 2 7 13 42 99; do
  echo "=== Seed $seed ==="
  ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000 --seed $seed 2>&1 | tail -20
done

# Focus on one role across seeds
for seed in 2 7 13 42 99; do
  echo "=== Seed $seed ==="
  ROBOT_DEBUG=1 cogames play -m machina_1 -c 4 -p class=robot.RobotPolicy -s 1000 --seed $seed 2>&1 | grep '\[A2.*scrambl'
done
```

### What "Working" Looks Like

**Miner lifecycle:**
```
[A0 t20] cmd=NAVIGATE_TO:mining d=4           # heading to extractor
[A0 t24] cmd=NAVIGATE_TO:mining d=0 ON_TARGET! # arrived, bumping
[A0 t28] cmd=NAVIGATE_TO:depositing d=6       # full cargo, going to hub
[A0 t34] cmd=NAVIGATE_TO:mining d=5           # deposited, heading out again
```

**Scrambler lifecycle:**
```
[A2 t15] cmd=NAVIGATE_TO:getting heart d=3     # heading to hub for heart
[A2 t18] cmd=EXPLORE:exploring for enemy junctions t18  # searching
[A2 t30] cmd=EXPLORE:in enemy aoe, searching for junction t30  # HP drain detected
[A2 t35] cmd=NAVIGATE_TO:scrambling enemy junction d=5  # found it
[A2 t40] cmd=NAVIGATE_TO:getting heart d=12    # used heart, returning to hub
```

### What "Broken" Looks Like

**Stuck/oscillating:**
```
[A2 t50] pos=(3, -6) cmd=EXPLORE:exploring for enemy junctions t50
[A2 t51] pos=(4, -6) cmd=EXPLORE:exploring for enemy junctions t51
[A2 t52] pos=(3, -6) cmd=EXPLORE:exploring for enemy junctions t52  # oscillating!
```

**Congestion timeout firing unnecessarily:**
```
[A0 t30] cmd=NAVIGATE_TO:mining
[A0 t31] cmd=NAVIGATE_TO:mining
...                                              # same static reason 15x
[A0 t45] cmd=EXPLORE:congestion break           # forced explore, bad
```
Fix: make the `reason` string dynamic (include distance or tick).

**Agent never equipping gear:**
```
[A1 t30] pos=(2, 5) gear=None cmd=NAVIGATE_TO:gear up d=1  # adjacent but not equipping
[A1 t31] pos=(2, 5) gear=None cmd=NAVIGATE_TO:gear up d=1  # stuck
```
Fix: check `navigate_to` bump logic and position ground truth.

---

## 11. Code Change Workflow

When modifying agent behavior:

1. **Read the relevant decision method** in `brain.py` (e.g. `_decide_miner`, `_decide_scrambler`, `_decide_aligner`)
2. **Understand the `MacroCommand` flow**: `brain.decide()` → `MacroCommand` → `navigator.execute()` → action
3. **Check the constants** at the top of `brain.py` — many behaviors are threshold-driven
4. **Make the change** — prefer adjusting constants or decision order over rewriting pathfinding
5. **Use dynamic reason strings** — always include `d={distance}` or `t{tick}` to prevent `CONGESTION_TIMEOUT`
6. **Run with `ROBOT_DEBUG=1`** and the same seed to verify
7. **Check for regressions** on other roles (a scrambler fix could break miners if shared code changed)

### Anti-patterns to Avoid

- **Static `reason` strings** in `MacroCommand` — these trigger `CONGESTION_TIMEOUT` after 15 identical ticks
- **Trusting `last_action_move`** for position updates — always use `local_position` ground truth
- **Using reconstructed territory labels for enemy detection** — value 1 is friendly, value 2 is enemy, value 0 is neutral
- **Blocking on hub resources** — add a `_hub_wait_ticks` escape hatch
- **Clearing `_last_enemy_area` too eagerly** — scramblers need this memory for return trips

---

## 12. Module Reference

### brain.py — Decision Engine

The entry point is `RobotBrain.decide(snapshot)`. It dispatches to role-specific methods:

- `_decide_miner()` — mine extractors in friendly territory, deposit at hub
- `_decide_aligner()` — capture neutral junctions with hearts
- `_decide_scrambler()` — neutralize enemy junctions with hearts
- `_decide_solo()` — single-agent mode cycling all roles
- `_cmd_gear_station()` — find and navigate to gear/hub (shared setup logic)

Helper methods:
- `_find_nearest(snapshot, type)` — find closest entity by type string
- `_find_nearest_extractor(snapshot)` — find extractor in friendly territory
- `_find_enemy_junction(snapshot)` — find closest enemy/clips junction
- `_is_in_enemy_territory(snapshot)` — junction proximity OR HP drain detection
- `debug_state()` — returns dict of internal counters for dashboard

### pathfinding.py — Navigator

- `execute(command, memory)` — translates `MacroCommand` into an action string
- `navigate_to(target, memory)` — A* pathfinding + stuck detection
- `explore(memory, ...)` — frontier-based exploration
- `_emit(action, pos)` — action filter with anti-repeat logic

### state.py — WorldSnapshot

- `build_snapshot(...)` — assembles full world state from memory (called once per tick)
- `WorldSnapshot.to_dict()` — JSON-serializable format (for dashboard/BlackBox)
- `WorldSnapshot.to_prompt()` — condensed text format (for LLM consumption)
- `_classify_junctions()` — determines junction ownership from entity tags

### blackbox.py — Telemetry

- `BlackBox.record(snapshot, action)` — stores one tick
- `BlackBox.last_n(n)` — retrieves recent ticks
- `BlackBox.dump_json(path)` — exports full history
- `BlackBox.summary()` — condensed narrative string (designed for LLM context)
