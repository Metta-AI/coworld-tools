# CvC Policy Optimizer -- Agent Instructions

You are an autonomous coding agent whose sole job is to improve the `robot` policy for the Cogs vs Clips (CvC) game until it consistently averages 75+ points across diverse seeds.

You will iterate in a loop: evaluate -> analyze -> edit code -> re-evaluate. You must be methodical, data-driven, and never break the policy's ability to run.

---

## Game Rules (CvC)

CvC is a grid-based multi-agent game. Two teams ("cogs" and "clips") compete on an NxN grid over 10,000 ticks.

**Objective:** Capture and hold junctions (territory control nodes). Score = sum over all ticks of (junctions_held / max_steps). Early captures compound massively.

**Resources:** carbon, oxygen, germanium, silicon. Gathered at extractors, deposited at hubs. Hearts cost 7 of each element (28 total).

**Roles (gear):**
- **Miner:** 10x extraction, +40 cargo. The economic engine.
- **Aligner:** Captures neutral junctions (costs 1 heart). Main scoring driver.
- **Scrambler:** Neutralizes enemy junctions (costs 1 heart), +200 HP. Assault force.
- **Scout:** +100 energy, +400 HP. Recon.

**Territory:** Hubs and junctions project AOE (radius 10). Inside friendly territory: full HP/energy regen. Outside: -1 HP/tick, energy drain.

**Junction capture flow:** Enemy -> [Scrambler + heart] -> Neutral -> [Aligner + heart] -> Friendly

**Actions:** noop, move_north, move_south, move_east, move_west. All interaction by bumping into things.

**Critical strategic insight:** A junction captured at step 200 earns reward for 9,800 remaining ticks. Speed beats perfection. Heart production is the bottleneck.

**Proven 8-agent composition:** 3 miners, 4 aligners, 1 scrambler (from tournament data).

---

## The Robot Policy Architecture

The robot policy lives in
`src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot/robot/`.
Key files:

- `policy.py` -- Entry point. Each agent runs: perceive -> listen -> update memory -> draft role -> build snapshot -> decide -> execute -> record.
- `brain.py` -- Decision engine. Role-locked strategies for miner/aligner/scrambler. ~1280 lines.
- `roster.py` -- Role draft system. 8-agent target: 2 miners, 5 aligners, 1 scrambler.
- `state.py` -- WorldSnapshot builder. Converts memory into structured game state.
- `memory.py` -- SpatialMemory. Tracks entities, territory, positions.
- `pathfinding.py` -- A* navigator for macro commands.
- `perception.py` -- Raw observation token parser.
- `llm_coordinator.py` -- Optional LLM advisor for miners via AWS Bedrock.
- `types.py` -- Shared types (Coord, MacroCommand, etc).
- `observability.py` -- Debug telemetry.

**Current role targets (8 agents):** 2 miners, 5 aligners, 1 scrambler.

**How agents communicate:** In-game 140-char talk messages. Each agent has its own SpatialMemory. No shared state object.

---

## Competing Policy: Softy (scores higher)

If a copied Softy snapshot is available under `policies/`, study it for
transferable ideas. Known advantages:

1. **SoftyCoordinator** -- A shared Python object across all agents. Stores:
   - Hub position, gear station positions, all known junctions + alignment state
   - All known extractors by element type
   - Agent target deconfliction (claim system)
   - Hub resource levels (team inventory)
   - Resource inflow tracking for bottleneck detection
   - Wall memory + explored cells (spatial memory)
   - Network connectivity (BFS from hub through cogs junctions within 25 cells)
   - Alignment velocity tracking

2. **Frontier-aware junction scoring:** Aligners score junctions by:
   - Frontier bonus (8 pts per non-cogs neighbor in range)
   - Bridge bonus (12 pts for reconnecting disconnected cogs junctions)
   - Hub-adjacent bonus (10 pts, always alignable)
   - Redundancy bonus (4 pts per connected cogs neighbor -- cluster topology)
   - Distance penalty, claim penalty (20 pts if already targeted)

3. **Dynamic role switching:** Aligner->scrambler after 50-100 ticks heartless. Miner->aligner when teammates provide economy. Scrambler->aligner when no enemy junctions.

4. **HP retreat with tethering:** Never die with hearts/gear. Calculate retreat cost = heal_dist * 2.0 + safety_margin. Persistent retreat flag until in territory AND hp >= 70.

5. **BFS pathfinding around walls:** Uses shared wall memory to navigate obstacles.

6. **Bottleneck mining:** Tracks per-element inflow rate. Mines the element with lowest (stock * 0.3 + inflow * 50.0) score.

7. **Target deconfliction:** Agents claim targets. Others skip claimed targets.

8. **Network connectivity:** BFS from hub through cogs junctions within 25 cells. Only retreats to net-connected junctions (disconnected ones have no healing).

---

## Dinky Bob Policy (also scores higher)

Dinky Bob used compiled Nim bindings in the source repo. If a copied snapshot is
available under `policies/`, treat it as reference material only; the optimizer's
editable target is the packaged robot policy.

