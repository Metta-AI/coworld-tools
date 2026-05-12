# CvC Agent Architecture & Game Rules

See `cogamer/IDENTITY.md` for this cogamer's name, personality, and strategic philosophy.

## Game Rules

### Overview
- **Game**: Cogs vs Clips (CvC) — 2 teams compete on an 88×88 grid for 10,000 steps
- **Teams**: 8 agents per team
- **Scoring**: `score = total_junctions_held_per_step / max_steps` per cog
- **Objective**: Align and hold junctions. More junctions held longer = higher score

### Map Layout
- 88×88 grid with walls, corridors, and open areas
- **Hubs** (1 per team): team spawn point, shared resource storage, gear crafting
- **Junctions**: capturable nodes scattered across the map (neutral → friendly/enemy)
- **Extractors**: resource gathering points for each element type

### Resources
Four elements: **carbon, oxygen, germanium, silicon**
- Mined from extractors, deposited at hub
- Used to craft gear (each role needs different ratios)
- **Hearts**: consumable HP restore items, crafted at hub
- **HP**: health points, depleted by enemy attacks or environmental damage

### Agent Roles
| Role | Purpose | Gear Cost | HP Threshold |
|------|---------|-----------|-------------|
| **Miner** | Harvest resources from extractors | C:1 O:1 G:3 S:1 | 15 |
| **Aligner** | Capture neutral junctions | C:3 O:1 G:1 S:1 | 50 |
| **Scrambler** | Neutralize enemy junctions | C:1 O:3 G:1 S:1 | 30 |
| **Scout** | Explore (rarely used) | C:1 O:1 G:1 S:3 | 30 |

### Junction Mechanics
- **Alignment distance**: 15 Manhattan distance (agent must be within range to align)
- **Hub alignment distance**: 25
- **AoE range**: 10 (junctions affect nearby junctions)
- Junctions form networks: aligned junctions near other friendly junctions strengthen control
- Scramblers neutralize enemy junctions (flips them back to neutral)

### Key Distances & Thresholds
```
JUNCTION_ALIGN_DISTANCE = 15
HUB_ALIGN_DISTANCE = 25
JUNCTION_AOE_RANGE = 10
RETREAT_MARGIN = 15 (HP threshold to retreat)
DEPOSIT_THRESHOLD = 12 (miner deposits at this carry amount)
TARGET_CLAIM_STEPS = 30
EXTRACTOR_MEMORY = 600 steps
```

## Architecture

### Agent Independence (CRITICAL)
**Agents MUST be fully independent.** No shared state between agents. Each agent may run in a separate process. You will not necessarily be playing with copies of yourself.

**NOTHING is shared between agents:**
- `WorldModel()` — per-agent (new instance). Sharing causes 0.00 score.
- `_claims` / `_junctions` — internal to each agent, created in `__init__`
- Each agent runs its own LLM brain independently

**The ONLY way to know about teammates** is via `team_summary` from game observations (positions, roles, inventory). This is game-provided data, not shared state.

### Policy Stack (StatefulPolicyImpl pattern)
```
CvCPolicy (MultiAgentPolicy)
  └─ StatefulAgentPolicy[CvCAgentState]  ← framework-managed, one per agent
       └─ CvCPolicyImpl (StatefulPolicyImpl[CvCAgentState])
            ├─ CvCAgentPolicy (heuristic engine)
            ├─ LLM brain (periodic Claude calls → resource_bias)
            └─ Snapshot logging (periodic state capture)
```

This follows the official cogames agent pattern (see `cogames-agents/docs/creating-scripted-agents.md`):
- **`MultiAgentPolicy`**: Top-level wrapper, creates per-agent policies
- **`StatefulPolicyImpl[S]`**: Per-agent logic, implements `step_with_state(obs, state) -> (Action, state)`
- **`StatefulAgentPolicy[S]`**: Framework glue, wraps impl into AgentPolicy with state lifecycle

