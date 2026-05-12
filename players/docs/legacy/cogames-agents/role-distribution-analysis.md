# Role Distribution Analysis: Existing Scripted Agents

> **Issue:** cg-llxe | **Date:** 2026-01-28 | **Author:** polecat/dust (automated analysis)

## Executive Summary

This document systematically analyzes role distributions across all existing scripted agents in the CoGames agent suite.
The four available roles are **miner**, **scout**, **aligner**, and **scrambler**. Each agent variant uses a different
strategy for distributing agents across these roles, ranging from static URI-configured counts to dynamic
game-state-driven role switching.

**Key Finding:** The highest-performing agents (CoGsGuard Control, Wombo) share a common pattern: they start with an
explore-heavy distribution and dynamically shift toward aligner/scrambler-heavy distributions as junctions are
discovered. Pure static distributions (planky defaults) leave performance on the table.

---

## 1. Roles in CoGsGuard Mechanics

In CoGsGuard, the competitive objective is **junction alignment**: aligning junctions to your team ("cogs") while
denying them to the opponent ("clips"). Hearts are produced from four resources (carbon, oxygen, germanium, silicon) via
hub recipes.

| Role          | Primary Function                                    | Win Contribution                               |
| ------------- | --------------------------------------------------- | ---------------------------------------------- |
| **Miner**     | Gather resources from extractors, deposit at hub    | Heart production (resource economy)            |
| **Scout**     | Explore map, discover extractors/junctions/stations | Enables all other roles by providing map intel |
| **Aligner**   | Align neutral/enemy junctions to cogs               | Direct scoring + team energy via AOE           |
| **Scrambler** | Scramble enemy-aligned junctions                    | Denial + scoring (neutralize enemy junctions)  |

---

## 2. Agent-by-Agent Role Distribution Analysis

### 2.1 Planky (`metta://policy/planky`)

**Architecture:** Goal-tree hierarchical policy. Static role distribution via URI params.

**Default distribution (10 agents):**

| Role      | Count | Percentage |
| --------- | ----- | ---------- |
| Miner     | 4     | 40%        |
| Scout     | 0     | 0%         |
| Aligner   | 2     | 20%        |
| Scrambler | 4     | 40%        |

**URI params:** `?miner=4&scout=0&aligner=2&scrambler=4`

**Key observations:**

- Default has **zero scouts**. Map discovery depends entirely on miners stumbling into structures.
- Heavy scrambler bias (40%) reflects a competitive/denial strategy.
- Aligner count (2) is low relative to scramblers.
- No dynamic role switching -- distribution is fixed for the entire episode.
- Supports a `stem` role that dynamically selects among roles at runtime, but it's off by default (`stem=0`).

**Source:** `planky/policy.py:254-268` -- constructor defaults `miner=4, scout=0, aligner=2, scrambler=4`.

---

### 2.2 Role / CoGsGuard (`metta://policy/role`)

**Architecture:** Multi-role vibe system with SmartRoleCoordinator. Dynamic role switching.

**Default distribution (when no URI params):**

| Role           | Count | Percentage (10 agents) |
| -------------- | ----- | ---------------------- |
| Scrambler      | 1     | 10%                    |
| Miner          | 4     | 40%                    |
| Gear (dynamic) | 5     | 50%                    |

**URI params default:** `scrambler=1, miner=4`, remaining agents get `gear` vibe.

**Smart coordinator role selection (for `gear` agents):** The `SmartRoleCoordinator.choose_role()` method dynamically
assigns roles based on team state:

1. If hub or chest not found → **scout**
2. If no scout in team → **scout**
3. If no miner in team → **miner**
4. If no scrambler → **scrambler**
5. If no aligner → **aligner**
6. If clips junctions exist and scramblers <= aligners → **scrambler**
7. If neutral junctions exist → **aligner**
8. If few structures discovered → **scout**
9. Fallback → **miner**

**Key observations:**

- The 1 scrambler guaranteed at start provides **scrambler gear priority** for the first 25 steps -- other agents yield
  gear station access.
- `gear` agents dynamically fill gaps, producing a balanced team.
- Smart role switching occurs on a 40-step cooldown, allowing mid-episode adaptation.
- This is the most adaptive base agent, but initial startup can be slow (agents exploring before coordinator has data).

**Source:** `cogsguard/policy.py:1300-1404` (constructor/defaults), `cogsguard/policy.py:278-311` (choose_role).

---

### 2.3 CoGsGuard V2 (`metta://policy/cogsguard_v2`)

**Architecture:** CoGsGuard base with tuned static default allocation formula.

**Default distribution by team size:**

| Team Size | Scrambler   | Aligner     | Scout | Miner     |
| --------- | ----------- | ----------- | ----- | --------- |
| 1         | 0           | 0           | 0     | 1         |
| 2         | 1           | 0           | 0     | 1         |
| 3         | 1           | 0           | 1     | 1         |
| 4-7       | 1           | 1           | 1     | N-3       |
| 8+        | N/6 (min 2) | N/6 (min 2) | 1     | remainder |