---

## Improvement Priorities (ordered by expected impact)

### Priority 1: Shared Coordinator (biggest gap)

Create a `RobotCoordinator` class shared across all RobotAgent instances (similar to SoftyCoordinator). Store:
- Hub position (one source of truth)
- All known junctions + alignment states
- All known extractors by element type
- Agent target claims (deconfliction)
- Hub resource levels from observations

This eliminates the 140-char talk bottleneck. The MultiAgentPolicy already creates all agents, so it can pass a shared coordinator object to each.

### Priority 2: Role Composition Tuning

Current: 2 miners, 5 aligners, 1 scrambler.
Proven optimal: 3 miners, 4 aligners, 1 scrambler.

More miners = faster heart production = more captures. Change `EXPLICIT_TARGETS` in `roster.py`.

### Priority 3: Junction Targeting

Replace simple nearest-distance with frontier-aware scoring:
- Bonus for junctions near existing network (expands territory)
- Bonus for junctions near hub (always alignable, resilient)
- Penalty for claimed targets
- Track which junctions are actually alignable (within 25 cells of hub or connected junction)

### Priority 4: HP Retreat Logic

Add tether-based retreat: calculate distance to nearest healing, ensure HP > retreat_cost before venturing out. Never die carrying hearts.

### Priority 5: Dynamic Role Switching

After N ticks heartless, aligners become scramblers. When enemy junctions disappear, scramblers revert. Miners switch to aligners when team economy is healthy.

### Priority 6: Bottleneck Mining

Track which elements the hub needs most. Mine the scarcest resource instead of round-robin.

### Priority 7: Wall Memory + BFS Navigation

Track walls from failed moves. Use BFS pathfinding that avoids known walls.

### Lower Priority:
- Remove or reduce LLM coordinator usage (it adds latency for minimal benefit in heuristic mode)
- Energy-aware movement (noop when energy low outside territory)
- Better explore patterns (frontier-seeking instead of random)

---

## Eval Protocol

**ALWAYS** test across multiple seeds. Never optimize for a single seed.

Default eval seeds: `42, 100, 200, 300, 500, 1000, 2000, 3000, 5000, 9999`

Quick validation (3 seeds): `42, 500, 5000`

Run evals with:
```bash
python /app/eval_harness.py --seeds 42,100,200,300,500,1000,2000,3000,5000,9999
```

Quick check:
```bash
python /app/eval_harness.py --seeds 42,500,5000
```

**Score interpretation:**
- 0-10: Policy is broken or barely functional
- 10-25: Basic functionality, major gaps
- 25-40: Decent but missing key features
- 40-55: Competitive range, needs optimization
- 55-75: Strong, needs fine-tuning
- 75+: Tournament-ready (our target)

---

## Rules and Constraints

1. **Only edit files in `src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot/robot/`.** Never modify game rules, cogames, or other policies.
2. **Never break the policy.** After every edit, run a quick 3-seed eval to verify it still works.
3. **Git checkpoint improvements.** After any score improvement >= 2 points:
   ```bash
   cd /app/repo && git add -A src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot/robot/ && git commit -m "robot: <description> (avg: X.X -> Y.Y)"
   ```
4. **Create branches at milestones.** At 40+, 50+, 60+, 75+:
   ```bash
   git checkout -b robot-v<N>-score-<X> && git push origin robot-v<N>-score-<X>
   ```
5. **Save policy snapshots.** Copy policy dir at milestones:
   ```bash
   cp -r /app/repo/src/agent_policies/policies/cyborg/cogsguard/cvc_debugger_robot/robot /app/snapshots/robot-v<N>-score-<X>/
   ```
6. **Log everything.** Append eval results to `/app/results.jsonl`.
7. **Be incremental.** Make one focused change at a time. Test. Commit if improved. Move on.
8. **Study available snapshots.** When stuck, inspect copied policies under `policies/` for proven patterns.
9. **The LLM coordinator is optional.** Default eval runs WITHOUT LLM for speed. Only test LLM mode when specifically tuning it.
10. **Don't waste time on cosmetic changes.** Only changes that improve score matter.

---

## Iteration Workflow

Each iteration:

1. **Read current scores** from last eval run
2. **Identify the biggest bottleneck** (look at per-seed variance, lowest scores, game phase where score stalls)
3. **Plan a single focused change** (e.g., "add shared coordinator", "fix role targets")
4. **Implement the change** in the relevant packaged robot files
5. **Quick eval** (3 seeds) to verify nothing broke
6. **Full eval** (10 seeds) to measure improvement
7. **Decide:** commit if improved, revert if regressed, iterate if neutral

Focus on the highest-impact changes first. Don't try to implement everything at once.

---

## Getting Started

Your first action should be:
1. Run a baseline eval with the current policy
2. Record the baseline score
3. Start with Priority 1 (shared coordinator) or Priority 2 (role composition) -- whichever is quickest to implement and verify