### CvCAgentState (dataclass)
All per-agent mutable state:
```python
@dataclass
class CvCAgentState:
    engine: CvCAgentPolicy | None   # Heuristic engine (holds own internal state)
    last_llm_step: int                  # Step of last LLM call
    llm_interval: int                   # Steps between LLM calls (adaptive)
    llm_latencies: list[float]          # Recent LLM call latencies
    resource_bias_from_llm: str | None  # LLM-guided resource priority
    llm_log: list[dict]                 # LLM call history
    snapshot_log: list[dict]            # Game state snapshots
    last_snapshot_step: int             # Step of last snapshot
```

### CvCPolicyImpl (StatefulPolicyImpl)
Per-agent decision logic:
1. Sets `engine._llm_resource_bias` from state (LLM guidance)
2. Calls `engine.step(obs)` → action (heuristic fast path)
3. Periodically calls LLM for `resource_bias` (slow path)
4. Periodically logs game state snapshot

### CvCAgentPolicy (heuristic engine)
Extends `CvcEngine` with:
- `_llm_resource_bias` attribute: set by CvCPolicyImpl, used in `_macro_directive()`
- `_macro_directive()`: returns LLM bias if set, else least-available resource
- `_pressure_budgets()`: phase-based aligner/scrambler allocation
- `_should_retreat()`: extra safety for miners far from hub

### File Layout
```
cvc/
├── cogamer_policy.py          # CvCPolicy + CvCPolicyImpl + CvCAgentState + LLM brain
├── programs.py                # Flat program table (all 32 programs)
├── game_state.py              # GameState adapter wrapping CogletAgentPolicy
└── agent/
    ├── __init__.py            # Barrel file re-exporting all submodules
    ├── main.py                # CvcEngine (heuristic decision tree)
    ├── coglet_policy.py       # CogletAgentPolicy (LLM overrides: resource bias, budgets, retreat)
    ├── roles.py               # Role-specific action logic (miner/aligner/scrambler)
    ├── navigation.py          # Movement, explore patterns, unstick
    ├── targeting.py           # Target selection, claims, sticky targets
    ├── pressure.py            # Role budgets, retreat (delegates to budgets.py)
    ├── junctions.py           # Junction memory, depot lookup
    ├── tick_context.py        # TickContext (per-tick read-only state) + builder
    ├── decisions.py           # Decision pipeline: composable check functions
    ├── budgets.py             # Pure functions: assign_role, pressure budgets, retreat margin
    ├── pathfinding.py         # Pure functions: A* search, oscillation detection
    ├── world_model.py         # WorldModel (per-agent entity memory)
    ├── scoring.py             # Junction/extractor scoring functions
    ├── resources.py           # Deposit/heart/resource logic
    ├── geometry.py            # Manhattan distance, position helpers
    └── types.py               # Constants, KnownEntity
```

### Per-Agent Decision Loop
Each step, CvCPolicyImpl.step_with_state():
1. Set `engine._llm_resource_bias` from LLM state
2. `engine.step(obs)` → action (heuristic engine handles everything)
3. If LLM interval reached → call Claude for new `resource_bias`
4. If log interval reached → capture snapshot

### LLM Brain (Strategic Advisor)
The LLM never picks individual actions — Python handles all real-time decisions. The LLM steers Python heuristics via three soft overrides every ~500 steps:

| Knob | Effect |
|------|--------|
| `resource_bias` | Which element miners prioritize |
| `role` | Override role assignment (null = keep current) |
| `objective` | Macro strategy: `expand`/`defend`/`economy_bootstrap` — adjusts pressure budgets |

**Call cycle:** `summarize` collects context → `_build_analysis_prompt()` builds structured prompt → Claude Sonnet returns JSON → `_parse_analysis()` validates → effects applied to GameState.

- Each agent independently calls Claude Sonnet at adaptive intervals (200-1000 steps)
- Sends: step, HP, hearts, gear, hub resources, team roles, junction counts, stall/oscillation status
- Receives: `{"resource_bias": "...", "role": null|"...", "objective": null|"...", "analysis": "..."}`
- Latency ~2s per call, interval adapts: shrinks if <2s, grows if >5s
- 8 agents × ~20 calls = ~160 API calls per game (consider cost)