**Example: 10 agents:**

| Role      | Count | Percentage |
| --------- | ----- | ---------- |
| Scrambler | 2     | 20%        |
| Aligner   | 2     | 20%        |
| Scout     | 1     | 10%        |
| Miner     | 5     | 50%        |

**Key observations:**

- Unlike base role, V2 **always includes a scout** (for teams >= 3).
- Balanced scrambler/aligner split.
- Miner-heavy remainder ensures resource economy.
- Static allocation -- no dynamic switching beyond what the smart coordinator provides at runtime.

**Source:** `cogsguard/v2_agent.py:12-33` (default role counts formula).

---

### 2.4 CoGsGuard Control (`metta://policy/cogsguard_control`)

**Architecture:** Phased commander coordinator with active role reassignment.

**Phase-based distribution (10 agents):**

| Phase             | Step Range | Scrambler | Aligner | Scout | Miner |
| ----------------- | ---------- | --------- | ------- | ----- | ----- |
| **Explore**       | 0-60       | 1         | 0       | 2     | 7     |
| **Control**       | 60-220     | 2         | 2       | 1     | 5     |
| **Sustain**       | 220+       | 1         | 1       | 1     | 7     |
| **Low resources** | (any)      | 1         | 1       | 1     | 7     |

**Key observations:**

- **Phase-aware distribution** is the distinguishing feature. Early game heavily favors scouting and mining.
- Control phase ramps up scramblers and aligners when junctions are discovered.
- Sustain phase reduces combat roles as junctions stabilize.
- Commander (agent 0) re-plans every 40 steps based on aggregated game state.
- Assigns **specific junction targets** to scrambler/aligner agents -- avoids wasting effort on already-aligned
  junctions.
- Default initial allocation uses same formula as V2.

**Source:** `cogsguard/control_agent.py:113-146` (phase-based count selection).

---

### 2.5 Wombo (`metta://policy/wombo`)

**Architecture:** CoGsGuard generalist variant prioritizing multi-junction alignment.

**Distribution strategy:** Wombo inherits from `CogsguardGeneralistImpl` and overrides target role counts. When fewer
than `TARGET_ALIGNED_JUNCTIONS` (2) are aligned:

| Role      | Target Count |
| --------- | ------------ |
| Scout     | max(base, 2) |
| Scrambler | max(base, 2) |
| Aligner   | max(base, 2) |
| Miner     | max(4, N/2)  |

**Effective distribution (10 agents, early game before 2 junctions aligned):**

| Role      | Count | Percentage |
| --------- | ----- | ---------- |
| Scrambler | 2     | 20%        |
| Aligner   | 2     | 20%        |
| Scout     | 2     | 20%        |
| Miner     | 5     | 50%        |

After 2 junctions are aligned, it falls back to the base generalist `_select_role()` logic which uses a situation-aware
algorithm considering:

- Pending actions
- Charger alignments
- Extractor availability
- Role balance scores

**Key observations:**

- Most aggressive junction-control strategy.
- Double scouts ensure fast map discovery.
- Each agent is a **generalist** that dynamically selects roles on a 120-step cooldown.
- Role selection is per-agent and situation-aware, not centrally coordinated.

**Source:** `cogsguard/policy.py:1871-1935` (WomboImpl), `cogsguard/policy.py:1755-1772` (target counts).

---

### 2.6 Teacher (`metta://policy/teacher`)

**Architecture:** Wrapper that delegates to Nim CoGsGuard agents with forced initial vibes.

**Default distribution:** Cycles through `["miner", "scout", "aligner", "scrambler"]` per agent. Each episode, the role
assignment rotates by `(episode_index + agent_id) % 4`.

**Effective per-episode (4 agents):**

| Role      | Count | Percentage |
| --------- | ----- | ---------- |
| Miner     | 1     | 25%        |
| Scout     | 1     | 25%        |
| Aligner   | 1     | 25%        |
| Scrambler | 1     | 25%        |

**Key observations:**

- Even 1:1:1:1 distribution is designed for **behavioral cloning** -- it exposes the learner to all roles equally.
- Not optimized for performance; optimized for training signal diversity.
- Rotates roles across episodes so each agent learns all behaviors.

**Source:** `cogsguard/teacher.py:116-142` (role action resolution), `cogsguard/teacher.py:156-162` (rotation logic).

---

## 3. URI Parameter Reference

All CoGsGuard-family agents accept role count parameters via URI query strings:

```
metta://policy/<agent>?miner=N&scout=N&aligner=N&scrambler=N&gear=N
```

### Base role additional params:

```
metta://policy/role?role_cycle=aligner,miner,scrambler,scout  # Repeating cycle
metta://policy/role?role_order=aligner,miner,aligner,miner    # Exact sequence
metta://policy/role?evolution=1                                 # Evolutionary roles
```

### Planky additional params:

```
metta://policy/planky?miner=4&aligner=2&scrambler=4&stem=0&trace=1
```

### Single-role policies:

```
metta://policy/miner      # All agents as miners
metta://policy/scout       # All agents as scouts
metta://policy/aligner     # All agents as aligners
metta://policy/scrambler   # All agents as scramblers
```

---

## 4. Comparative Distribution Table

For a standard 10-agent team:

| Agent                 | Miner        | Scout   | Aligner | Scrambler | Dynamic? | Notes                                           |
| --------------------- | ------------ | ------- | ------- | --------- | -------- | ----------------------------------------------- |
| **planky** (default)  | 4 (40%)      | 0 (0%)  | 2 (20%) | 4 (40%)   | No       | No scouts; denial-heavy                         |
| **role** (default)    | 4 (40%)      | 0-2\*   | 0-2\*   | 1 (10%)   | Yes      | 5 dynamic `gear` agents fill gaps               |
| **cogsguard_v2**      | 5 (50%)      | 1 (10%) | 2 (20%) | 2 (20%)   | Limited  | Balanced static formula                         |
| **cogsguard_control** | 5-7          | 1-2     | 0-2     | 1-2       | Yes      | Phase-aware; commander reassigns every 40 steps |
| **wombo**             | 4-5 (40-50%) | 2 (20%) | 2 (20%) | 2 (20%)   | Yes      | Per-agent generalist; junction-push mode        |
| **teacher**           | 1 (25%)      | 1 (25%) | 1 (25%) | 1 (25%)   | Rotates  | Even split for training signal diversity        |

\*role `gear` agents are assigned by the SmartRoleCoordinator at runtime based on game state.

---

## 5. Optimal Distribution Theory (CoGsGuard Mechanics)

### Junction Alignment is the Objective

In competitive CoGsGuard, the primary scoring mechanism is **aligned junction held** -- the number of junctions aligned
to your team at episode end. This makes aligner and scrambler roles disproportionately valuable for scoring.

However, **miners fund the economy**: hearts are consumed by aligners (1 heart per alignment) and scramblers (1 heart
per scramble). Without miners producing hearts, combat roles starve.

### Theoretical Optimal by Game Phase

**Early game (steps 0-100):**

- 2 scouts (map discovery is critical -- extractors and junctions are unknown)
- 1 scrambler (deny early enemy junction claims; gets gear priority)
- remainder miners (bootstrap resource economy)

**Mid game (steps 100-500):**

- 0-1 scout (map mostly discovered)
- 2 scramblers (active junction denial)
- 2 aligners (claim neutral/scrambled junctions)
- remainder miners (sustain heart production)

**Late game (steps 500+):**

- 0 scouts (map fully discovered)
- 1-2 scramblers (maintain denial)
- 1-2 aligners (maintain claims)
- remainder miners (extractors may be depleted, but some still cycle)

### Recommended Distributions

**Heavy aligner strategy (scoring-focused):**

```
metta://policy/role?scrambler=2&aligner=3&miner=4&scout=1
```

Prioritizes junction control. Works when opponent is passive.

**Heavy scrambler strategy (denial-focused):**

```
metta://policy/planky?scrambler=4&aligner=2&miner=3&scout=1
```

Denies opponent while maintaining moderate economy. Works against aggressive opponents.

**Balanced adaptive (recommended):**

```
metta://policy/cogsguard_control
```

Phase-aware distribution handles all game states. Best general-purpose choice.

**Maximum economy (resource-gathering focus):**

```
metta://policy/role?miner=7&scout=1&aligner=1&scrambler=1
```

Maximizes heart production. Best for non-competitive or pure resource metrics.

**Junction-push (competitive burst):**

```
metta://policy/wombo
```

Aggressive junction control with double scouts and generalist role switching.

---

## 6. Conclusions

1. **No agent currently uses a theoretically optimal distribution out of the box.** Planky lacks scouts entirely in its
   defaults. Role defaults are miner-heavy with most agents dynamically assigned.

2. **Dynamic role switching outperforms static allocation.** CoGsGuard Control and Wombo (the highest-rated agents in
   machina1 analysis) both use adaptive distributions.

3. **The scout role is consistently undervalued.** Only cogsguard_v2, cogsguard_control, and wombo allocate scouts by
   default. Map discovery is a prerequisite for all other roles to function effectively.

4. **Aligner/scrambler balance matters more than total count.** Having 2 aligners and 2 scramblers outperforms 4 of
   either, because alignment and denial are complementary operations on the same junction objects.

5. **The "gear" meta-vibe is the most flexible mechanism** for dynamic distribution, but its effectiveness depends
   entirely on the SmartRoleCoordinator having sufficient information (which requires scouts or incidental discovery by
   miners).

6. **For training/behavioral cloning**, the even 1:1:1:1 teacher distribution is correct -- it maximizes behavioral
   diversity in the training signal. For evaluation/competition, the phase-aware cogsguard_control distribution is the
   strongest general-purpose choice.