### Decision Pipeline (`decisions.py`)
The decision tree is a composable pipeline of check functions. Each check takes `(TickContext, role, engine)` and returns `(Action, summary)` or `None`. First non-None wins:
```
1. hub_camp_heal     — stay at hub until full HP (step ≤ 20)
2. early_retreat     — rush back if low HP (step < 150)
3. wipeout_recovery  — return to hub when dead (HP=0)
4. retreat           — retreat when HP dangerously low
5. oscillation_unstick — break extractor oscillation
6. stall_unstick     — break position stall (12+ steps)
7. emergency_mine    — ungeared non-miners help mine when broke
8. gear_delay        — delay aligner gear in early game
9. gear_acquisition  — get role gear or mine to fund it
10. role_dispatch    — miner/aligner/scrambler action
```
`TickContext` is built once per tick with all computed state (position, junctions, AOE flags, etc.), eliminating repeated queries.

### Pressure Budgets (role allocation)
Controls how many agents become aligners vs miners vs scramblers:
```python
step < 10:   aligners=2, scramblers=0  (bootstrap)
step < 300:  aligners=5, scramblers=0  (early expansion)
step >= 300: aligners=4, scramblers=1  (sustained play)
```

## Commands

```bash
# Play locally (with LLM if ANTHROPIC_API_KEY is set)
cogames play -m machina_1 -p class=cvc.cogamer_policy.CvCPolicy -c 8 --seed 42 -r none

# Play without LLM (unset API key)
ANTHROPIC_API_KEY= cogames play -m machina_1 -p class=cvc.cogamer_policy.CvCPolicy -c 8 --seed 42 -r none

# Upload to tournament
cogames upload -p class=cvc.cogamer_policy.CvCPolicy -n coglet-v0 \
  -f cvc -f setup_policy.py \
  --setup-script setup_policy.py --season beta-cvc \
  --secret-env "COGORA_ANTHROPIC_KEY=..."

# Check tournament results
cogames results --season beta-cvc --policy coglet-v0
```

## Scheduling & Monitoring

Use `/loop` to schedule recurring checks while waiting for results:

```bash
# Monitor tournament results every 30 minutes
/loop 30m check coglet-v0 tournament results on beta-cvc, report score and rank

# Watch a running game's learnings output
/loop 5m check /tmp/coglet_learnings/ for new game results, summarize scores

# Poll for deployment completion
/loop 10m check if coglet-v0 latest version has tournament results yet
```

Syntax: `/loop [interval] <prompt>` — intervals: Ns, Nm, Nh, Nd (default 10m, min 1m).

## Logging & Learnings

### Console Output
- `[coglet] a{id} step={n} llm={ms}ms interval={n}: {analysis}` — LLM call
- `[coglet:snap] a{id} step={n} role={r} hp={hp} hearts={h} | C=... | junc: f={f} e={e} n={n} | {subtask}` — state snapshot

### Learnings File
Written to `/tmp/coglet_learnings/{game_id}.json` at end of episode:
```json
{
  "game_id": "...",
  "duration_s": 123.4,
  "agents": { "0": {"steps": 10000, "last_infos": {...}}, ... },
  "llm_log": [ {"step": 500, "agent": 0, "latency_ms": 2000, ...}, ... ],
  "snapshots": [ {"step": 500, "agent": 0, "role": "miner", ...}, ... ]
}
```

## Key Insights (from optimization)
- **Score depends on junction holding time** — capturing junctions early and keeping them matters more than late-game captures
- **Silicon bottleneck** is common — often the first resource to run out
- **Hub proximity matters** — junctions close to hub are cheaper to defend and resupply
- **Heart efficiency** is critical — each heart-based death is expensive in steps lost
- **LLM adds ~2s latency per call** — tournament has action timeout constraints
- **Alpha.0 constants don't work for us** — their RETREAT_MARGIN=20, deposit_threshold=40 require their full LLM pilot system
- **Tournament vs local gap** — local scores with LLM (avg 9.6, best 23.4) much higher than tournament (~2-3). Tournament is 1v1 vs real policies, not clips
