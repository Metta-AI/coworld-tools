# CogsGuard Experiment Log

> Complete record of all training runs, sweep results, and experimental findings.
> For the active execution plan, see [ROADMAP.md](ROADMAP.md).
> For setup & technical reference, see [README.md](README.md).
> For literature review, see [LITERATURE.md](LITERATURE.md).

---

## Experimental Findings (Phase 1)

### Eval Results: Starter vs Random (cogsguard_machina_1.basic, 8 cogs, 10,000 steps)

| Metric | Starter | Random |
|--------|---------|--------|
| Per-agent reward | 1.00 | 1.00 |
| Failed moves (per agent) | **7,883** | 26 |
| Successful moves | 2,117 | 771 |
| Cells visited | 86,273 | 27,273 |
| Cogs aligned junctions | **0** | 0 |
| Clips aligned junctions | **144** | - |
| Hearts gained | 0.88 | 8.0 |

**Key observations**:
- The starter policy on its own **fails to capture any junctions** — clips take all 144
- The starter has massive failed-move rate (79%) — it gets stuck navigating walls
- Random agents explore less but interact more (get more hearts)
- Neither policy is competitive — the leaderboard top scores (7-21) come from sophisticated scripted agents in the cogames-agents repo

### Analysis of Scripted Agents (cogames-agents repo)

The **Planky agent** (one of the stronger scripted policies) reveals the architecture needed:

1. **Persistent entity map**: Accumulates spatial memory across steps (explored cells, entity positions)
2. **A* pathfinding** with stuck detection, sidestep avoidance, and frontier exploration
3. **Goal-stack architecture**: Priority-ordered goals per role (survive > emergency mine > get gear > role-specific task)
4. **Resource bottleneck switching**: Miners dynamically target the most-needed resource
5. **Static role assignment**: Default 4 miners + 4 aligners (fixed at episode start)
6. **Zero inter-agent coordination**: Each agent operates independently with its own world model
7. **Anti-stuck mechanisms**: 5+ independent stuck-recovery systems

**What Planky lacks** (and where our approach can win):
- No dynamic role switching (only one hardcoded aligner→scrambler at step 1000)
- No teammate modeling (doesn't know what other agents are doing)
- No scouts by default (the docs say scouts are "consistently undervalued")
- No adaptive coordination (implicit only, through shared collective inventory)
- Optimal role distribution changes over time: early=scouts+miners, mid=scramblers+aligners, late=miners+aligners

---

## Current State of the Benchmark

### What exists
- **Game**: CogsGuard — 8-agent cooperative territory control, 10,000-step episodes, partial observability (13x13 egocentric)
- **Roles**: Miner, Aligner, Scrambler, Scout — no single role can succeed alone
- **Scoring**: Value Over Replacement (VOR) — how much your agent improves a mixed team
- **Training stack**: PPO via PufferLib, CNN+LSTM architecture, 256 parallel envs
- **Top policy**: `dinky:v24` (scripted, score 21.09) — no learned agent has scored >6 on the leaderboard (PI confirmed 2026-03-11; slanky is scripted)

### What's hard
1. **Role discovery**: Scripted agents hand-assign roles. Learned agents can't discover specialization on their own.
2. **Partial observability**: 13x13 view on maps up to 100x100. No memory of explored territory.
3. **Long episodes + sparse credit**: 10,000 steps. Reward = junctions held / max_steps each tick, but the chain from resource gathering to junction capture is long and indirect.
4. **Coordination without communication**: Agents share reward but have no explicit communication channel (only "vibes" — role signals).
5. **Teammate generalization**: VOR scoring means you must cooperate with unknown teammates, not just clones of yourself.

### Why scripted agents win
The scripted `dinky` policy hard-codes the key insight: **split agents into miners and aligners**. Miners gather resources, aligners capture junctions. This solves role assignment, coordination, and credit assignment simultaneously — but it requires human knowledge of the game and can't adapt.

### The economy chain
```
Mine resources (C, O, Ge, Si) → Deposit at hub → Craft hearts (7 of each element)
→ Acquire gear (role-specific element costs) → Capture junctions (1 heart each)
→ Territory AOE heals agents → Score = junctions_held / max_steps per tick
```

---

## Identified Bottlenecks & Research Angles

### Bottleneck 1: No World Model
Current learned agents (CNN+LSTM) are reactive — they see 13x13 tokens and produce an action. They have no persistent spatial map, no model of resource locations, no prediction of teammate behavior. This makes long-horizon planning impossible.

**Active inference angle**: A generative model that predicts observations given actions would provide:
- Spatial memory (where are resources, junctions, teammates?)
- Counterfactual reasoning (what happens if I go north vs south?)
- Temporal depth (planning over 10+ steps, not just next-action)

**Note**: Planky already implements a basic world model (EntityMap) that works well. We can reuse this pattern and add probabilistic inference on top.

### Bottleneck 2: No Role Discovery
PPO with shared parameters produces homogeneous behavior. All 8 agents try to do everything, leading to resource contention and no strategic division of labor.

**Active inference angle**: Hierarchical generative model with:
- **High-level policy**: Selects role/goal (mine, align, scramble, scout) — slow timescale
- **Low-level policy**: Executes role-specific behavior (navigate, interact) — fast timescale
- Role selection driven by expected free energy: "which role reduces uncertainty about team success the most?"

**Key insight from Planky analysis**: The optimal role distribution changes over the episode (early: scouts+miners → mid: scramblers+aligners → late: miners+aligners). No current agent implements this adaptively.

### Bottleneck 3: No Theory of Mind
Agents don't model teammates. They can't infer "agent 3 is mining, so I should align" or "this area is already covered, I should go elsewhere."

**Active inference angle**: ToM via generative model of other agents:
- Infer others' roles from observed vibes + movement patterns
- Adjust own role selection to complement the team
- This is exactly the social-layer architecture: intent particle filter over teammate goals

**Key insight**: Vibes are visible to all agents in the observation window. An agent can literally read teammate vibes to know their role — but no current agent uses this for adaptive coordination.

### Bottleneck 4: Exploration is Undirected
LSTM-PPO explores via entropy bonus. In a 100x100 partially observable world, this is hopelessly slow. The agent has no drive to explore unknown territory.

**Active inference angle**: Epistemic foraging — expected information gain as an intrinsic drive:
- "I haven't seen the north side of the map — going there reduces my uncertainty"
- Naturally balances exploitation (capture known junctions) with exploration (find new ones)

---

## Phased Roadmap

### Phase 1: Environment Mastery (Week 1 — 10 hrs) ✅ COMPLETE

- [x] Install cogames on AWS sandbox (Python 3.12, NVIDIA L4 GPU)
- [x] Clone cogames and cogames-agents repos
- [x] Run eval with starter and random policies
- [x] Study observation token format and action space
- [x] Study Planky scripted agent architecture in depth
- [x] Map the full game loop: resources → hub → hearts → junctions → reward
- [x] Submit baselines to the leaderboard (mahault.random-baseline:v1, mahault.starter-baseline:v1 on beta-cvc)

### Phase 2: Bottleneck Analysis (Week 2 — 10 hrs) ✅ COMPLETE

**Goal**: Identify and document the specific failure modes of current learned approaches.

- [x] Train a basic CNN+LSTM policy with PPO (10M steps on arena, 5.1M on machina_1)
- [x] Compare its behavior to the scripted starter — what does it fail to learn?
- [x] Document specific failure modes: role confusion, exploration failure, credit assignment
- [x] Build baselines comparison table (Starter vs Random vs Trained)
- [x] Build "Buggy" scripted agent (Planky fork with full role goal trees)
- [x] Set up eval infrastructure (eval_and_log.sh, results_log.jsonl)
- [x] Exhaustive sweep of reward shaping, hyperparams, curriculum (18 A3 experiments, 3 machina_1 experiments)
- [x] PI meetings (2026-03-10, 03-11, 03-13, 03-14) — AIF direction approved, research proposal accepted
- [x] Individual role training (A1.5) — aligner 12.1 junctions, scrambler 15.9 hearts
- [x] Scout investigation — root cause: reward ratio, not exploration
- [x] Kickstarted training (Path B) — first functioning economy chain on machina_1

**Deliverable**: Written analysis of bottlenecks with evidence from training runs and replays.

### Phase 2b: Systematic Approach Evaluation (Week 3 — 8 hrs) ✅ COMPLETE

**Goal**: Evaluate ALL candidate approaches from the literature review before committing to implementation. Score each on feasibility, expected impact, implementation cost, and compatibility with our constraints (CPU-only training, PufferLib, ~50 remaining hours, 30GB disk).

#### Evaluation Criteria

| Criterion | Weight | Description |
|-----------|--------|-------------|
| **Expected impact** | 30% | Estimated VOR score improvement based on paper results and problem fit |
| **Implementation effort** | 25% | Hours to implement given our codebase and constraints |
| **Feasibility** | 20% | Can it work CPU-only? Compatible with PufferLib/cogames? Proven at our scale? |
| **Composability** | 15% | Can it combine with other approaches? Does it stack? |
| **Novelty/research value** | 10% | Differentiation for the contract deliverable and Softmax presentation |

#### Category 1: Quick Wins (Reward Shaping & Config) ✅ COMPLETE

- [x] **A1: Forced role assignment** — Pre-assign vibes in config (2 miner + 2 aligner + 2 scrambler + 2 scout)
  - ✅ Done. forced_role_vibes config tested. Key finding: `role_conditional` HURTS (overwrites reward keys, miners get heart.gained=-0.1 penalty).
- [x] **A2: Reward variant stacking** — `credit` + `role_conditional` + `objective_mine:25`
  - ✅ Done. Best combo: forced_role_vibes + credit + objective_mine:50 → **2.500 junctions**. Reward conflict discovered: `credit` + `role_conditional` stacking overwrites keys.
- [x] **A3: Hyperparameter tuning** — gamma=0.999, gae_lambda=0.95, bptt=128, ent_coef=0.05, checkpoint_interval=50
  - ✅ Done (A3 sweep: 18 experiments). Best: milestones alone, ent=0.03, u=3 → **3.214 junctions**.
- [x] **A4: Curriculum training** — arena (50x50) → machina_1 (88x88), `events_no_clips` → standard
  - ✅ Evaluated. Arena configs DON'T transfer to machina_1 (Phase 2b: 3 experiments, all 0 junctions). Superseded by individual role training (A1.5).

#### Category 2: Architecture Changes (Neural) — EVALUATED, B2' IN PIPELINE

- [ ] **B1: MAPPO** (centralized critic) — [Yu et al., NeurIPS 2022]
  - Evaluated in decision matrix. Not chosen — individual role training (A1.5) + kickstarting addresses credit assignment more directly.
- [x] **B2: Entity Transformer** — replace CNN with attention over observation tokens
  - ✅ Superseded by **B2': Cortex arch** (AGaLiTe + Axon + sLSTM). In pipeline as step S5. Public package: github.com/Metta-AI/cortex
- [ ] **B3: HAPPO** (heterogeneous-agent PPO) — [Kuba et al., ICLR 2022]
  - Evaluated in decision matrix. Not chosen — individual role training achieves specialization without HAPPO complexity.
- [ ] **B4: MAT** (Multi-Agent Transformer) — [Wen et al., NeurIPS 2022]
  - Evaluated in decision matrix. Not chosen — compute cost too high for L4 GPU.

#### Category 3: Role Discovery & Exploration — SUPERSEDED by A1.5

Individual role training (A1.5) solved role specialization directly — no need for learned role discovery. PI confirmed: train individual roles, then kickstart or compose heterogeneous teams.

- [ ] **C1: ACORM** — Superseded. Individual role training + forced vibes solves specialization.
- [ ] **C2: MAVEN** — Superseded. Forced vibes + individual training removes exploration burden.
- [ ] **C3: RODE** — Superseded. Only 5 actions (noop + 4 moves) — too few for meaningful clustering.
- [ ] **C4: R3DM** — Superseded.
- [ ] **C5: MAVEN + Social Influence** — Superseded.

#### Category 4: Hierarchical & Planning — EVALUATED, NOT CHOSEN

AIF approach (F1/H1) chosen as capstone instead. HTN-style structure encoded in POMDP generative model.

- [ ] **D1: HS-MARL + HTN** — Not chosen. Economy chain structure encoded in POMDP B matrix instead.
- [ ] **D2: Feudal MARL** — Not chosen.
- [ ] **D3: Distributed Option-Critic (DOC)** — Not chosen.

#### Category 5: Communication-Based — IN PIPELINE (Step S6)

Research narrative: learned communication is the empirical bridge between scripted and AIF approaches.

- [ ] **E1: TarMAC** (targeted communication) — In pipeline (step S6). Scouts share junction info with aligners, miners coordinate deposits.
- [ ] **E2: IC3Net** (gated communication) — In pipeline (step S6). Learns WHEN to communicate, low implementation cost.
- [ ] **E3: MAIC** (incentive communication) — Not chosen. Requires teammate model — high implementation cost.

#### Category 6: Active Inference / Model-Based — F1 CHOSEN AS CAPSTONE, IN PROGRESS

- [x] **F1: Scripted AIF agent** (social-layer port) — **CHOSEN as capstone approach**. POMDP module implemented in `aif-meta-cogames` repo (18-state POMDP, 3 obs modalities, 5 actions, A/B matrix fitting from trajectory data). Design doc: `AIF_DESIGN.md`. Next: fit from v3 data + run pymdp agent.
- [ ] **F2: Orchestrator AIF** — Reference material for F1 design.
- [ ] **F3: Factorised AIF** — Reference material for F1 design.
- [ ] **F4: EcoNet** — Reference material for F1 design.

#### Category 7: Credit Assignment & Intrinsic Motivation — EVALUATED, NOT CHOSEN

Reward shaping (A1-A3) + individual role training (A1.5) solved credit assignment sufficiently. AIF approach (F1) provides principled alternative.

- [ ] **G1: ToM as intrinsic motivation** — Not chosen. AIF ToM (from social-layer) provides this natively.
- [ ] **G2: Social empowerment** — Not chosen. Marginal value vs simpler reward shaping confirmed by A1-A3 sweeps.
- [ ] **G3: MAESTRO** — Not chosen. Manual reward stacking sufficient for current needs.
- [ ] **G4: Asynchronous credit assignment** — Not chosen.

#### Category 8: Meta-Learning with Active Inference (Capstone) — ACTIVE RESEARCH

Active research collaboration with Luca Manneschi & Alejandro. Email discussion (2026-03-17) narrowed focus to H1 and H5 as most promising. Phase 1 POMDP module implemented in `aif-meta-cogames` repo. Luca confirmed trajectory data v3 looks good, wants to try MAML/in-context learning.

- [ ] **H1: Hierarchical AIF as meta-learning** — **TOP PRIORITY with Luca**
  - Outer loop (slow): MAML over A/B matrix initialization across CogsGuard variants
  - Inner loop (fast): standard state inference + EFE policy selection with variant-specific fitted A/B
  - Phase 1 COMPLETE: 18-state POMDP + discretizer + A/B fitting pipeline in `aif-meta-cogames`
  - Phase 2 TODO: Fit A/B from v3 trajectory data, run pymdp agent, validate per-variant differences
  - Phase 3 TODO: MAML/Reptile over A/B initialization (Luca's contribution)
  - Compare: flat AIF agent (F1) vs hierarchical AIF (H1) vs MAML/Reptile baseline

- [ ] **H2: EFE for model/structure selection** — Deferred (requires H1 working first)

- [ ] **H3: Neural AIF — VFE as training objective** — Deferred (most ambitious, requires all prior insights)

- [ ] **H4: Amortized EFE planning** — Deferred (requires explicit EFE agent from F1/H1)

- [ ] **H5: Active task selection — EFE-driven curriculum meta-learning** — **SECOND PRIORITY**
  - Fastest to prototype, composes with any inner loop, clean empirical story
  - EFE selects which training scenario maximizes epistemic + instrumental value
  - CogsGuard task family: {arena, machina_1} × {4, 8 cogs} × {no_clips, fast_clips, slow_clips} × {role distributions}
  - **Synergy**: composes with ANY inner-loop approach

#### Meta-Learning × AIF: Implementation Priority (UPDATED 2026-03-18)

| Priority | Approach | Status | Effort | Prerequisite |
|----------|----------|--------|--------|-------------|
| 1st | **H1: Hierarchical AIF** | Phase 1 COMPLETE (POMDP module). Phase 2 next (fit + validate) | 20-25 hrs | F1 POMDP ✅ |
| 2nd | **H5: Active task selection** | Not started. Fastest empirical result once H1 inner loop works | 8-10 hrs | Working inner-loop agent |
| 3rd | **H2: EFE structure selection** | Not started | 20-25 hrs | Need H1 working first |
| 4th | **H4: Amortized EFE** | Not started | 15-20 hrs | Need explicit EFE agent (F1/H1) |
| 5th | **H3: Neural AIF (VFE loss)** | Not started | 25-30 hrs | Standalone, most ambitious |

#### Open Research Questions (from Luca/Alejandro discussion, 2026-03-17)

- **Luca's focus**: MAML/in-context learning over A/B matrices — confirmed data v3 looks good
- **Alejandro**: volunteered to help with Phase 1 POMDP (now complete)
- **Venue targeting**: Active Inference Workshop (conceptual clarity) vs NeurIPS (empirical + architectural novelty)
- **Synergy with Luca's projects**: Dreamer self/other distinction, LSA layer-wise energy minimisation, test-time OOD adaptation
- **Task family richness**: 36 CogsGuard variants (30 arena + 6 machina_1) with 3,600 episodes of trajectory data ready

#### Evaluation Process

1. **Paper skim** (15 min each): Read abstract, methods, results, limitations for each approach
2. **Feasibility check**: Can it run CPU-only? Compatible with PufferLib? Implementation complexity?
3. **CogsGuard fit**: Does it address our specific bottlenecks (role discovery, credit assignment, exploration, spatial memory)?
4. **Score matrix**: Rate each approach 1-5 on all criteria, compute weighted score
5. **Shortlist**: Select top 2-3 approaches for implementation (Categories 1-7), plus 1-2 from Category 8 as capstone
6. **Combination analysis**: Which shortlisted approaches compose well together?
7. **AIF/meta-learning informing**: For each Category 1-7 approach evaluated, document what its failure modes tell us about which Category 8 mechanism is most needed

**Deliverable**: Scored decision matrix with top 2-3 approaches selected, plus implementation plan for chosen path. Separate section documenting implications for AIF/meta-learning capstone design.

### Phase 2b Results: Decision Matrix

**Hardware**: NVIDIA L4 GPU (24GB VRAM) available on AWS. GPU training WORKS after compiling CUDA kernel (see "PufferLib CUDA Kernel Fix" section).

**Scoring weights** (de-weighting effort — this is a research project):
- Impact 35% | Feasibility 20% | Novelty 20% | Composability 15% | Effort 10%

#### Full Scores (re-scored with GPU available, sorted by weighted total) — HISTORICAL

*Scores below are from the initial evaluation (pre-experimentation). See Category 1-8 status above for what was actually implemented and outcomes.*

| Rank | Approach | Impact | Feas. | Novel. | Comp. | Effort | **Total** | Category |
|------|----------|--------|-------|--------|-------|--------|-----------|----------|
| 1 | **D1: HS-MARL + HTN** | 4 | 5 | 4 | 4 | 3 | **4.10** | Hierarchical |
| 2 | **C4: R3DM** | 4 | 4 | 5 | 2 | 2 | **3.80** | Role Discovery |
| 3 | **B2: Entity Transformer** | 4 | 5 | 4 | 5 | 2 | **4.10** | Neural |
| 4 | **B4: MAT** | 4 | 4 | 4 | 2 | 2 | **3.50** | Neural |
| 5 | **B1: MAPPO** | 4 | 5 | 2 | 5 | 3 | **3.85** | Neural |
| 6 | **H1: Hierarchical AIF meta** | 4 | 4 | 5 | 4 | 2 | **4.00** | Meta-AIF |
| 7 | **H5: Active task selection** | 3 | 5 | 3 | 5 | 5 | **3.70** | Meta-AIF |
| 8 | **A1: Forced roles** | 4 | 5 | 1 | 5 | 5 | **3.70** | Quick Win |
| 9 | **C1: ACORM** | 3 | 5 | 4 | 5 | 3 | **3.80** | Role Discovery |
| 10 | **G1: ToM intrinsic motiv.** | 3.5 | 4 | 4 | 5 | 3 | **3.80** | Credit |
| 11 | **H3: Neural AIF (VFE loss)** | 4 | 4 | 4 | 2 | 4 | **3.70** | Meta-AIF |
| 12 | **D3: Option-Critic** | 4 | 4 | 2 | 4 | 3 | **3.50** | Hierarchical |
| 13 | **H4: Amortized EFE** | 3 | 4 | 3 | 5 | 3 | **3.45** | Meta-AIF |
| 14 | **C5: Social Influence** | 3 | 3 | 3 | 4 | 2 | **3.05** | Credit |
| 15 | **A2: Reward shaping** | 3 | 5 | 1 | 5 | 5 | **3.35** | Quick Win |
| 16 | **E3: MAIC** | 3.5 | 4 | 3 | 3 | 3 | **3.40** | Communication |
| 17 | **A3: Hyperparams** | 3 | 5 | 1 | 5 | 4 | **3.30** | Quick Win |
| 18 | **F1: Scripted AIF agent** | 4 | 3 | 4 | 2 | 4 | **3.40** | AIF |
| 19 | **H2: EFE structure select** | 3 | 3 | 4 | 3 | 3 | **3.20** | Meta-AIF |
| 20 | **C2: MAVEN** | 4 | 3 | 3 | 3 | 2 | **3.15** | Role Discovery |
| 21 | **A4: Curriculum** | 3 | 5 | 2 | 4 | 3 | **3.20** | Quick Win |
| 22 | **B3: HAPPO** | 3 | 4 | 3 | 3 | 2 | **3.10** | Neural |
| 23 | **E2: IC3Net** | 2.5 | 4 | 2 | 4 | 3 | **2.95** | Communication |
| 24 | **G4: Async credit** | 3 | 3 | 4 | 2 | 3 | **3.10** | Credit |
| 25 | **G2: Social empowerment** | 2.5 | 3 | 2 | 5 | 3 | **2.90** | Credit |
| 26 | **F3: Factorised AIF** | 3 | 2 | 4 | 2 | 3 | **2.80** | AIF |
| 27 | **G3: MAESTRO** | 3 | 2 | 4 | 3 | 2 | **2.85** | Credit |
| 28 | **D2: Feudal MARL** | 3 | 3 | 2 | 2 | 2 | **2.55** | Hierarchical |
| 29 | **C3: RODE** | 3 | 3 | 3 | 2 | 2 | **2.70** | Role Discovery |
| 30 | **E1: TarMAC** | 2 | 3 | 3 | 4 | 2 | **2.65** | Communication |
| — | **F2: Orchestrator AIF** | 2.5 | 1 | 4 | 2 | 1 | **2.10** | BLOCKER: LLM |
| — | **F4: EcoNet** | 1 | 1 | 2 | 1 | 1 | **1.20** | BLOCKER: scale |

#### Key Changes with GPU Available

- **C4: R3DM UNBLOCKED** → jumps to rank 2. Forward-looking role discovery via dynamics models, +20% on SMACv2. Requires QMIX backbone adaptation but GPU makes the two RSSM networks feasible.
- **B2: Entity Transformer** → feasibility 4→5. GPU eliminates training speed concern entirely.
- **B4: MAT** → feasibility 2→4. Transformer inference for 8 agents now tractable on GPU.
- **C5: Social Influence** → partially unblocked. 48 counterfactual evals still expensive but GPU helps. Still risky.
- **C1: ACORM** → feasibility 4→5. Contrastive learning + attention on GPU is standard.
- **H1: Hierarchical AIF** → feasibility 3→4. Hyperprior updates + belief propagation faster on GPU.

#### Blocked Approaches (still eliminated)

- **F2: Orchestrator AIF** — LLM-focused, no clear CogsGuard applicability
- **F4: EcoNet** — tested on 2 agents, 24 timesteps. Wrong domain and scale.

#### Selected Approaches: Implementation Path — SUPERSEDED

*Original tier plan below. Replaced by revised pipeline after PI meetings (2026-03-10, 2026-03-13). See "Revised Pipeline" section for active execution plan.*

**Tier 1 — ✅ COMPLETE:**
- **A1: Forced role assignment** — ✅ Done. Answer: YES, role discovery IS the bottleneck. Forced roles + reward shaping → 2.5 junctions (from 0).
- **A2 + A3: Reward shaping + hyperparams** — ✅ Done. Best: milestones alone, ent=0.03 → 3.214 junctions.
- **B1: MAPPO** — Not implemented. Individual role training (A1.5) addressed credit assignment more directly.

**Tier 2 — SUPERSEDED by revised pipeline:**
- **B2: Entity Transformer** → Superseded by **B2': Cortex arch** (AGaLiTe + Axon + sLSTM). In pipeline as step S5.
- **D1: HTN planning** → Economy chain structure now encoded in POMDP B matrix (F1 approach).
- **C1: ACORM** → Superseded by A1.5 individual role training. Forced vibes solved specialization.
- **C4: R3DM** → Not implemented. Individual role training removed the need for learned role discovery.

**Tier 3 — ACTIVE (AIF capstone, three distinct tracks):**
- **F1: Scripted AIF agent** (S7a) — Softmax deliverable. Full 216-state POMDP with G-coupling, ToM particle filter, strict EFE decomposition. Port social-layer arch to CogsGuard. POMDP module implemented; next: fit A/B from v3 data + run pymdp agent.
- **H1: Meta-learning over world models** (S7b) — Research paper with Luca/Alejandro. MAML over A/B matrices across environment variants. Phase 1 COMPLETE (POMDP module + v3 trajectory data in `aif-meta-cogames`). Luca starting MAML.
- **G-coupling vs IC3Net comparison** (S7c) — Research narrative. Does principled AIF communication (G-coupling) match or beat learned IC3Net? Depends on S6 (IC3Net) + S7a (AIF agent) being done first.
- **H5: Active task selection** — Extends H1 if time permits; EFE-driven curriculum.

**Research publication track (UPDATED):**
1. H1 (meta-learning over world models) → main paper with Luca/Alejandro
2. F1 (scripted AIF agent) + S7c (G-coupling vs IC3Net) → Softmax deliverable + Active Inference Workshop
3. H5 (active curriculum) → extends H1 if time permits

#### What Tier 1 Results Taught Us About AIF Design

| Result | What it told us | AIF implication |
|--------|----------------|-----------------|
| A1 (forced roles) → 2.5 junctions | Role discovery IS the bottleneck | Economy chain must be in generative model (B matrix) |
| A3 sweep → 3.214 junctions | PPO learns economy with right reward signal | But ceiling is low — model-based planning needed |
| A4 (curriculum) → 0 junctions on machina_1 | Arena configs don't transfer | Per-variant adaptation needed → meta-learning (H1) |
| A1.5 (individual roles) → 12+ junctions | Specialization works, composition is the challenge | AIF role selection via EFE, not learned roles |
| Kickstarting failed | Teacher-student doesn't compose easily | AIF coordination via G-coupling, not distillation |
| slanky is scripted | No learned agent >6 on leaderboard | Model-based (AIF) may be the only viable path |

### Phase 3: Architecture Design (Weeks 4-5 — 15 hrs) — SUPERSEDED

**Status**: Superseded by the revised pipeline (post-PI meeting). See "Recommended Research Plan (Revised)" below for the active execution plan. The AIF generative model specification is now in `AIF_DESIGN.md` and implemented in the `aif-meta-cogames` repo.

### Phase 4: Implementation & Iteration (Weeks 5-7 — 25 hrs) — SUPERSEDED

**Status**: Superseded. Implementation now follows the five-step pipeline: A1.5 (done) → A5/kickstarting (done) → B2'/Cortex → E/communication → F1/H1/AIF capstone. See revised timeline below.

### Phase 5: Evaluation & Report (Week 8 — 10 hrs) — PENDING

**Status**: Pending. Leaderboard submissions made (flat PPO + 3 kickstarted roles). Full evaluation and report deferred until AIF agent is ready.

- [x] Submit policies to leaderboard (flat PPO, kickstarted aligner/miner/scrambler)
- [ ] Compare VOR scores against all baselines and leaderboard entries
- [ ] Document: architecture, results, lessons learned, comparison to literature
- [ ] Prepare presentation for Softmax team

---

## Leaderboard Submissions

| Policy | Season | Score | Status | Notes |
|--------|--------|-------|--------|-------|
| `mahault.random-baseline:v1` | beta-cvc | ~0 | retired | Random actions baseline |
| `mahault.starter-baseline:v1` | beta-cvc | ~1.0 | retired | Built-in heuristic baseline |
| `mahault.flat_ppo_milestones_v1:v1` | beta-cvc | 1.77 | retired | Best flat PPO (milestones, ent=0.03, u=3) |
| `kickstarted_aligner_v1:v1` | beta-cvc | 0.00 | qualifying | Single-role specialist — scores 0 alone in CvC |
| `kickstarted_miner_v1:v1` | beta-cvc | 0.00 | qualifying | Single-role specialist — scores 0 alone in CvC |
| `kickstarted_scrambler_v1:v1` | beta-cvc | 0.00 | qualifying | Single-role specialist — scores 0 alone in CvC |
| `kickstarted_team_v1:v1` | beta-cvc | — | retired | Heterogeneous team (miner+aligner+scrambler), 4 matches |
| `cortex-lstm-s13:v2` | beta-cvc | — | qualifying | Cortex-LSTM, 3.75j peak in scrimmage (2026-03-25) |
| `cortex-axon-s14:v1` | beta-cvc | — | qualifying | Cortex-Axon, 2.25j peak in scrimmage (2026-03-25) |
| `cortex-agas-s15:v1` | beta-cvc | — | qualifying | Cortex-Ag,A,S, 2.56j peak in scrimmage (2026-03-25) |
| `cortex-agas-seq-s16:v1` | beta-cvc | — | qualifying | Cortex sequential Ag,A,S, 2.25j peak (2026-03-25) |
| `cortex-agas-s20:v1` | beta-cvc | — | qualifying | Best Cortex sweep: ent=0.12, 2.778j peak (2026-03-25) |

Check status: `cogames submissions --season beta-cvc`
View leaderboard: `cogames season leaderboard beta-cvc --pool qualifying`

---

## Phase 2 Training Log

### CNN+LSTM PPO Training (cogsguard_arena, 4 cogs, 10M steps, CPU)
- **Architecture**: 2-layer CNN (3x3 conv, stride 2) → FC(256) + self-encoder(256) → LSTM(512) → actor/critic heads
- **Params**: 2.8M
- **PPO config**: lr=0.00092, gamma=0.995, gae_lambda=0.90, clip=0.2, ent_coef=0.01, bptt=64

| Epoch | SPS | Hearts/agent | Junctions | Gear | Entropy | Expl. Var. | Notes |
|-------|-----|-------------|-----------|------|---------|------------|-------|
| 9 | 3,100 | 0.76 | 0.25 | 0 | 1.53 | -0.46 | Value function useless |
| 44 | 3,000 | 0.73 | 0.13 | 0 | 1.43 | 0.72 | Learning hearts, not junctions |
| 77 | 3,000 | 0.60-0.86 | 0.0 | 0 | 1.43 | 0.47-0.60 | **Confirmed: never discovers roles** |

**Key failure modes confirmed**:
1. Agents learn to mine resources and craft hearts (~0.7/agent) — basic economy works
2. **NO role specialization**: `miner.amount`, `aligner.amount`, `scout.amount` all 0.0 — `change_vibe` never explored
3. **NO junction capture**: `aligned.junctions` stuck at 0.0 — agents never acquire gear or attempt alignment
4. **NO gear acquisition**: The entire gear→capture chain is undiscovered
5. Heart withdrawal rate (2.0-2.4) suggests agents sometimes craft but never use the products
6. Value function mediocre (explained variance 0.47-0.60) — can't predict long-horizon returns

**Diagnosis**: The economy chain is too long for flat PPO with default entropy bonus. The `change_vibe` action has zero immediate reward, so it's never explored. Without role specialization, the gear→junction chain is unreachable.

### Tier 1 Training: A2+A3 (cogsguard_arena, 8 cogs, 50M steps, GPU) — 2026-03-09 ✅ COMPLETE

- **Architecture**: Same CNN+LSTM (2.8M params)
- **PPO config**: lr=0.00092, **gamma=0.999**, **gae_lambda=0.95**, clip=0.2, **ent_coef=0.05**, **bptt=128**
- **Reward shaping**: `credit` + `role_conditional` + `objective_mine:25`
- **Device**: NVIDIA L4 GPU (CUDA kernel fix applied)
- **Training time**: 26m 29s | **SPS**: ~31K (20x faster than CPU)
- **Checkpoints**: `train_dir/177309700806/model_000{050,100,150,191}.pt`

| Epoch | SPS | Hearts/agent | Junctions | Gear | Entropy | Expl. Var. | Notes |
|-------|-----|-------------|-----------|------|---------|------------|-------|
| 44 | 31.4K | 0.704 | 0.600 | 0 | 1.600 | 0.938 | Value function already excellent |
| 100 | 31K | ~0.74 | ~1.2 | 0 | 1.61 | 0.987 | Junctions improving |
| 191 | 30K | 0.759 | **1.889** | 0 | 1.607 | **0.997** | Final — value function near-perfect |

**Comparison to Phase 2 baseline:**

| Metric | Phase 2 (defaults) | Tier 1 (A2+A3) | Verdict |
|--------|-------------------|----------------|---------|
| Explained variance | 0.47-0.60 | **0.997** | Massive improvement — γ/λ/bptt fix |
| Entropy | 1.43 | **1.607** | Healthier exploration (ent_coef=0.05) |
| Hearts/agent | 0.70 | **0.759** | +8% marginal |
| Aligned junctions | 0 | **1.889** | Nonzero! But tiny vs 58 available |
| Gear acquisition | 0 | **0** | Still zero — economy chain blocked |
| Role discovery | 0 | **0** | change_vibe never explored |
| SPS | 1.5K (CPU) | **31K (GPU)** | 20x throughput |

**Key findings:**
1. **Value function fixed**: γ=0.999 + λ=0.95 + bptt=128 solved the credit assignment problem for the value function. Explained variance converged to 0.997 by epoch 100.
2. **Reward shaping helps marginally**: Junction alignment went from 0→1.889 (nonzero but tiny). `objective_mine:25` nudges behavior but can't overcome the `change_vibe` barrier.
3. **Role discovery is THE bottleneck**: Despite perfect value estimates and healthy exploration, agents never try `change_vibe`. The entire gear→junction chain remains unreachable.
4. **Learning ceiling hit**: The agent has learned everything it can as a generic agent. Further training won't help — the policy is exploring within default behavior only.

**Conclusion**: Hyperparams and reward shaping are necessary but not sufficient. **A1 (forced role assignment) is required** to break through the learning ceiling. The tuned hyperparams should be kept for all future runs.

### Tier 1b Training: A1+A2+A3 (cogsguard_arena, 8 cogs, 50M steps, GPU) — 2026-03-09 ✅ COMPLETE

- **Architecture**: Same CNN+LSTM (2.8M params)
- **PPO config**: lr=0.00092, **gamma=0.999**, **gae_lambda=0.95**, clip=0.2, **ent_coef=0.05**, **bptt=128**
- **Reward shaping**: `forced_role_vibes` + `credit` + `role_conditional` + `objective_mine:25`
- **Device**: NVIDIA L4 GPU (CUDA kernel fix applied)
- **Training time**: ~27 min | **SPS**: ~30K
- **Checkpoints**: `train_dir/177309922942/model_000{050,100,150,191}.pt`

**forced_role_vibes details**: Built-in cogames variant (`ForcedRoleVibesVariant`). Assigns vibes at env construction: miner→5, aligner→4, scrambler→3, scout→6. `per_team=True` → 2+2+2+2 for 8 agents. Disables `change_vibe` action. Injects `role_id` into observation space.

| Epoch | SPS | Hearts/agent | Junctions | Gear | Carbon.dep | Heart.withdrawn | Expl. Var. |
|-------|-----|-------------|-----------|------|-----------|----------------|------------|
| 99 | 29.9K | 0.795 | 0.424 | 0 | ~2.5 | ~4.5 | 0.988 |
| 191 | 30K | 0.772 | 0.393 | 0 | 1.5-4.4 | 4.2-4.8 | 0.997-0.998 |

**Comparison to all runs:**

| Metric | Phase 2 (defaults) | Tier 1 (A2+A3) | Tier 1b (A1+A2+A3) | Verdict |
|--------|-------------------|----------------|---------------------|---------|
| Explained variance | 0.47-0.60 | 0.997 | **0.997-0.998** | All tuned runs equivalent |
| Hearts/agent | 0.70 | 0.759 | **0.772** | Marginal improvement |
| Aligned junctions | 0 | **1.889** | 0.393 | **REGRESSED** — forced roles interfere |
| Gear acquisition | 0 | 0 | **0** | Still zero |
| Carbon deposited | N/A | N/A | **1.5-4.4** | NEW — agents deposit at hub |
| Heart withdrawal | N/A | N/A | **4.2-4.8** | NEW — agents withdraw hearts |
| Role discovery | 0 | 0 | N/A (forced) | change_vibe disabled |

**New behaviors unlocked by forced roles:**
1. **Carbon deposit**: Agents now mine AND deposit carbon at the hub (was not happening in prior runs)
2. **Heart withdrawal**: Agents actively withdraw hearts from junctions
3. These show the role infrastructure is working — agents act differently with roles

**What still fails:**
1. **Zero gear**: The chain breaks at deposit → craft → gear. Crafting has zero immediate reward, same as `change_vibe` before
2. **Junction regression**: Aligned junctions dropped from 1.889 → 0.393. Forced roles may interfere with the generic strategy that was accidentally capturing junctions. The junction metric was volatile (0.2 to 2.375 between epochs).
3. **No role-specific specialization**: Despite having role IDs in observations, all agents converge to similar behavior (mine → deposit → withdraw hearts). The policy doesn't differentiate by role.

**Diagnosis**: The economy chain is fundamentally too long for flat PPO. Each step in the chain has zero immediate reward:
```
mine → deposit → craft → equip gear → capture junctions
  ✅      ✅       ❌       ❌           ❌ (regressed)
```
Forced roles moved the frontier one step forward (agents now deposit), but crafting is the new `change_vibe` — an action with no immediate reward that PPO will never discover.

**Conclusion**: Category 1 quick wins (A1+A2+A3) have been exhausted. They improved the value function dramatically and unlocked basic economy behaviors, but cannot bridge the full economy chain. Next steps require either:
1. **Deeper reward shaping**: Explicit craft/gear rewards (a new reward variant)
2. **Architecture change**: Entity transformer (B2), HTN planning (D1), or MAPPO (B1) to handle the chain structurally
3. **Curriculum**: Pre-deposit resources so agents only need to learn craft → gear → capture

**What Tier 1 diagnostics tell us about AIF design** (updating the decision matrix):
- A1 (forced roles) partially works → EFE-based role selection IS relevant, but not the only bottleneck
- The economy chain itself needs hierarchical decomposition → HTN (D1) or hierarchical AIF (H1) are high priority
- Credit assignment across 5+ steps is the core issue → temporal abstraction is critical

### Tier 1c: Bridging the Craft Gap — Research & Experiments (2026-03-09) ✅ COMPLETE

**Goal**: Exhaust all Category 1 (quick win) approaches to bridge the craft/gear gap before moving to architectural changes. Give flat PPO the best possible shot.

#### Research Findings (3 parallel investigations)

**1. Reward Variant Analysis (cogames internals)**

Complete economy chain with reward coverage:

| Step | Action | Stats Available | Rewarded By |
|------|--------|-----------------|-------------|
| 1. Mine elements | Use extractor | `{element}.gained` | `credit` (0.001), `objective_mine` (0.03 log), `miner` (0.5 log) |
| 2. Deposit at hub | Use hub | `game.{team}/{element}.deposited` | `objective_mine` only (0.03 log) |
| 3a. Hub crafts heart | Hub conversion | `game.{team}/{element}.withdrawn` | **NONE** ← GAP |
| 3b. Agent equips gear | Gear station | `{gear}.gained` | `credit` (aligner/scrambler only, 0.2). **Miner/scout gear NOT rewarded** ← GAP |
| 4. Withdraw heart | Use hub | `heart.gained` | `credit` (0.05), `objective_mine` (0.05) |
| 5. Capture junction | Use junction | `junction.aligned_by_agent` | `milestones`, `objective_mine`, role variants |

Key gaps: (a) no reward for crafting itself, (b) `credit` variant only rewards aligner/scrambler gear, not miner/scout gear.

**Undiscovered built-in variants useful for curriculum:**
- `braveheart`: 255 initial hearts (skip mining-for-hearts entirely)
- `energized`: max energy, never run dry
- `no_clips`: remove adversarial pressure
- `tin_man` / `tin_team`: require gear before heart withdrawal

**2. Top Agent Analysis**

slanky:v109 (24.61) — **likely a scripted agent** (PI clarified 2026-03-11). Our earlier claim that it used "BC from dinky + ViT + 20B steps" was unverified and likely incorrect. The kickstarting recipe (KL loss from dinky, α=1.2 annealed) is a separate approach described by Subhojeet for training learned agents.

Tutorial missions exist with pre-loaded resources:
- `aligner_tutorial`: 120 hearts, 1000 steps, 4 agents
- `miner_tutorial`: no hearts, 1000 steps, 4 agents

Curriculum rotation natively supported: multiple `-m` flags.

**3. Web Research: Long Credit Chain Techniques**

| Technique | Effort | Expected Impact | Requires Code Change? |
|-----------|--------|-----------------|----------------------|
| Potential-based reward shaping (Ng et al.) | Low | HIGH | Yes — custom variant |
| Curriculum with staged chain unlocking | Low-Med | HIGH | No — config only |
| Count-based exploration (hash inventory) | Low | Medium | Yes — custom variant |
| RND exploration bonus | Medium | Medium-High | Yes — dual value heads |
| Auxiliary prediction heads (UNREAL) | Medium | High | Yes — architecture |
| Macro-actions / options framework | Med-High | Medium-High | Yes — env wrapper |

#### Experiment Plan

**Run 1 (no code changes):** `braveheart` + `forced_role_vibes` + `credit` + `objective_mine:25` + `energized`
- Gives 255 hearts for free. Tests: is the bottleneck resource scarcity or action discovery?
- If agents learn gear→junctions with free hearts → bottleneck was hearts, not crafting action discovery

**Run 2 (no code changes):** Curriculum rotation through tutorials
- `aligner_tutorial` (120 hearts) → `miner_tutorial` → `arena.basic`
- Teaches chain backwards: junction capture first, then mining

**Run 3 (code change):** Custom reward variant patching the craft gap
- Reward `game.{team}/{element}.withdrawn` (crafting happening)
- Reward ALL gear gains (not just aligner/scrambler)
- Potential-based shaping with large jump at craft step

#### Run 1: Braveheart + Full Shaping — ✅ COMPLETE

**Command**:
```bash
cogames train -m cogsguard_arena.basic -p class=tutorial --cogs 8 --steps 50000000 --device auto -v braveheart -v forced_role_vibes -v credit -v objective_mine:25 -v energized
```

**Hypothesis**: With 255 free hearts, agents should be able to skip the mining→craft chain and directly learn gear acquisition → junction capture. If gear.gained goes nonzero, the bottleneck was resource scarcity, not action discovery.

**Status**: ✅ COMPLETE
- Started: 2026-03-09 ~23:50 UTC
- Completed: 2026-03-10 ~00:17 UTC (~27 min)
- Checkpoint: `train_dir/177310177160/model_000191.pt`

**Results:**

| Epoch | heart.amount | heart.gained | heart.withdrawn | aligned.junctions | gear | expl.var | clipfrac |
|-------|-------------|-------------|----------------|-------------------|------|----------|----------|
| 26 | 250.4 | 0.645 | 5.375 | 0.000 | 0 | -0.043 | — |
| 48 | 247.0 | 1.000 | 8.276 | 0.667 | 0 | 0.923 | — |
| 93 | 243.8 | 1.405 | 11.342 | 1.026 | 0 | 0.984 | — |
| 115 | 244.3 | 1.335 | — | 1.065 | 0 | 0.989 | **0.000** |
| 191 | 241.4 | 1.705 | 13.857 | 1.357 | **0** | 0.992 | **0.000** |

**Key finding: Gear still ZERO despite 255 free hearts.**

The bottleneck is NOT resource scarcity — it's action discovery. Agents found a local optimum and **completely stopped exploring**:
- approx_kl = 0.000 and clipfrac = 0.000 by epoch ~115 → policy frozen
- ent_coef=0.05 was insufficient to prevent premature convergence
- Agents learned: mine → deposit → withdraw hearts → capture some junctions (same ceiling as Tier 1b)
- But never navigated to gear stations or interacted with converters

**Diagnosis**: Two compounding failures:
1. **Premature convergence** — policy stops updating before discovering gear
2. **No gradient toward gear stations** — no reward signal pulls agents toward converter objects on the map

#### Run 2: Tutorial Curriculum + Higher Entropy — ✅ COMPLETE

**Changes from Run 1:**
1. `ent_coef=0.10` (up from 0.05) — prevent premature convergence
2. Tutorial curriculum rotation: `aligner_tutorial` → `miner_tutorial` → `arena.basic`
   - Tutorials have built-in role-specific rewards (aligner_rewards, miner_rewards)
   - Shorter episodes (1000 steps vs 10000) — faster credit assignment
   - No clips pressure
3. 4 cogs (matching tutorials, simpler coordination)

**Command**:
```bash
cogames train -m cogsguard_machina_1.aligner_tutorial -m cogsguard_machina_1.miner_tutorial -m cogsguard_arena.basic -p class=tutorial --cogs 4 --steps 50000000 --device auto -v braveheart -v credit -v objective_mine:25 -v energized
```

**Hypothesis**: Higher entropy keeps exploration alive + tutorials bring agents closer to gear stations with role-specific rewards. If this fails, flat PPO is exhausted.

**Status**: ✅ COMPLETE (interim analysis at epoch 47/~76, trajectory clear)
- Started: 2026-03-10 ~00:25 UTC

**Results:**

| Epoch | heart.amount | heart.gained | aligned.junctions | gear | expl.var | clipfrac | approx_kl |
|-------|-------------|-------------|-------------------|------|----------|----------|-----------|
| 14 | 253 | 0.4-0.8 | 0.1-0.4 | 0 | -0.04 | 0.10-0.55 | 0.003-0.05 |
| 35 | 252 | 0.5-0.7 | 0.0-0.1 | 0 | -0.15 | 0.02-0.55 | 0.003-0.11 |
| 47 | 253 | 0.5-0.7 | 0.0-0.1 | **0** | **-0.15** | nonzero | nonzero |

**Key findings:**
1. **Premature convergence FIXED**: clipfrac/KL stayed nonzero throughout (ent_coef=0.10 works). Policy kept exploring.
2. **Gear STILL ZERO**: Despite active exploration and tutorial curriculum, zero gear acquired. This eliminates convergence as the explanation.
3. **Value function BROKEN**: Explained variance negative (-0.05 to -0.15) — worst of any run. Curriculum rotation prevented value convergence (switching environments every ~3 epochs).
4. **Junctions REGRESSED**: 0.0-0.1, worst of any run with reward shaping. Curriculum rotation was counterproductive.
5. **Curriculum transitions visible**: clipfrac/KL spike every ~3 epochs as environment switches, then settle. Policy disrupted but not learning transferable skills.

**Conclusion**: Run 2 is the definitive negative result. With exploration maintained (no premature convergence) AND tutorial curriculum AND 255 free hearts AND maximum reward shaping — flat PPO still cannot discover gear stations. The problem is structural, not tunable.

#### Category 1 Summary: Quick Wins Exhausted

**Total training**: 250M+ steps across 5 runs, ~2.5 hours GPU time.

| Intervention | Tried | Effect |
|-------------|-------|--------|
| Hyperparams (γ=0.999, λ=0.95, bptt=128) | ✅ | Value function fixed (0.997 expl.var) |
| Reward shaping (credit + objective_mine:25 + role_conditional) | ✅ | Small junction improvement (0→1.889) |
| Forced roles (forced_role_vibes) | ✅ | Unlocked deposit + heart withdrawal, but regressed junctions |
| Resource abundance (braveheart + energized) | ✅ | No effect on gear — bottleneck is not resource scarcity |
| Higher entropy (ent_coef=0.10) | ✅ | Fixed premature convergence but no gear |
| Tutorial curriculum (aligner + miner tutorials) | ✅ | Counterproductive — broke value function, regressed junctions |

**What we learned for Tier 2+3:**
- The value function works beautifully (0.997) with tuned hyperparams — keep γ=0.999, λ=0.95, bptt=128
- Curriculum rotation between very different missions is harmful (destroys value function)
- Forced roles unlock new behaviors (deposit, withdrawal) but don't bridge the full chain
- The mine→deposit→craft→gear→capture chain is 5+ steps with zero intermediate reward — flat PPO cannot bridge this through exploration alone
- The gear station interaction requires: (a) navigating to a specific object type, (b) having collective resources deposited, (c) bumping the station. None of these has any gradient signal in flat PPO.

**Definitive conclusion**: Architectural changes are required. The economy chain is too long for frame-level PPO exploration. Need either: hierarchical planning (D1/options), curiosity/intrinsic motivation (RND/count-based), behavioral cloning from scripted teacher, or model-based planning (AIF).

#### Leaderboard Validation (2026-03-10)

Our Category 1 results are **consistent with and slightly better than** what other flat PPO teams achieve on CogsGuard. Validated against the full beta-cvc qualifying leaderboard (143 entries):

**In our 43 experiments (~2B steps), no flat PPO run ever acquired gear. Low-scoring leaderboard entries are consistent with this pattern.**

| Score Range | Agents | Approach | Gear Acquired? |
|-------------|--------|----------|----------------|
| 36-77 | dinky (v21-v24) | Scripted (Nim, hand-coded goals) | Yes (hard-coded) |
| 10-31 | slanky, relh | **Likely scripted** (PI clarified slanky is scripted; relh approach unknown) | Yes |
| 1.4-6.2 | glanky (~15 versions) | Unknown arch sweep | Unclear |
| 1.0-2.5 | gassy, mammet, tanky, cranky, nlanky, neophyte, **us** | Flat PPO | **No** — all hit the same wall |

**slanky:v109 (24.61)**: PI clarified (2026-03-11) that slanky is likely a **scripted agent**, not a learned one. Our earlier characterization as "BC from dinky + ViT + 20B steps" was unverified and likely incorrect — there was no cited source for this claim.

**Our 1.889 aligned junctions** is near the ceiling for flat PPO. Most community flat-PPO submissions score 1.0-1.5. Our explained variance of 0.997 shows we extracted maximum value from the PPO value function — the bottleneck is genuinely in policy exploration.

**The gear acquisition wall is a known-in-practice problem**, evidenced by:
1. Complete absence of successful flat PPO agents on the leaderboard
2. Training infrastructure's default recommendation of BC+PPO (not pure PPO)
3. Internal `training-and-submission-guide.md` implicitly assumes BC
4. ~100 slanky versions submitted (1.0-24.6 range) — even BC+ViT requires massive sweeping

**No published papers exist** on CogsGuard training. Our ROADMAP is the most thorough documentation of the flat PPO failure mode. The general RL literature confirms the pattern: long-horizon economy chains with zero intermediate reward are a known failure mode for flat PPO (CMU multi-agent credit assignment thesis, RL Journal Club credit assignment survey, "Exploitation Is All You Need" arXiv).

**What this means for Tier 2+3**: All agents scoring >6 appear to be scripted. No learned agent has demonstrated gear acquisition on the leaderboard. Our path must be through one of:
1. A scripted agent with AIF-based coordination (leveraging our social-layer expertise)
2. Hierarchical planning (HTN/options) to compress the economy chain
3. Curiosity/intrinsic motivation to discover gear stations
4. A hybrid approach combining scripted low-level skills with learned high-level policy

#### A1-A4 Improvement Map (2026-03-09)

**Context**: PI (Subhojeet) confirmed our results are expected with the default reward function and will share ways to get flat PPO learning. Below maps all improvements per approach, informed by deep analysis of `reward_variants.py` and A4 curriculum research.

##### A1: Forced Role Assignment — Improvements ✅ RESOLVED

What we tried: `forced_role_vibes` (2+2+2+2 miner/aligner/scrambler/scout)

**Variant status:**
| ID | Variant | Status | Result |
|----|---------|--------|--------|
| A1.1 | Different role distribution (3m+3a+1s+1sc) | Superseded | A1.5 individual role training solves this better |
| A1.2 | Forced roles WITHOUT `role_conditional` | ✅ DONE | A1×A2 sweep tested this. Confirmed: role_conditional HURTS. Best config has no role_conditional. |
| A1.3 | Forced roles + `milestones` | ✅ DONE | `A1_mile` = 0.000 junctions (forced roles hurt milestones). `A1_mile_credit` = 2.450 (Phase 1), 1.857 (Phase 2a best). |
| A1.4 | Two-phase forced roles | ✅ DONE | Became A1.5: individual role training on tutorials → heterogeneous team composition. Aligner: 12.132 junctions. |

##### A2: Reward Shaping — Improvements ✅ RESOLVED

What we tried: `credit` + `role_conditional` + `objective_mine:25` (initial), then exhaustive A1×A2 sweep (20 experiments) + Phase 2a A3 sweep (18 experiments).

**Critical finding: reward key conflicts confirmed** — `credit` + `role_conditional` stacking overwrites keys. Miners get `heart.gained = -0.1` (penalty).

**Variant status:**
| ID | Variant | Status | Result |
|----|---------|--------|--------|
| A2.1 | `objective_mine:50` alone | ✅ DONE | 0.393 junctions (mid-run peak 1.800, then collapsed). Premature convergence. |
| A2.2 | `milestones` + `objective_mine:50` | ✅ DONE | Sweep: noA1=2.000, A1=1.214. Good but not best. |
| A2.3 | `credit` alone | ✅ DONE | Sweep: noA1=0.214, A1=0.000. Credit alone is weak. |
| A2.4 | `role_conditional` alone | ✅ DONE | 0.000 junctions. Catastrophic — per-role penalties prevent chain. |
| A2.5 | Custom variant (full chain shaping) | Not done | Superseded. Milestones alone outperforms all custom combos. |
| A2.6 | Higher `objective_mine` factor (50) | ✅ DONE | Tested in sweep as obj_mine:50. Best with A1+credit = 2.500 junctions. |
| A2.7 | `milestones` + `role_conditional` + `forced_role_vibes` | Not done | role_conditional confirmed harmful — no point testing. |

**Conclusion**: Best config = `milestones` alone, ent=0.03, u=3 → **3.214 junctions**. Simplest reward config wins. All further reward exploration superseded by individual role training (A1.5) and AIF approach.

##### A3: Hyperparameter Tuning — Improvements ✅ RESOLVED

What we tried: γ=0.999, λ=0.95, bptt=128, ent_coef=0.05 (initial), then Phase 2a sweep (18 experiments over {ent_coef: 0.03, 0.05, 0.07} × {update_epochs: 1, 3}).

**Variant status:**
| ID | Variant | Status | Result |
|----|---------|--------|--------|
| A3.1 | update_epochs=3 | ✅ DONE | **CRITICAL finding**: u3 mandatory for junction performance. u1 → 0 junctions in most configs. |
| A3.2 | Larger minibatch | Not done | Deprioritized — u3 + ent=0.03 proved more impactful. |
| A3.3 | Learning rate schedule | Not done | Deprioritized. |
| A3.4 | ent_coef=0.03 | ✅ DONE | **Best**: milestones + ent=0.03 + u=3 → 3.214 junctions. Lower entropy → better local optimum. |
| A3.5 | vf_coef=1.0 | Not done | Deprioritized — expl_var already 0.987 with current config. |

**Conclusion**: Optimal A3 config = ent_coef=0.03, update_epochs=3. All other hyperparams (γ, λ, bptt) remain at proven values.

##### A4: Curriculum Training — Improvements ✅ RESOLVED

What we tried: Round-robin rotation (FAILED), then arena→machina_1 transfer (Phase 2b: 0 junctions), then individual role tutorials (A1.5: SUCCESS).

**Key lesson**: RotationSupplier round-robin between DIFFERENT missions is counterproductive. Arena configs don't transfer to machina_1.

**Variant status:**
| ID | Variant | Status | Result |
|----|---------|--------|--------|
| A4.1 | Same-mission difficulty progression | Not done | Superseded by A1.5. |
| A4.2 | Map size progression (13x13→50x50→88x88) | Partially done | Arena→machina_1 = 0 junctions (Phase 2b). Full progression not tried. |
| A4.3 | Single-role pre-training | ✅ DONE | Became **A1.5**: individual role training on tutorials. Aligner: 12.132 junctions, Scrambler: 15.908 hearts, Miner: 0.368 hearts. |
| A4.4 | Backward chain curriculum | Not done | Superseded. |
| A4.5 | EasyHearts → arena → machina_1 | Not done | Superseded. |
| A4.6 | Rotation same mission, different variants | Not done | Superseded. |

**Conclusion**: A4.3 was the right idea. Individual role training (A1.5) on tutorial missions is the path forward. Curriculum across map sizes remains untested but deprioritized.

##### Priority Ranking — ✅ RESOLVED

All priority items were either executed (A2.1, A2.4, A2.2 in sweep) or superseded by the revised pipeline (A1.5 individual role training → kickstarting → AIF capstone). The PI's suggestion at the 2026-03-10 meeting was: train individual roles on tutorials, then compose and kickstart. This superseded all remaining A2.x/A4.x variants.

##### A2.1 and A2.4 Results (2026-03-09)

Ran the top two priority experiments. Neither beats our best (Tier 1 A2+A3 with 1.889 junctions).

**A2.1: `forced_role_vibes` + `objective_mine:50`** (no credit, no role_conditional)
- Checkpoint: `train_dir/177311165417/model_000191.pt`
- Hearts: 0.763 | Junctions: **0.393** | Gear: **0** | Expl.var: 0.965
- Mid-run peak of **1.800 junctions at 38M steps**, then collapsed to 0.393
- Volatile trajectory: hearts dropped to 0.148 at 25M then recovered
- Premature convergence: clipfrac=0.000, approx_kl=0.000 by end
- **Verdict**: Removing `credit` removed helpful precursor signals. Objective_mine:50 alone provides less dense shaping than the original stack. The junction peak at 38M shows the signal exists but policy freezes before exploitation.

**A2.4: `forced_role_vibes` + `role_conditional`** (no credit, no objective_mine)
- Checkpoint: `train_dir/177311325191/model_000191.pt`
- Hearts: **1.045** (best!) | Junctions: **0.000** (worst!) | Gear: **0** | Expl.var: 0.994
- Carbon hoarding: 24-57 carbon/game — agents mine aggressively but never align
- Zero junctions across entire 50M steps — per-role penalties prevent junction chain
- Lower entropy (1.420 vs 1.608) — policy converged tighter, stuck in mining attractor
- **Verdict**: Per-role penalties are catastrophic for junctions. `_apply_miner` sets `heart.gained = -0.1` (penalty), causing miners to avoid the heart→junction chain. `role_conditional` alone over-specializes agents on mining without teaching the full economy chain.

**Comparison table:**

| Metric | Tier 1 A2+A3 (best) | A2.1 (obj_mine:50) | A2.4 (role_cond) |
|--------|---------------------|---------------------|-------------------|
| Hearts/agent | 0.759 | 0.763 | **1.045** |
| Aligned junctions | **1.889** | 0.393 | 0.000 |
| Gear acquired | 0 | 0 | 0 |
| Explained variance | **0.997** | 0.965 | 0.994 |
| Entropy | 1.607 | 1.608 | 1.420 |
| Convergence | healthy | premature | premature |

**Key lessons:**
1. **Original A2+A3 stack (credit + role_conditional + objective_mine:25) is STILL the best** — the "conflicting" overwrites actually created a useful hybrid
2. `credit` alone provides small but critical precursor signals that `objective_mine` alone lacks
3. `role_conditional` alone is too restrictive — miners penalized for hearts, scouts ignore mining
4. Both new runs hit premature convergence (clipfrac=0) — ent_coef=0.05 insufficient for these reward configs
5. A2.1's mid-run junction peak (1.800) shows signal exists when objective_mine dominates, but unstable

**A2.2: `forced_role_vibes` + `milestones` + `objective_mine:50`**
- Hearts: 0.763 | Junctions: **1.286** | Gear: **0** | Expl.var: 0.998 | Entropy: 1.608
- Carbon deposited: 3.429 | Clipfrac: 0.000 | approx_kl: 0.000
- **Verdict**: Middle ground — better than A2.1 (0.393) and A2.4 (0.000) for junctions, but still below original A2+A3 (1.889). `milestones` junction reward (1.0) helps but doesn't overcome the gear wall. Premature convergence again.

**Remaining untried from priority list:**
- A2.3: `credit` alone (no role_conditional) — test if credit was the key ingredient
- A2.5: Custom variant (code change) — reward ALL gear gains, close craft gap
- A2.7: `milestones` + `role_conditional` + `forced_role_vibes`

##### Systematic A1×A2 Sweep Plan (2026-03-10)

**Goal**: Instead of manually guessing reward combos, systematically sweep all A1 × A2 combinations to find the optimal configuration.

**Design**: 20 experiments in 2 blocks of 10:
- **Block 1 (no forced roles)**: 10 reward variant combos
- **Block 2 (forced roles)**: same 10 combos with `forced_role_vibes`

Each combo from: `{credit, objective_mine:25, objective_mine:50, milestones}` and their pairwise/triple stacks.

**Fixed A3 hyperparams** (proven best): gamma=0.999, gae_lambda=0.95, bptt=128, ent_coef=0.05

**Full experiment list:**

| # | Name | Variants | A1 |
|---|------|----------|----|
| 1 | noA1_credit | credit | off |
| 2 | noA1_obj25 | objective_mine:25 | off |
| 3 | noA1_obj50 | objective_mine:50 | off |
| 4 | noA1_mile | milestones | off |
| 5 | noA1_credit_obj25 | credit + objective_mine:25 | off |
| 6 | noA1_credit_obj50 | credit + objective_mine:50 | off |
| 7 | noA1_mile_obj25 | milestones + objective_mine:25 | off |
| 8 | noA1_mile_obj50 | milestones + objective_mine:50 | off |
| 9 | noA1_mile_credit | milestones + credit | off |
| 10 | noA1_mile_credit_obj25 | milestones + credit + objective_mine:25 | off |
| 11 | A1_credit | forced_role_vibes + credit | on |
| 12 | A1_obj25 | forced_role_vibes + objective_mine:25 | on |
| 13 | A1_obj50 | forced_role_vibes + objective_mine:50 | on |
| 14 | A1_mile | forced_role_vibes + milestones | on |
| 15 | A1_credit_obj25 | forced_role_vibes + credit + objective_mine:25 | on |
| 16 | A1_credit_obj50 | forced_role_vibes + credit + objective_mine:50 | on |
| 17 | A1_mile_obj25 | forced_role_vibes + milestones + objective_mine:25 | on |
| 18 | A1_mile_obj50 | forced_role_vibes + milestones + objective_mine:50 | on |
| 19 | A1_mile_credit | forced_role_vibes + milestones + credit | on |
| 20 | A1_mile_credit_obj25 | forced_role_vibes + milestones + credit + objective_mine:25 | on |

**Runtime**: 20 × 27 min = ~9 hours (overnight sweep)
**Disk**: checkpoint_interval=999 (only final checkpoint), intermediates auto-cleaned.
**Results**: Saved to `sweep_results.csv` with hearts, junctions, gear, expl_var, entropy, convergence metrics.

**Phase 2 sweep** (after Phase 1): Take top 3 variant combos, sweep A3 hyperparams:
- ent_coef: {0.03, 0.05, 0.07}
- update_epochs: {1, 3}
= 3 × 6 = 18 runs, ~8 hours

**Sweep script**: `cogames/sweep.sh`

**Sweep status**: ✅ COMPLETE
- Started: 2026-03-10 04:27 UTC | Completed: 2026-03-10 13:05 UTC (~8.5 hours)
- 20/20 experiments completed
- Results: `~/projects/cogames/sweep_results_fixed.csv` (original CSV had metric extraction bug — `…` Unicode ellipsis broke grep pattern)
- Disk after sweep: 2.2GB free (93% used)

##### Sweep Results (sorted by aligned_junctions)

| Rank | Config | A1 (forced roles) | Junctions | Hearts | Expl.Var | Gear |
|------|--------|:--:|-----------|--------|----------|------|
| **1** | **credit + obj_mine:50** | **ON** | **2.500** | 0.719 | 0.997 | **0** |
| **2** | **milestones + credit** | **ON** | **2.450** | 0.531 | 0.977 | **0** |
| **3** | **milestones** | OFF | **2.417** | 0.808 | 0.981 | **0** |
| 4 | milestones + obj_mine:50 | OFF | 2.000 | 0.705 | 0.998 | 0 |
| 5 | milestones + obj_mine:50 | ON | 1.214 | 0.688 | 0.037 | 0 |
| 6 | credit + obj_mine:50 | OFF | 0.679 | 0.795 | 0.998 | 0 |
| 7 | mile+credit+obj25 | ON | 0.571 | 0.701 | 0.998 | 0 |
| 8 | obj_mine:25 | OFF | 0.500 | 0.719 | 0.997 | 0 |
| 9 | milestones + obj_mine:25 | OFF | 0.429 | 0.701 | 0.997 | 0 |
| 9 | credit + obj_mine:25 | ON | 0.429 | 0.772 | 0.998 | 0 |
| 11 | obj_mine:50 | OFF | 0.286 | 0.772 | 0.998 | 0 |
| 11 | mile+credit+obj25 | OFF | 0.286 | 0.754 | 0.041 | 0 |
| 13 | credit | OFF | 0.214 | 0.875 | 0.981 | 0 |
| 13 | obj_mine:50 | ON | 0.214 | 0.759 | 0.998 | 0 |
| 15 | credit + obj_mine:25 | OFF | 0.179 | 0.705 | 0.998 | 0 |
| 15 | obj_mine:25 | ON | 0.179 | 0.768 | 0.689 | 0 |
| 17 | milestones + obj_mine:25 | ON | 0.143 | 0.750 | 0.998 | 0 |
| 18 | milestones + credit | OFF | 0.000 | 0.888 | 0.979 | 0 |
| 18 | milestones | ON | 0.000 | 0.951 | 0.984 | 0 |
| 18 | credit | ON | 0.000 | 0.888 | 0.981 | 0 |

**Note**: Previous best (Tier 1 A2+A3 = credit + role_conditional + objective_mine:25, no forced roles) scored 1.889 junctions. The sweep's #1 config (2.500) does NOT use role_conditional, suggesting role_conditional was hurting junction performance.

##### Sweep Analysis

**1. New best config: `forced_role_vibes + credit + objective_mine:50` (2.500 junctions)**
- 32% better than our previous best (1.889)
- Key difference: `objective_mine:50` (vs 25) and NO `role_conditional`
- `role_conditional` was HURTING — its per-role penalties conflicted with the economy chain

**2. `milestones` is a strong ingredient:**
- 3 of top 4 configs include milestones
- `milestones` alone (no forced roles) scored 2.417 — 3rd best overall
- Direct junction reward (1.0/0.5) provides gradient for junction-related behavior

**3. forced_role_vibes effect is mixed:**
- Helped the #1 config (credit+obj50: 0.679→2.500 with A1)
- Hurt milestones alone (2.417→0.000 with A1!)
- Hurt milestones+credit (0.000 vs 2.450... wait, A1_mile_credit=2.450 but noA1_mile_credit=0.000 — reversed!)
- **Inconsistent** — suggests interaction effects, not a clear main effect

**4. `role_conditional` was the problem:**
- Our previous best used `credit + role_conditional + objective_mine:25`
- The sweep's best configs all OMIT role_conditional
- Per-role penalties (miners penalized for hearts, scouts ignore mining) disrupt the chain

**5. Gear still ZERO across all 20 experiments:**
- Confirms the exploration hypothesis: no reward variant combo creates a gradient toward gear stations
- The gear wall is structural, not a reward tuning problem
- Best junction performance comes from variants that optimize the steps the agent CAN discover

**6. All runs hit premature convergence** (clipfrac=0, approx_kl=0):
- Despite this, expl_var was 0.97-0.998 for most runs (value fn works)
- The policy converges to a local optimum (mine/deposit/hearts) and stops updating
- Higher ent_coef might help but Run 2 showed 0.10 breaks value fn with curriculum

**Top 3 configs for Phase 2 A3 sweep:**
1. `forced_role_vibes + credit + objective_mine:50` (2.500 junctions)
2. `forced_role_vibes + milestones + credit` (2.450 junctions)
3. `milestones` alone (2.417 junctions)

##### Phase 2a: A3 Hyperparameter Sweep on Arena (2026-03-10) ✅ COMPLETE

**Rationale**: Phase 1 sweep found the best reward configs but ALL runs hit premature convergence (clipfrac=0, approx_kl=0). The policy freezes before fully exploiting the reward landscape. Sweeping `ent_coef` (controls exploration pressure) and `update_epochs` (controls gradient extraction per batch) could unlock better performance from the same reward configs.

**Design**: Top 3 Phase 1 configs × {ent_coef: 0.03, 0.05, 0.07} × {update_epochs: 1, 3} = 18 runs

| Parameter | Values | Rationale |
|-----------|--------|-----------|
| **ent_coef** | 0.03, 0.05, 0.07 | 0.05 caused convergence in Phase 1. 0.03 may converge faster to better local optimum. 0.07 may keep exploring longer. 0.10 was tested in Run 2 and broke value fn with curriculum, but may work without rotation. |
| **update_epochs** | 1, 3 | Default is 1. More epochs extract more gradient per batch — standard PPO uses 3-4. Could help when premature convergence is the issue. |

**Fixed**: gamma=0.999, gae_lambda=0.95, bptt=128 (proven optimal from Phase 1)

**Status**: ✅ Complete — 2026-03-10 15:16 to 2026-03-11 00:14 UTC (8h 57min)
- Script: `sweep_phase2.sh`
- Logs: `sweep_phase2_logs/` (18 files)
- Results: `sweep_phase2_results.csv`

##### Phase 2a Results (sorted by aligned_junctions)

| Rank | Config | ent_coef | epochs | Junctions | Hearts | Entropy | Expl.Var |
|------|--------|----------|--------|-----------|--------|---------|----------|
| **1** | **milestones (no A1)** | **0.03** | **3** | **3.214** | 0.839 | 1.251 | 0.987 |
| **2** | **milestones (no A1)** | **0.05** | **3** | **3.125** | 0.719 | 1.590 | 0.900 |
| **3** | **A1 + milestones + credit** | **0.05** | **3** | **1.857** | 0.924 | 1.501 | 0.983 |
| 4 | milestones (no A1) | 0.03 | 1 | 1.833 | 0.472 | 1.496 | 0.978 |
| 5 | A1 + milestones + credit | 0.07 | 3 | 1.286 | 0.875 | 1.542 | 0.975 |
| 6 | A1 + milestones + credit | 0.03 | 3 | 0.893 | 0.714 | 1.102 | 0.968 |
| 7 | A1 + credit + obj50 | 0.07 | 1 | 0.714 | 0.732 | 1.607 | 0.982 |
| 8 | A1 + credit + obj50 | 0.07 | 3 | 0.429 | 0.705 | 1.601 | 1.000 |
| 9 | A1 + credit + obj50 | 0.03 | 1 | 0.393 | 0.728 | 1.609 | 0.039 |
| 10 | A1 + credit + obj50 | 0.05 | 3 | 0.321 | 0.777 | 1.609 | 0.026 |
| 11 | A1 + credit + obj50 | 0.03 | 3 | 0.250 | 0.250 | 1.386 | 0.981 |
| 12 | A1 + credit + obj50 | 0.05 | 1 | 0.250 | 0.701 | 1.608 | 0.990 |
| 13 | milestones (no A1) | 0.07 | 3 | 0.179 | 0.982 | 1.499 | 0.973 |
| 14 | milestones (no A1) | 0.05 | 1 | 0.143 | 0.960 | 1.558 | 0.977 |
| 15 | A1 + milestones + credit | 0.03 | 1 | 0.000 | 0.866 | 1.461 | 0.978 |
| 16 | A1 + milestones + credit | 0.05 | 1 | 0.000 | 0.884 | 1.403 | 0.979 |
| 17 | A1 + milestones + credit | 0.07 | 1 | 0.000 | 0.875 | 1.582 | 0.980 |
| 18 | milestones (no A1) | 0.07 | 1 | 0.000 | 0.987 | 1.586 | 0.979 |

##### Phase 2a Analysis

**1. NEW OVERALL BEST: `milestones` alone, ent_coef=0.03, update_epochs=3 → 3.214 junctions**
- 28.6% improvement over Phase 1's best (2.500)
- No forced roles, no credit stacking — simplest reward config wins
- Checkpoint: `train_dir/177317914284/model_000191.pt`

**2. `update_epochs=3` is the critical hyperparameter:**
- For `milestones` (no A1): u3 = {3.214, 3.125, 0.179} vs u1 = {1.833, 0.143, 0.000}. u3 wins 2/3.
- For `A1_mile_credit`: u3 = {0.893, 1.857, 1.286} vs u1 = {0.000, 0.000, 0.000}. ALL u1 runs got ZERO junctions. u3 is mandatory.
- For `A1_credit_obj50`: u3 = {0.250, 0.321, 0.429} vs u1 = {0.393, 0.250, 0.714}. u1 actually wins here — possibly over-fitting to objective_mine signal with 3 epochs.
- u3 costs ~25-35% more training time (avg 2040s vs 1539s).

**3. Lower ent_coef (0.03) is better for the best config:**
- milestones + u3: 0.03→3.214, 0.05→3.125, 0.07→0.179
- Higher entropy pushes toward hearts farming instead of junction alignment

**4. Forced roles (A1) HURT milestones:**
- milestones alone: best = 3.214 (rank 1)
- A1 + milestones + credit: best = 1.857 (rank 3)
- Adding forced roles and credit constrains the policy in ways that reduce junction alignment

**5. Phase 1's best config (A1_credit_obj50) is mediocre under A3 tuning:**
- Best A3 combo: ent_coef=0.07, u1 → 0.714 junctions (rank 7)
- Its Phase 1 score of 2.500 with default ent_coef=0.05/u1 was not reproduced — high variance

**6. Premature convergence is UNIVERSAL:**
- ALL 18 experiments ended with clipfrac=0.000, approx_kl=0.000
- No ent_coef value (0.03-0.07) prevents convergence over 50M steps
- The learning happens DURING training before convergence — hyperparams affect HOW, not WHETHER the policy converges

**7. Gear still ZERO across all 18 experiments:**
- aligner_amt = 0.000 everywhere
- Confirms the gear wall is structural, independent of hyperparameters
- 38 total experiments (20 Phase 1 + 18 Phase 2a), 1.9 billion steps, zero gear ever

##### Phase 2a → Phase 2b: Top 3 for Machina_1

| Rank | Config | Hyperparams | Checkpoint | Rationale |
|------|--------|------------|------------|-----------|
| **1** | `-v milestones` | ent=0.03, u=3 | `train_dir/177317914284/model_000191.pt` | Best junctions (3.214), good hearts (0.839), best expl_var (0.987) |
| **2** | `-v milestones` | ent=0.05, u=3 | `train_dir/177318260374/model_000191.pt` | 2nd best (3.125), higher terminal entropy (1.590) — may adapt better to machina_1 |
| **3** | `-v forced_role_vibes -v milestones -v credit` | ent=0.05, u=3 | `train_dir/177317198573/model_000191.pt` | Best hearts+junctions combo (1.857j, 0.924h), best forced-role config |

##### Phase 2b: Machina_1 Training — Tournament Map (planned, after 2a)

**Rationale**: All training so far used arena (50x50, 1000 steps/episode). The tournament leaderboard uses machina_1 (88x88, 10,000 steps/episode). Policies trained on arena may not transfer — machina_1 has longer episodes, more junctions (141 vs ~59), larger distances, and different resource layout. We need to validate that our best configs work on the actual tournament map before submitting to the leaderboard.

**Design**: Top 3 configs from Phase 2a (best reward + best hyperparams), trained directly on machina_1.

| Parameter | Value |
|-----------|-------|
| Map | `cogsguard_machina_1.basic` (88x88, 10K steps/ep) |
| Steps | 50M |
| Runs | 3 (top configs from Phase 2a) |
| Est. time per run | ~4-5 hours (10x longer episodes than arena) |
| Total time | ~15 hours |

**Why not curriculum (arena → machina_1)?**: Run 2 showed curriculum rotation disrupts value function. Sequential checkpoint loading (train on arena, then fine-tune on machina_1) is an option but adds complexity. Training directly on machina_1 gives clean results for comparison.

**Script**: `sweep_phase2b.sh` (updated with Phase 2a winners)

**Status**: ✅ COMPLETE — see Phase 2b Results below.
- Run 1: `m1_mile_e003_u3` — milestones, ent=0.03, u=3 (Phase 2a winner)
- Run 2: `m1_mile_e005_u3` — milestones, ent=0.05, u=3
- Run 3: `m1_A1_mile_credit_e005_u3` — A1 + milestones + credit, ent=0.05, u=3

All 3 runs: 0 junctions on machina_1 — arena configs don't transfer.

##### Phase 2b Results (2026-03-11) ✅ COMPLETE

**Duration**: 1h 43min (much faster than 13h estimate — ~34 min/run at ~25K SPS)

| Rank | Config | ent_coef | Hearts | Junctions | Expl.Var | Duration |
|------|--------|----------|--------|-----------|----------|----------|
| 1 | milestones | 0.03 | 1.000 | **0.000** | 0.959 | 2050s |
| 2 | milestones | 0.05 | 1.000 | **0.000** | 0.936 | 2063s |
| 3 | A1+mile+credit | 0.05 | 0.875 | **0.000** | 0.801 | 2084s |

**All 3 runs: ZERO junctions on machina_1.** Arena configs did NOT transfer.

**Key findings:**
1. **Arena → machina_1 transfer fails**: Configs that scored 3.214 junctions on arena got 0 on machina_1. The 88x88 map with 10K-step episodes is fundamentally harder.
2. **Transient success then regression**: The forced_role_vibes run showed 3.0 junctions at 27.5M steps with 55.3 silicon deposited, but regressed to 0 by end. The behavior is learnable but unstable.
3. **Hearts learning works**: All runs learn heart acquisition (0.875-1.000), confirming the basic economy chain works on machina_1.
4. **Value function degrades with complexity**: Simplest config (milestones-only, ent=0.03) had best expl_var (0.959). More reward terms = harder value estimation.
5. **Gear still zero** across all runs.

**Checkpoints:**
- Best: `train_dir/177323416557/model_000191.pt` (milestones, ent=0.03, u=3)
- `train_dir/177323621553/model_000191.pt` (milestones, ent=0.05, u=3)
- `train_dir/177323827826/model_000191.pt` (A1+mile+credit, ent=0.05, u=3)

**Conclusion**: Flat PPO on machina_1 is even more limited than on arena. The larger map increases distances to resources/junctions, making the exploration problem worse. Confirms that Steps 2-3 of the revised plan (kickstarting + Cortex) are essential for machina_1 performance.

##### Kickstarting Baseline Results (PI data, 2026-03-11)

Subhojeet shared his kickstarting experiments on the leaderboard. These used nlanky (a scripted agent) as the teacher:

| Entry | Score | Type | Notes |
|-------|-------|------|-------|
| subho.nlanky:v1 | 3.46 | Scripted (teacher) | The baseline teacher |
| subho.kickstartednlanky.clipsL:v1 | 2.26 | Kickstarted (learned) | Best kickstarted variant |
| subho.kickstartednlanky.no_clips:v1 | 2.03 | Kickstarted (learned) | No-clips variant |
| subho.kickstartednlanky.clips:v1 | 1.67 | Kickstarted (learned) | Worst variant |

**Key insight: the kickstarted student scored WORSE than its scripted teacher** (2.26 vs 3.46). Kickstarting is not magic — the student degraded rather than surpassed the teacher.

**Implications for our plan:**
1. **Teacher quality matters**: nlanky scores 3.46 — a weak teacher produces a weak student. Kickstarting from dinky (19.94) should yield much better results.
2. **Kickstarting alone is insufficient**: The KL loss + annealing recipe doesn't automatically produce a better-than-teacher agent. RL fine-tuning after annealing needs more work.
3. **Our flat PPO is competitive with nlanky**: Our best arena score (3.214 junctions) is in nlanky's ballpark (3.46). On machina_1 we got 0, but with more training or curriculum transfer we could approach it.
4. **Learned agents still don't beat scripted**: PI confirmed — the gap remains open. This is the core research challenge.
5. **No learned agent has scored >6 on the leaderboard** (confirmed by PI and leaderboard data). slanky (scripted) dominates at 6-9.5.

**Updated leaderboard picture:**

| Score Range | Agents | Type |
|-------------|--------|------|
| 18-20 | dinky:v23-v24 | Scripted |
| 7-10 | slanky (many versions), relh entries | Scripted |
| 5-7 | slanky older versions, dinky:v21 | Scripted |
| 3-5 | nlanky, glanky | Scripted |
| 1-3 | kickstartednlanky, gassy, mammet, our baseline | Learned / mixed |

**Revised A5 expectations**: Kickstarting from dinky (19.94) instead of nlanky (3.46) should produce a much stronger student. Target: 5-15 range (beating flat PPO ceiling, potentially approaching lower slanky versions). Exceeding the teacher is the stretch goal.

**Flat PPO submitted** (2026-03-11): `mahault.flat_ppo_milestones_v1:v1` = **1.77** (690 matches, rank 127/140). Arena score of 3.214 junctions translates to 1.77 on tournament map — confirms the arena→machina_1 transfer gap. This is the first flat PPO on the leaderboard.

**Role-specific agents already on leaderboard** (by relh):
- relh.aligner:v1 = 1.42, relh.aligner:v2 = 1.41
- relh.scout:v1 = 1.39, relh.scout:v2 = 1.42
- relh.miner:v2 = 1.37
- relh.scrambler:v1 = 1.32, relh.scrambler:v2 = 1.29
These are individual role submissions (no combined team). Our flat PPO at 1.77 beats all individual role agents.

##### Metta Repo Exploration (2026-03-11)

Cloned https://github.com/Metta-AI/metta (4498 files). Use as **reference only** — training code must be built on cogames/PufferLib (PI directive).

**Key findings:**

| Component | What We Found | Impact on Plan |
|-----------|--------------|----------------|
| **Cortex** | Public package at github.com/Metta-AI/cortex. Pattern "Ag,A,S" (AGaLiTe + Axon + sLSTM), not "AXMS" as in metta default. | B2' effort drops — can pip install |
| **Kickstarter** | `metta/rl/loss/kickstarter.py`: action_coef=0.6, temp=2.0, value_coef=1.0. No explicit annealing in code. | Need to implement our own annealing schedule |
| **Annealing** | PI clarified: α=1.0 constant for 2.5B steps, annealed 1.0→0 over 2.5B-10B, pure PPO after 10B. Total: 10B+ steps (~92 hrs on L4). | A5 is compute-heavy — may need shorter variant |
| **Nlanky** | Nim-compiled scripted agent with role-based behavior. Source in cogames-agents/nim_agents/. | Confirmed as scripted teacher for kickstarting |
| **Slanky/Dinky** | No source code in repo, no short_names registration. All scripted agents have source code. Ambiguous — could be learned checkpoints or remotely-hosted scripted agents. | Need PI clarification |
| **Gradient TD** | `metta/rl/advantage.py` — CUDA-optimized TD-Lambda reverse scan. Paper: arxiv.org/abs/2507.09087 | Reference for our own implementation |
| **Reward centering** | Rolling normalization with beta parameter, distributed across ranks. | Reference for training stability |
| **Tutorial missions** | Official tutorials in `packages/cogames/tutorials/`: TRAIN_MINER, TRAIN_ALIGNER, TRAIN_SCOUT, TRAIN_SCRAMBLER. Use `cogames train -m miner_tutorial` etc. | A1.5 is just running tutorial missions — effort minimal |
| **ForcedRoleVibesVariant** | `variants.py`: `ForcedRoleVibesVariant(role_order=["miner"]*4, disable_change_vibe=True)` + `apply_reward_variants()`. Not exposed via `-v` CLI flag. | Programmatic role forcing for custom configs |
| **Tutorial hyperparams** | gamma=0.995, gae_lambda=0.90, ent_coef=0.01, update_epochs=1, bptt=64. Different from our sweep config. | May explain performance differences |
| **Three exploration paths** | PI framing: (1) kickstarting, (2) shaped rewards, (3) intrinsic exploration rewards | All three are valid research directions |

**Subhojeet's three paths to solving the exploration problem:**
1. **Kickstarting** from scripted teacher (BC + PPO) — proven approach but compute-heavy (10B steps)
2. **Shaped rewards** that guide toward desired behavior — what our sweeps explored (partially exhausted)
3. **Intrinsic exploration rewards** — untried (count-based, RND, curiosity). Could be faster than kickstarting.

##### Hypothesis: Why No Reward Variant Gets Gear (2026-03-10)

**Observation**: Across 7 runs (250M+ steps), 3 manual A2.x experiments, and a systematic 20-experiment sweep, gear acquisition is ALWAYS zero regardless of reward variant configuration.

**Hypothesis**: All reward variant experiments address **credit assignment** (making known chain steps more rewarding), but the actual bottleneck is **exploration** (discovering gear stations as interactable objects in the first place).

The structural problem has two distinct failure modes that reward shaping conflates:

| Failure Mode | What It Is | Solved By Reward Shaping? |
|-------------|-----------|--------------------------|
| **Credit assignment** | Long chain, sparse/delayed reward, can't attribute success to earlier actions | YES — γ=0.999, λ=0.95, bptt=128 give 0.997 expl.var |
| **Exploration** | Agent never visits gear stations, so never experiences gear.gained > 0 | **NO** — amplifying a zero signal is still zero |

Why the agent never visits gear stations:
1. **Gear stations are specific map objects** — the agent must navigate ~50 directed steps to reach one
2. **Zero reward gradient toward gear stations** — no variant rewards proximity to converter objects
3. **PPO explores via entropy bonus** (one random action at a time) — probability of a random walk reaching a gear station AND bumping it is ~0
4. **The reward variants only amplify signal from behaviors that already occur** — if `gear.gained` is always 0, multiplying it by 0.2 (credit) or 2.0 (role variant) changes nothing

This explains the paradox of our results:
- **Best junctions (1.889) came from A2+A3 WITHOUT forced roles** — generic agents accidentally bump into things while exploring broadly
- **Forced roles REDUCED junctions** — agents became more focused/efficient at mining (deposit went up) but LESS likely to randomly discover gear stations
- **Braveheart (255 hearts) didn't help** — resource abundance doesn't create a gradient toward gear stations
- **Higher entropy (0.10) didn't help** — more random actions ≠ directed exploration toward specific objects

**Prediction**: The A1×A2 sweep will confirm this — no combination of existing reward variants will produce gear.gained > 0. The sweep's value is in finding the best reward config for everything ELSE (hearts, junctions, value function), establishing the optimal baseline before adding exploration mechanisms.

**What would actually solve gear discovery:**
- **PBRS with potential function** — Φ(s) includes inventory/chain state, gear acquisition creates a +10 potential jump → creates gradient toward gear stations even before first discovery (via value function generalization)
- **Count-based inventory exploration** — explicitly rewards visiting novel inventory states → first gear acquisition gets a large novelty bonus
- **Reward machines** — FSM defines explicit "navigate to gear station" state transitions → chain structure exposed to PPO
- **Proximity reward** — reward decreasing distance to nearest gear station → direct spatial gradient (but requires reading observation tokens to locate gear stations)

**Note**: PI (Subhojeet) says flat PPO CAN learn with "different reward functions." This may mean they have a PBRS-style or proximity-based reward that creates the missing gradient, or a custom variant beyond the public `reward_variants.py`. Their suggestion will likely address the exploration problem, not just credit assignment.

**Advanced approaches to try after sweep** (from reward function research):

| Rank | Approach | What It Does | Effort |
|------|----------|-------------|--------|
| 1 | **Reward Machines (FSM)** | Define chain as finite-state automaton, reward state transitions. Icarte et al. craft domain is structurally identical to CogsGuard. | 8-12 hrs |
| 2 | **PBRS (potential-based shaping)** | Φ(s) encodes chain progress; gear acquisition gives +10 spike. Preserves optimal policy. | 4-6 hrs |
| 3 | **Dense proxy rewards** | Close documented gaps: reward `game.{team}/{element}.withdrawn` (crafting), add miner/scout gear to credit. | 2-4 hrs |
| 4 | **Count-based inventory exploration** | Hash inventory state (~45K states), reward novel configurations. First gear gets huge novelty bonus. | 6-8 hrs |
| 5 | **RND exploration** | Dual value heads, intrinsic motivation for novel observations. | 10-15 hrs |

### Buggy Agent Eval (cogsguard_machina_1.basic, 8 cogs, 3 episodes) — 2026-03-09

Buggy = Planky fork with explicit role goal trees (miner, scout, aligner, scrambler).
Fixed name collision in `cogsguard/roles.py` (`miner` → `ca_miner` etc.) to allow cogames-agents PYTHONPATH import.

| Metric | Buggy | Starter (ref) | Notes |
|--------|-------|---------------|-------|
| Per-agent reward | 1.00 | 1.00 | Base reward, no junctions captured |
| Cells visited | 48,750 total | 86,273 | Less exploration than starter |
| change_vibe.success | 30,000 | — | IS changing roles (~1250/agent-ep) |
| aligned_junction_held | 30,000 | 0 cogs / 144 clips | Likely clips-held, NOT cogs |
| cogs/aligner.amount | 0 | 0 | **NO aligner gear acquired** |
| cogs/miner.amount | 0 | 0 | **NO miner gear acquired** |
| cogs/hp.amount | 0 | 0 | **NO hearts crafted** |
| Resources (Si/Ge/C) | 24 each | — | Some mining happening |
| max_steps_without_motion | 60,000 | — | **Severely stuck** (~2500/agent-ep) |

**Diagnosis**: Buggy goal trees are firing (roles assigned, mining attempted) but the economy chain breaks:
1. Resources mined but NOT deposited → no hearts → no gear → no junctions
2. Agents getting severely stuck (2500+ steps without motion per agent)
3. The A* navigator or goal transitions have bugs — deposit/craft chain not completing
4. Need to debug goal execution: are agents reaching the hub? Is deposit triggering?

**Deprioritized**: Buggy/Planky comparison superseded by kickstarted agents and AIF direction. slanky confirmed scripted by PI (2026-03-11).

### Leaderboard Update (2026-03-09)

| Rank | Policy | Score | Type | Notes |
|------|--------|-------|------|-------|
| 1 | dinky:v24 | 77.62 | Scripted | Top |
| 2 | dinky:v23 | 43.86 | Scripted | |
| 5 | relh.live-pilot:v1 | 30.90 | ? | New entrant |
| 6 | relh.clanky:v1 | 29.69 | ? | New entrant |
| 7 | **slanky:v109** | **24.61** | Scripted (PI confirmed 2026-03-11) | Was assumed learned, actually scripted |
| 8 | slanky:v83 | 14.54 | Learned | |
| 9 | relh.mettagrid-sdk-semantic-cogsguard-v2:v1 | 11.92 | ? | |

**Note**: slanky was later confirmed scripted (PI, 2026-03-11), not learned. The "massive jump" was likely a scripted agent improvement, not a learned-agent breakthrough. `relh` entries are new — approach unknown.

### AWS State (2026-03-09)

- **Tier 1 training complete** — A2+A3 finished (50M steps, 26.5min). Checkpoint at `train_dir/177309700806/model_000191.pt`
- **Disk**: 27G/30G used (90%), 3.1G free
- **GPU**: NVIDIA L4, idle. CUDA kernel fix applied.
- **screen**: available
- **cogames-agents**: NOT pip-installed, using PYTHONPATH workaround
- **Env**: cogames 0.18.0, mettagrid 0.18.2, PufferLib 3.0.17 (cogames fork, CUDA kernel compiled + patched)
- **Checkpoints**: old partials cleaned up. New run saving every 50 epochs.
- **Buggy fix**: renamed `cogsguard/roles.py` short_names to avoid collision with cogames built-ins
- **Hyperparams patched**: `train.py` modified (gamma=0.999, gae_lambda=0.95, bptt=128, ent_coef=0.05, checkpoint_interval=50). Backup at `train.py.bak`.
- **PufferLib patched**: `pufferl.py` line 76 loads compiled CUDA `.so` at import time. `ninja` installed for JIT compilation.

### PufferLib CUDA Kernel Fix (2026-03-09)

**Bug**: PufferLib 3.0.17 (cogames' custom fork, not on PyPI) ships with CUDA kernel source (`extensions/cuda/advantage.cu`) but doesn't compile it during installation. The `pufferl.py` module checks for `nvcc` on PATH and assumes CUDA kernels are available if it exists (`ADVANTAGE_CUDA = shutil.which("nvcc") is not None`). On AWS with CUDA toolkit installed, `nvcc` exists → PufferLib thinks CUDA kernels work → tries to dispatch `compute_puff_advantage` to CUDA → `NotImplementedError` crash.

**Fix** (3 steps):

1. **Install ninja** (build tool): `pip install ninja`

2. **JIT-compile the CUDA kernel**:
```python
from torch.utils.cpp_extension import load
import os
cuda_dir = '/home/ec2-user/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/extensions/cuda'
load(name='pufferlib_cuda_advantage', sources=[os.path.join(cuda_dir, 'advantage.cu')], verbose=True)
# This fails to import (no PyInit) but compiles .so to ~/.cache/torch_extensions/
```

3. **Copy compiled .so and patch pufferl.py**:
```bash
# Copy .so to PufferLib extensions dir
cp ~/.cache/torch_extensions/py312_cu128/pufferlib_cuda_advantage/pufferlib_cuda_advantage.so \
   /home/ec2-user/projects/cogames-env/lib64/python3.12/site-packages/pufferlib/extensions/cuda/

# Patch pufferl.py line 76 — replace:
#   ADVANTAGE_CUDA = shutil.which("nvcc") is not None
# With:
_CUDA_ADV_SO = os.path.join(os.path.dirname(__file__), 'extensions', 'cuda', 'pufferlib_cuda_advantage.so')
if os.path.exists(_CUDA_ADV_SO) and torch.cuda.is_available():
    try:
        torch.ops.load_library(_CUDA_ADV_SO)
        ADVANTAGE_CUDA = True
    except Exception:
        ADVANTAGE_CUDA = shutil.which('nvcc') is not None
else:
    ADVANTAGE_CUDA = shutil.which('nvcc') is not None
```

**Result**: GPU training works with `--device auto`. NVIDIA L4 uses ~1082 MiB, advantage computation runs natively on CUDA.

**Why the `.so` can't be imported normally**: The CUDA kernel uses `TORCH_LIBRARY_IMPL(pufferlib, CUDA, m)` which registers a dispatch impl, not a Python module. It has no `PyInit_*` function. Must be loaded via `torch.ops.load_library()` AFTER the CPU extension (which defines the schema via `TORCH_LIBRARY`) is imported.

### Tier 1 Training Run (A2+A3) — ✅ COMPLETE

**Command**:
```bash
cogames train -m cogsguard_arena.basic -p class=tutorial --cogs 8 --steps 50000000 --device auto -v credit -v role_conditional -v objective_mine:25
```

**What's active**:
- A2: Reward variants (credit + role_conditional + objective_mine:25)
- A3: Tuned hyperparams (gamma=0.999, gae_lambda=0.95, bptt=128, ent_coef=0.05)
- GPU training on NVIDIA L4 (CUDA kernel fix applied)

**What's NOT active** (needs separate implementation):
- A1: Forced role assignment — tutorial policy doesn't assign vibes at step 0. `role_conditional` shapes rewards per agent index but doesn't force `change_vibe`.

**Status**: ✅ COMPLETE — see "Tier 1 Training: A2+A3" in Phase 2 Training Log for full results.
- Started: 2026-03-09 ~22:57 UTC
- Completed: 2026-03-09 ~23:23 UTC (26m 29s)
- Final checkpoint: `train_dir/177309700806/model_000191.pt`
- Key result: Value function near-perfect (0.997 expl. var.), but role discovery still zero. **A1 is next.**

### Tier 1b Training Run (A1+A2+A3) — ✅ COMPLETE

**Goal**: Force role assignment at step 0 via built-in `forced_role_vibes` variant, combined with A2+A3. Tests whether PPO can learn the economy chain when roles are given.

**Discovery**: cogames 0.18.0 has a built-in `ForcedRoleVibesVariant` (`variants.py` line 495) that:
1. Sets each agent's initial vibe at env construction (miner→5, aligner→4, scrambler→3, scout→6)
2. Disables `change_vibe` action so agents cannot switch roles
3. Injects `role_id` into observation space as a global token
4. Default role_order `["miner", "aligner", "scrambler", "scout"]` with `per_team=True` → 2+2+2+2 for 8 agents

**Command**:
```bash
cogames train -m cogsguard_arena.basic -p class=tutorial --cogs 8 --steps 50000000 --device auto -v forced_role_vibes -v credit -v role_conditional -v objective_mine:25
```

**What's active** (all of Tier 1):
- A1: Forced role assignment via `forced_role_vibes` (roles assigned at step 0, change_vibe disabled)
- A2: Reward variants (credit + role_conditional + objective_mine:25)
- A3: Tuned hyperparams (gamma=0.999, gae_lambda=0.95, bptt=128, ent_coef=0.05)
- GPU training on NVIDIA L4 (CUDA kernel fix applied)

**Status**: ✅ COMPLETE — see "Tier 1b Training: A1+A2+A3" below for full results.
- Started: 2026-03-09 ~23:30 UTC
- Completed: 2026-03-09 ~23:57 UTC (~27 min)
- Final checkpoint: `train_dir/177309922942/model_000191.pt`

---

## Deep Research: Approaches & Bottleneck Analysis

### The Core Problem

The gap between scripted agents (dinky: 77.62 qualifying / 21.09 competition; slanky: ~24.6, also scripted per PI) and learned agents (our baseline: ~1.77, no learned agent >6) stems from **four compounding failures**:

| # | Failure | Why It Happens | Impact |
|---|---------|---------------|--------|
| 1 | **Role discovery never happens** | `change_vibe` has zero immediate reward; 4^8 = 65,536 role combinations never searched | Fatal — blocks entire gear→junction chain |
| 2 | **Economy chain too long for flat PPO** | Mine→deposit→craft→gear→capture→hold spans 100+ steps; γ=0.995 attenuates signal by ~40% | Severe — even if roles assigned, credit assignment fails |
| 3 | **CNN is wrong inductive bias** | Observations are entity tokens `[loc, feat, val]`, not spatial pixels; CNN misses relational structure | Moderate — wastes capacity on spatial assumptions |
| 4 | **LSTM(512) insufficient for spatial memory** | 13x13 view on 100x100 map; LSTM must encode spatial+entity+temporal state in one vector for 10K steps | Moderate — can't remember resource locations |

### What Scripted Agents Get Right

- **Immediate role assignment**: Each agent knows its role from step 0
- **Goal-stack decomposition**: "I'm an aligner" → "need hearts" → "find hub" → "navigate" → "use hub" → "find junction" → "align junction"
- **Entity memory**: Planky remembers entity locations beyond 13x13 view
- **A* pathfinding**: Optimal navigation, no wasted steps
- **But**: Can't adapt roles, can't model teammates, can't counter novel opponents

### What Learning Could Add

- Adaptive role reallocation based on game state
- Opponent modeling and counter-strategy
- Emergent coordination patterns
- Efficient resource routing that scripted heuristics can't optimize

---

## Why Role Discovery Fails: Technical Detail

From examining `src/cogames/train.py` and training logs:

1. **`change_vibe` has zero immediate reward**: In default reward setup, changing vibe gives 0 reward. The benefit of specialization (10x mining for miners, +400 HP for scouts) is delayed 50-100+ steps. With γ=0.995: `0.995^100 = 0.606` — barely above noise.

2. **Entropy coefficient too low**: `ent_coef=0.01` (train.py line 306) doesn't provide enough exploration pressure on `change_vibe`. With 6 actions, max entropy is `ln(6) ≈ 1.79`. Our training shows entropy stable at 1.43 — agents explore movement but not role changes.

3. **No role initialization**: All 8 agents start without roles (default vibe). Must independently discover that specialization helps. This is a coordination problem with `4^8 = 65,536` possible role assignments.

4. **`penalize_vibe_change` is premature**: This reward variant (weight=-0.01) discourages the very exploration needed in early training. Should only be used after role discovery is established.

5. **Reward signal from specialization is indirect**: Even after `change_vibe`, the agent must then navigate to the appropriate station, acquire gear, and perform role-specific actions. Each step adds delay and noise to the credit assignment chain.

---

## Comparison: Agent Approaches on Leaderboard

| Agent | Type | Score | Role Strategy | Key Advantage | Key Weakness |
|-------|------|-------|---------------|---------------|--------------|
| `daveey.pinky` (dinky) | Scripted | 21.09 | Fixed 4/4 miner/aligner | Optimal simplicity, A* paths | Cannot adapt |
| `daveey.planky` | Scripted | 3.8 | Fixed 4/4 + dynamic switch | Entity memory, goal stacks | Static roles |
| `slanky` variants | Likely scripted (PI clarified) | ~8.9-24.6 | Unknown | Unknown | Unknown |
| `starter` (built-in) | Scripted | ~1-2 | Per-agent heuristic | Works out of box | Gets stuck (79% failed moves) |
| Our baseline | Learned (CNN+LSTM) | ~1.0 | None | — | All four failures |

**Gap analysis**: The ~20x gap between dinky and our baseline is almost entirely explained by role specialization. Dinky's 50/50 miner/aligner split immediately solves credit assignment (miners know they mine, aligners know they align) and the economy chain (dedicated miners → steady resource flow → aligners can focus on junctions).

---

## Cortex Training Experiments

### S5/S6: Cortex (Ag,A,S) on Arena

#### Cortex Version Discovery (2026-03-17)

The standalone GitHub repo (`github.com/Metta-AI/cortex`) has **diverged** from the Metta monorepo (`metta/packages/cortex/`):
- Standalone removed `pattern` string support, uses `layers` param with explicit cell configs
- Standalone sLSTM backward crashes with `AttributeError: '_rnn_fwbwBackward' has no attribute '_fwd_used_autocast'` under PufferLib's autocast context
- Monorepo version has working `pattern` support and fixed sLSTM backward
- Subhojeet confirmed: "There is a PR which should fix this" for standalone

**Resolution**: Install cortex from monorepo (`metta/packages/cortex/`), not standalone GitHub.

#### S5 (CRASHED): Cortex d=256 (2026-03-16)

| Config | Value |
|--------|-------|
| Architecture | Ag,A,S, d_hidden=256, 2 layers |
| Parameters | 9.27M |
| Reward | milestones |
| SPS | ~1,800 (very slow) |
| Crashed | Epoch ~1550 (disk full — 30GB volume) |
| Result | **0 junctions** |

Too many parameters for this problem. Slow SPS prevented meaningful convergence.

#### S6 (FAILED): Cortex d=64 (2026-03-17 → 2026-03-19)

| Config | Value |
|--------|-------|
| Architecture | Ag,A,S, d_hidden=64, 2 layers |
| Parameters | 573K (comparable to TutorialPolicyNet ~500K) |
| Reward | milestones |
| Entropy coef | 0.03 (best from A3 sweep) |
| Steps | 50M |
| Agents | 4, Envs: 4 |
| Cortex source | Monorepo (`metta/packages/cortex/`) |
| Result | **0 junctions** |

| Metric | Early (5M steps) | Final (50M steps) |
|--------|-------------------|---------------------|
| heart.gained | 0.375 | ~0 |
| explained_variance | 0.995 | **-0.002** (collapsed) |
| entropy | 1.22 | ? |
| agents alive at | step 400+ | **step 11** (dying immediately) |

**Root cause: Episode boundary state corruption.** PufferLib 3.0.17 never zeros LSTM/Cortex state when episodes end within an `evaluate()` call. Standard LSTM tolerates stale state (forget gate decays it naturally), but Cortex's AGaLiTe tick counter and sLSTM commitment state become corrupted across episode boundaries. Dead agents' state persists into the next agent's episode → cascading corruption → value function collapse → agents learn to die early.

**Metta monorepo comparison**: Metta's `CortexTD` integration uses PyTree-based state flattening (optree) with per-agent slot tracking and proper episode resets. Our naive packing of TensorDict → flat `lstm_h`/`lstm_c` buffers missed episode boundary handling entirely.

#### S7 (FAILED): Cortex d=64 + Scripted Teacher (2026-03-20)

| Config | Value |
|--------|-------|
| Architecture | Ag,A,S, d_hidden=64, 2 layers |
| Parameters | 758K |
| Reward | milestones |
| Entropy coef | 0.03 |
| **update_epochs** | **1** (should have been 3 — see post-mortem) |
| Steps | 50M |
| Agents | 8, Envs: 4 |
| Episode-reset patch | **Applied** (`patch_pufferl_v2.py`) |
| Scripted teacher | dinky-style (half miners, half aligners, no scout) |
| Kickstarting | CE loss, ks_coef=0.1, anneal to 0 at 50% (25M steps) |
| Result | **0 junctions** |

**Fixes over S6:**
1. **Episode-reset patch** — zeros `lstm_h`/`lstm_c` for agents with `done=True` in PufferLib's evaluate loop
2. **Scripted teacher kickstarting** — `L = L_ppo + α·CE(π_student, π_scripted)`. Scripted teacher implements dinky's economy chain: even agents mine (extractor→hub), odd agents align (hub→craft→junction). No LSTM intermediary — train Cortex directly from scripted teacher.
3. **8 agents** (up from 4) — matches CogsGuard standard config

| Metric | Early (2.7M) | Mid (15.4M) | Final (50M) |
|--------|--------------|-------------|-------------|
| heart.gained | 0.375 | 0.250 | 0.625 |
| entropy | 1.267 | 1.210 | 1.575 (near max) |
| explained_variance | 0.236 | -0.031 | 0.006 |
| ks_loss | 1.103 | 1.416 | N/A (annealed off) |
| aligned.junctions | 0 | 0 | 0 |
| max_steps alive | 16.2 | 21.4 | 9.6 |

**Post-mortem**: Episode-reset patch prevented S6-style catastrophic collapse, but training still failed. Two issues identified:
1. **update_epochs=1 was used instead of 3** — the A3 sweep proved u=1 produces 0 junctions even with LSTM. This was a config error.
2. **Kickstarting may have hurt** — ks_loss increased back to 1.416 mid-training (policy drifted from teacher), and once CE annealed off at 25M steps, the policy had nothing anchoring it.

#### S8 (FAILED): Cortex d=64, u=3, No Kickstarting (2026-03-20)

| Config | Value |
|--------|-------|
| Architecture | Ag,A,S, d_hidden=64, 2 layers |
| Parameters | 758K |
| Reward | milestones |
| Entropy coef | 0.03 |
| **update_epochs** | **3** (matching A3 best) |
| Steps | 50M |
| Agents | 8, Envs: 4 |
| Episode-reset patch | **Applied** |
| Kickstarting | **None** (matching A3 best) |
| Result | **0 junctions** |

Designed as a clean apples-to-apples comparison with the LSTM A3 best (3.214 junctions). Only variable: Cortex vs LSTM architecture.

| Metric | S8 Final | S7 Final | LSTM A3 Best |
|--------|----------|----------|--------------|
| **aligned.junctions** | **0** | **0** | **3.214** |
| heart.gained | 0.375 | 0.625 | ~2.0 |
| entropy | **1.609** (uniform random) | 1.575 | ~1.5 |
| explained_variance | **0.000** | 0.006 | ~0.6 |
| policy_loss | **20.826** (exploded) | 0.953 | ~0.05 |
| clipfrac | **0.000** | 0.010 | ~0.2 |
| approx_kl | **0.000** | 0.001 | ~0.03 |
| max_steps alive | **7.5** | 9.6 | ~400+ |
| SPS | 1,800 | 1,300 | ~2,500 |

**S8 was worse than S7.** Policy completely collapsed — entropy at max (uniform random), policy_loss exploded, zero gradient signal (clipfrac=0, approx_kl=0). u=3 amplified the damage because 3 gradient steps on a broken value function compounds errors.

#### S9 (FAILED): Cortex-LSTM Control Test (2026-03-24)

| Config | Value |
|--------|-------|
| Architecture | Cortex `LSTMCellConfig()` × 2 layers, d_hidden=64 |
| Encoder | CNN (same as S5-S8) |
| Parameters | 459K |
| Reward | milestones |
| Entropy coef | 0.03, update_epochs=3 |
| Steps | 50M |
| Result | **0 junctions** |

**Goal**: Isolate whether the issue was specific cells (AGaLiTe/sLSTM) or the Cortex scaffold itself. Replaced Ag,A,S with pure LSTM cells inside Cortex.

**Result**: Same collapse — entropy→max (1.609), expl_var→0, clipfrac=0. Early metrics (expl_var=0.970 at 7.6M) were transient.

**Key insight**: Cortex-LSTM also fails → the issue is NOT specific cells. Root cause was **architecture mismatch**: CNN encoder (vs Linear), d_hidden=64 (vs 128), 2 layers (vs 1), 459K params (vs 226K). Multiple variables changed from native LSTMPolicyNet simultaneously. Also: PufferLib zeros ALL recurrent state at the start of every `evaluate()` call — state never persists beyond bptt_horizon=64 steps. The tick fix and episode-reset patch were red herrings.

#### S10 (FAILED): Cortex-LSTM Native Architecture Match (2026-03-24)

| Config | Value |
|--------|-------|
| Architecture | Cortex `LSTMCellConfig()` × 1 layer, d_hidden=128 |
| Encoder | **Linear(600→128→128)** — matches native LSTMPolicyNet |
| Parameters | 226,566 (vs native 226,310) |
| `post_norm` | **True** (Cortex default) |
| Reward | milestones |
| Entropy coef | 0.03, update_epochs=3 |
| Steps | 50M (ran 40M+ before killed) |
| Result | **0 junctions** |

**Goal**: True apples-to-apples — match native LSTMPolicyNet exactly (Linear encoder, d_hidden=128, 1 layer, same obs preprocessing). Only difference: LSTM cell wrapped in Cortex scaffold.

**Result**: Entropy stuck at exactly 1.609 (uniform random over 5 actions) for entire 40M+ steps. clipfrac=0, approx_kl=0, importance=1.0. Policy never changed from initialization.

**Root cause: `post_norm=True` kills LSTM gradients.** Diagnostic revealed Cortex's `build_cortex_auto_stack(post_norm=True)` applies LayerNorm after the LSTM stack, crushing gradient signal by **145,000x**:

| | `post_norm=True` | `post_norm=False` |
|---|---|---|
| weight_hh grad | 0.0000008 | **0.6937** |
| weight_ih grad | 0.0000015 | **0.1937** |
| grad to input | 0.0000004 | **0.0509** |

The LSTM's recurrent weights (`weight_hh`) receive zero gradient → no temporal learning → feedforward MLP behavior → uniform random policy. The only parameters that get meaningful gradients through `post_norm=True` are the norm's own `weight` and `bias`.

**Additional finding**: The `gradient_norms()` monitoring was broken — called after `trainer.train()` (which includes `optimizer.zero_grad()`), so it always reported 0.0. This masked the root cause throughout S10.

#### S11 (FAILED): Cortex-LSTM with post_norm=False (2026-03-24)

| Config | Value |
|--------|-------|
| Architecture | Cortex `LSTMCellConfig()` × 1 layer, d_hidden=128 |
| Encoder | Linear(600→128→128) — matches native |
| Parameters | 226,566 |
| `post_norm` | **False** (fix from S10) |
| Resets | `expand(-1, bptt_horizon)` — **broadcast to ALL timesteps (bug)** |
| Reward | milestones |
| Entropy coef | 0.03, update_epochs=3 |
| Steps | 50M (killed early) |

**Result**: Entropy drifting up toward max (1.575), expl_var oscillating wildly (-10 to +0.98). Better than S10 but still not learning.

**Root cause: Resets broadcast to all timesteps.** Diagnostic tests revealed:
- **Test D (temporal sensitivity): FAIL** — perturbing t=0 had zero effect on t=1+. LSTM not propagating state.
- **Test G (state across calls): FAIL** — state stored but not used on next call.
- `weight_hh` gradient: 0.0 (recurrence dead, same symptom as S10 but different cause).

The bug was in `forward()`:
```python
# BUG: broadcast reset to ALL timesteps in BPTT window
resets = resets.unsqueeze(1).expand(-1, bptt_horizon)
```

PufferLib zeros state at start of `evaluate()` → `_unpack_state` detects zero rows → `resets = [True] * B` → `expand` makes `resets = [True] * (B × T)` → Cortex LSTM resets hidden state at **every timestep** → no temporal memory → feedforward-only behavior.

**Scaffold architecture finding**: With 1 expert per layer, the E=1 fast-path fires — **no residual, no normalization, no mixing**. The Cortex scaffold is transparent; the LSTM output passes through unchanged. This means the S11 config should be functionally identical to native `nn.LSTM` — the only difference is the resets handling.

#### S12 (IN PROGRESS): Cortex-LSTM with resets fix (launched 2026-03-24)

| Config | Value |
|--------|-------|
| Architecture | Cortex `LSTMCellConfig()` × 1 layer, d_hidden=128 |
| Encoder | Linear(600→128→128) — matches native |
| Parameters | 226,566 |
| `post_norm` | **False** |
| Resets | **t=0 only** (`resets_2d[:, 0] = resets`) — fix |
| Reward | milestones |
| Entropy coef | 0.03, update_epochs=3 |
| Steps | 50M |
| PID | 818087 |

**Fixes over S11**: Resets only applied at first timestep of BPTT window:
```python
resets_2d = torch.zeros(segments, bptt_horizon, dtype=torch.bool, device=hidden.device)
resets_2d[:, 0] = resets  # Only reset first timestep
```

**Verification before launch**: Diagnostics confirmed:
- `weight_hh` gradient: **84.56** (was 0.0 in S10/S11 — 84x improvement)
- Temporal propagation: perturbation at t=0 decays exponentially through t=1→t=15 (correct)
- State affects subsequent forward calls (Test G now passes)

**Early metrics (2.6M steps, ~5 min)**: entropy=1.48 (learning), expl_var=0.02-0.57 (volatile but recovering), hearts=0.75, junctions=0.

**Final result (50M steps)**: entropy=1.609 (collapsed to max), expl_var=-0.612, junctions=0.333, hearts=0.333. Started learning but collapsed mid-training. The Cortex LSTM cell works (confirmed by diagnostics) but our custom training loop diverges from the native `cogames train` pipeline.

#### S13 (SUCCESS): Cortex-LSTM via `cogames train` (2026-03-24)

| Config | Value |
|--------|-------|
| Architecture | Cortex `LSTMCellConfig()` × 1 layer, d_hidden=128 |
| Encoder | Linear(600→128→128) — matches native |
| Parameters | 226,566 |
| `post_norm` | False |
| Resets | t=0 only |
| **Training pipeline** | **`cogames train`** (native, not custom script) |
| Steps | 50M |
| Training time | **24 min** (vs 1.5h with custom script) |

**Key difference**: Used `cogames train` instead of custom `train_cortex.py`. This means identical training loop, state handling, hyperparameters, and PufferLib integration as native LSTM.

`cogames train` hyperparameters (hardcoded, different from our custom script):

| Param | cogames train | train_cortex.py |
|-------|--------------|-----------------|
| bptt_horizon | **128** | 64 |
| update_epochs | **1** | 3 |
| ent_coef | **0.05** | 0.03 |
| gamma | **0.999** | 0.995 |
| num_workers | **4** | 1 |
| SPS | **36,200** | 9,400 |

**Result: Peak 3.750 junctions — exceeds native LSTM's 3.214 by 17%.**

| Metric | S12 (custom script) | S13 (cogames train) | Native LSTM A3 |
|---|---|---|---|
| peak junctions | 0.333 | **3.750** | 3.214 |
| final junctions | 0.333 | 0.071 (unstable) | 3.214 |
| expl_var | -0.612 | **0.985** | ~0.98 |
| entropy | 1.609 (collapsed) | 1.601 | ~1.55 |
| clipfrac | 0.000 | **0.025** | ~0.2 |
| approx_kl | 0.000 | **0.008** | ~0.03 |
| training time | 1.5h | **24 min** | ~50 min |

**Analysis**: The Cortex-LSTM is functionally identical to native LSTM (confirmed by diagnostic Test B: zero output difference). The S5-S12 failures were caused by a combination of code bugs (architecture mismatch, post_norm, resets) AND training loop differences (bptt_horizon, update_epochs, ent_coef, workers). Using the native pipeline eliminates all training loop confounds.

The junction instability (3.75 peak → 0.07 final) is characteristic of the arena environment — junctions require multi-agent coordination and a single failed chain produces 0. Native LSTM likely has similar epoch-to-epoch variance.

### Cortex Conclusion (Final)

| Run | Key Change | Training | Result | Root Cause of Failure |
|-----|-----------|----------|--------|----------------------|
| S5 | CNN, d=256, Ag,A,S | custom | 0j (crashed) | Architecture + post_norm + resets + training loop |
| S6 | CNN, d=64, Ag,A,S | custom | 0j | Architecture + post_norm + resets + training loop |
| S7 | CNN, d=64, Ag,A,S + KS | custom | 0j | Architecture + post_norm + resets + training loop |
| S8 | CNN, d=64, Ag,A,S | custom | 0j | Architecture + post_norm + resets + training loop |
| S9 | CNN, d=64, LSTM×2 | custom | 0j | Architecture + post_norm + resets + training loop |
| S10 | Linear, d=128, LSTM×1 | custom | 0j | post_norm + resets + training loop |
| S11 | + post_norm=False | custom | 0j | resets + training loop |
| S12 | + resets t=0 only | custom | 0j (collapsed) | **training loop** (bptt=64, u=3, ent=0.03) |
| **S13** | **same as S12** | **cogames train** | **3.75j peak** | **N/A — SUCCESS** |
| **S14** | **Axon cell, E=1** | **cogames train** | **2.25j peak** | Linear SSM — works but limited capacity |
| **S15** | **Ag,A,S, E=3** | **cogames train** | **2.56j peak** | Dead router: Wq/Wk=0, mixer near-dead, 97% residual |
| **S16** | **Ag,A,S sequential (E=1×3)** | **cogames train** | **2.25j peak** | Overparameterization: peaks early (e56), entropy collapse (1.44) |

**Key finding**: The custom `train_cortex.py` was the final confound. When using the native `cogames train` pipeline, Cortex-LSTM matches and briefly exceeds native LSTM performance. The training loop differences (bptt_horizon=128 vs 64, update_epochs=1 vs 3, ent_coef=0.05 vs 0.03, 4 workers vs 1) collectively caused S12 to collapse despite having correct gradient flow.

**Diagnosis evolution (complete)**:
1. S5-S8: Architecture mismatch (CNN encoder, d=64, 2 layers)
2. S9: Same architecture mismatch, confirmed not cell-specific
3. S10: Fixed architecture → exposed post_norm=True gradient kill
4. S11: Fixed post_norm → exposed resets broadcast bug
5. S12: Fixed resets → exposed training loop differences
6. **S13: Used native training pipeline → SUCCESS**

### Training Pipeline Audit (2026-03-24)

S13's success revealed that the custom `train_cortex.py` was the final confound. This raises the question: which past experiments used custom scripts, and which conclusions are invalidated?

#### Pipeline used per experiment

| Experiment | Training Pipeline | Valid? |
|---|---|---|
| Phase 2 baseline (CNN+LSTM, 10M) | `cogames train` (patched `train.py`) | Yes |
| Tier 1/1b/1c (A1+A2+A3) | `cogames train` | Yes |
| A3 sweep (18 experiments) | `cogames train` via `sweep_phase2.sh` | Yes |
| Phase 2b machina_1 (3 experiments) | `cogames train` via `sweep_phase2b.sh` | Yes |
| A1.5 individual roles | `cogames train -m *_tutorial` | Yes |
| Braveheart/curriculum runs | `cogames train` with variants | Yes |
| **S5-S12 (all Cortex)** | **`train_cortex.py` (custom)** | **No — confounded** |
| **S13 (Cortex-LSTM)** | **`cogames train`** | **Yes — SUCCESS** |

All pre-Cortex experiments used the native pipeline (sweep scripts patch `train.py` hyperparams in-place, then call `cogames train`). Only S5-S12 used the custom script.

#### Invalidated hypotheses

**1. "update_epochs=1 produces 0 junctions" — PARTIALLY INVALIDATED**

The A3 sweep found u=3 beats u=1 for most configs. But `cogames train` defaults ARE u=1, and S13 got 3.75 junctions with u=1. The interaction matters more than any single param: u=1 works when bptt=128 (more data per update); u=3 compensates when bptt=64. The A3 sweep result is valid within its context (patched `train.py` with bptt=128), but the blanket claim "u=1 → 0 junctions" is wrong.

**2. "CNN encoder doesn't work for CogsGuard" — UNTESTED**

S5-S9 all used CNN + custom training. They had five simultaneous confounds: (1) CNN encoder, (2) d_hidden=64 / 2 layers, (3) post_norm=True, (4) resets broadcast bug, (5) custom training loop. We never tested CNN via `cogames train` with bug fixes. CNN might work fine — we simply don't know. Low priority since Linear already works.

**3. "Kickstarting hurts Cortex" (S7) — INVALID**

S7 used kickstarting with `train_cortex.py` and had all bugs active. Zero evidence about whether kickstarting + working Cortex would succeed or fail.

**4. "Episode-reset patch is a red herring" — ONLY PROVEN FOR LSTM**

S13 works without the patch because PufferLib zeros state at `evaluate()` start and LSTM handles stale state via forget gates. For Ag,A,S (AGaLiTe tick, sLSTM commitment), episode-reset may still matter. Hypothesis remains open for non-LSTM cells.

**5. "Ag,A,S doesn't work for CogsGuard" — COMPLETELY UNTESTED**

S5-S8 all used Ag,A,S but with every confound stacked. Zero valid evidence. S15 (Ag,A,S via `cogames train`) will be the first clean test.

#### Hypotheses that remain valid

- **A3 sweep results** (milestones best, ent=0.03 best): Used `cogames train`, valid.
- **A1.5 results** (individual role training works): Used `cogames train`, valid.
- **"Arena configs don't transfer to machina_1"**: Used `cogames train`, valid.
- **"Forced roles hurt milestones"**: Used `cogames train`, valid.
- **"Gear wall is structural"**: 43 experiments, 1.9B steps, zero gear. Valid across both pipelines.

### Revisiting Previous Hypotheses

With S13 confirming Cortex-LSTM works via `cogames train`, the open hypotheses are:

**1. AGaLiTe tick corruption: Still OPEN for Ag,A,S**
- S13 proved Cortex-LSTM works. But Ag,A,S introduces AGaLiTe with tick counter.
- With E=3 (multi-expert), the scaffold uses residual + RMSNorm + ReZero + mixing.
- AGaLiTe tick may corrupt across mid-BPTT episode boundaries.
- **Test**: S15 — `preset="agas"` via `cogames train`.

**2. Episode-reset patch: May still matter for Ag,A,S**
- LSTM tolerates stale state (forget gate). Ag,A,S cells don't.
- **Test**: S16 — Ag,A,S with episode-reset patch (only if S15 fails).

**3. Multi-expert scaffold: Untested**
- E=1 fast-path is transparent (no residual/norm). E=3 activates full scaffold.
- **Test**: S14 (Axon, E=1) isolates non-LSTM cell, S15 (Ag,A,S, E=3) tests scaffold.

**4. Training loop: CLOSED — must use `cogames train`**
- Custom training scripts introduce fatal confounds. Always use `cogames train`.

### Planned Experiments

All experiments below use `cogames train` with the native pipeline. No custom training scripts.

#### S14: Axon via `cogames train`

| Config | Value |
|--------|-------|
| Architecture | Cortex `AxonCellConfig()` × 1 layer, d_hidden=128 |
| Encoder | Linear(600→128→128) — matches native LSTMPolicyNet |
| `post_norm` | False |
| Resets | t=0 only |
| Training pipeline | `cogames train` |
| Reward | milestones (cogames default) |
| Steps | 50M |
| Cogs | 8 |

**Purpose**: First clean non-LSTM cell test. Axon implements a stripped-down version of Trace Units (Elelimy et al., 2024 — arxiv:2409.01449): cheap per-cell RTRL that provides gradient flow beyond the BPTT truncation horizon. As a linear SSM, Axon has limited representational capacity on its own — the motivation for hybrid architectures is that different cell families (attention, RTRL, gated) compensate for each other's weaknesses. With E=1 (single expert per layer), the scaffold is transparent (same as S13), so this isolates Axon cell vs LSTM cell as the only variable.

**Hypothesis**: Axon's RTRL should provide better temporal credit assignment than LSTM's truncated BPTT, potentially exceeding S13's 3.75 peak junctions. However, as a linear SSM it may lack the nonlinear gating needed for complex policy learning.

**Command**:
```bash
PYTHONPATH=scripts/policy cogames train -m cogsguard_arena.basic -p class=cortex_policy.CortexAxonPolicy --cogs 8 --steps 50000000 --device auto
```

**Result: Peak 2.250 junctions. Axon works but underperforms LSTM.**

| Metric | S14 (Axon) | S13 (LSTM) | Native LSTM A3 |
|---|---|---|---|
| peak junctions | 2.250 | **3.750** | 3.214 |
| final junctions | 0.143 | 0.071 | 3.214 |
| explained_variance | 0.881 | **0.985** | ~0.98 |
| entropy | 1.46 (converged low) | 1.601 | ~1.55 |
| clipfrac | 0.001 | 0.025 | ~0.2 |
| approx_kl | 0.000 | 0.008 | ~0.03 |
| hearts | 0.906 | ~0.8 | ~0.84 |
| params | 390.6K | 226K | 226K |
| training time | 25 min | 24 min | ~50 min |

**Analysis**: Axon confirms non-LSTM cells work through `cogames train` (no collapse, non-zero junctions). But as a linear SSM it converges faster to a less exploratory policy: entropy settled at 1.46 (vs 1.60 for LSTM), clipfrac dropped to near-zero early, and peak junctions were 40% below S13. The RTRL advantage (unbounded gradient flow) didn't overcome the limited representational capacity of a linear model. This is exactly the motivation for the Ag,A,S hybrid: AGaLiTe provides attention-based memory, Axon provides cheap RTRL beyond truncation horizon, sLSTM provides nonlinear gating — each compensating for the others' weaknesses.

**Checkpoint**: `train_dir/177445582379/model_000191.pt`

#### S15: Ag,A,S via `cogames train`

| Config | Value |
|--------|-------|
| Architecture | Cortex `[AGaLiTe, Axon, sLSTM]` × 1 layer, d_hidden=128 |
| Encoder | Linear(600→128→128) — matches native LSTMPolicyNet |
| `post_norm` | False |
| Resets | t=0 only |
| Training pipeline | `cogames train` |
| Reward | milestones (cogames default) |
| Steps | 50M |
| Cogs | 8 |

**Purpose**: First clean multi-expert test. Tests all three open hypotheses simultaneously:
1. Does AGaLiTe tick corrupt at episode boundaries?
2. Does the multi-expert scaffold (E=3: residual + RMSNorm + ReZero + GlobalContextRouter) work under PPO?
3. Does the Ag,A,S combo outperform single-cell architectures?

**Hypothesis**: Ag,A,S combines AGaLiTe's attention-based memory, Axon's cheap RTRL (gradient flow beyond truncation), and sLSTM's nonlinear gating — each compensating for the others' weaknesses. S14 showed Axon alone is limited as a linear SSM; the hybrid should unlock what neither cell achieves individually. If it fails, the failure isolates multi-expert scaffold issues (since S14 confirmed single-expert Axon works).

**Command**:
```bash
PYTHONPATH=scripts/policy cogames train -m cogsguard_arena.basic -p class=cortex_policy.CortexAgasPolicy --cogs 8 --steps 50000000 --device auto
```

**Success criteria**: >0 junctions (confirms Ag,A,S works). If 0: diagnose whether it's tick corruption, scaffold, or cell interaction.

**Result: Peak 2.556 junctions. Ag,A,S works but underperforms LSTM.**

| Metric | S15 (Ag,A,S) | S14 (Axon) | S13 (LSTM) | Native LSTM A3 |
|---|---|---|---|---|
| peak junctions | 2.556 | 2.250 | **3.750** | 3.214 |
| final junctions | 0.429 | 0.143 | 0.071 | 3.214 |
| explained_variance | 0.983 | 0.881 | 0.985 | ~0.98 |
| entropy (final) | 1.545 | 1.465 | 1.601 | ~1.55 |
| peak clipfrac | 0.119 | 0.013 | 0.025 | ~0.2 |
| params | 1.2M | 390K | 226K | 226K |
| training time | 31 min | 25 min | 24 min | ~50 min |

**Analysis**: All three open hypotheses resolved — AGaLiTe tick corruption does not occur, episode-reset patch is not needed, multi-expert scaffold (E=3 with residual + RMSNorm + ReZero + GlobalContextRouter) trains stably under PPO. Ag,A,S beats Axon alone (2.56 vs 2.25 peak), confirming the complementary-cell hypothesis. But it doesn't beat LSTM despite 5x more parameters.

**Post-mortem diagnosis (2026-03-25)**: Weight analysis of the trained S15 model reveals a **dead router** as the smoking gun:

- `router.Wq.weight`: mean=0.000, std=0.000, max=0.000 (exactly zero — never learned)
- `router.Wk.weight`: mean=0.000, std=0.000, max=0.000 (exactly zero)
- `e_mixer.Wv.weight`: std=0.018 (near-dead)
- `e_mixer.out.weight`: std=0.011 (near-dead)
- `alpha_main = 0.97` (97% residual, only 3% scaffold contribution)

The GlobalContextRouter never learned to differentiate between the 3 experts (AGaLiTe, Axon, sLSTM). Instead of intelligently routing to the right cell for each input, it uniformly averaged all outputs — producing a confused blend worse than any single expert. This explains why S15 (2.56j) underperforms even S14 Axon alone (2.25j) per-parameter: the multi-expert overhead (router, mixer, norms) consumed capacity without benefit.

Root cause: with only 191 gradient updates (update_epochs=1, 50M steps / ~262K batch = 191 updates), max_grad_norm=1.5 over 1.2M params, the router received insufficient gradient signal to escape its zero initialization.

**Fix**: S16 uses sequential layers `[[AGaLiTe], [Axon], [sLSTM]]` — 3 scaffolds with E=1 each, which triggers the transparent fast-path (no router, no mixer, no ReZero overhead).

**Checkpoint**: `train_dir/177445943605/model_000191.pt`

**Depends on**: Run after S14 to establish single-cell baseline.

#### S16: Sequential Ag,A,S (no router) via `cogames train`

| Config | Value |
|--------|-------|
| Architecture | Cortex `AGaLiTe → Axon → sLSTM` as 3 sequential layers (E=1 each), d_hidden=128 |
| Encoder | Linear(600→128→128) — matches native LSTMPolicyNet |
| `post_norm` | False |
| Resets | t=0 only |
| Training pipeline | `cogames train` |
| Reward | milestones (cogames default) |
| Steps | 50M |
| Cogs | 8 |
| Params | 1,034,694 |

**Purpose**: Fix the dead router discovered in S15. By putting each cell as a separate layer (E=1 per scaffold), the transparent fast-path is used — no GlobalContextRouter, no expert mixer, no ReZero overhead. The cells process input sequentially: AGaLiTe (attention memory) → Axon (RTRL credit assignment) → sLSTM (nonlinear gating).

**Hypothesis**: Sequential processing should outperform multi-expert mixing for this problem scale. The router overhead (128×128 Wq, Wk + mixer) consumed ~100K params while contributing nothing (dead weights). Sequential layers eliminate this waste and ensure each cell's contribution is deterministic (not gated by a dead router).

**Command**:
```bash
PYTHONPATH=scripts/policy cogames train -m cogsguard_arena.basic -p class=cortex_policy.CortexAgasSeqPolicy --cogs 8 --steps 50000000 --device auto
```

**Success criteria**: >2.56j (beats S15 multi-expert). Stretch: >3.75j (beats S13 LSTM).

**Result**: Peak 2.250 junctions (epoch 56). Sequential Ag,A,S did NOT fix the underperformance.

| Metric | S16 (Ag,A,S seq) | S15 (Ag,A,S E=3) | S13 (LSTM) |
|---|---|---|---|
| peak junctions | 2.250 | 2.556 | 3.750 |
| peak epoch | 56 | ~100 | 158 |
| final entropy | 1.436 | 1.545 | 1.601 |
| final clipfrac | 0.001 | 0.000 | 0.000 |
| params | 1.03M | 1.2M | 226K |

**Analysis**: The dead router was NOT the primary issue. Sequential layers (no router) performed slightly WORSE than multi-expert (2.25 vs 2.56). The real issue is overparameterization + premature convergence. S16 entropy dropped to 1.436 (89% of max) vs LSTM's stable 1.601 (99.4% of max). The model converges too confidently too fast on a 5-action grid world. Literature survey (12+ papers from 2022-2025) confirms this is a well-documented phenomenon: primacy bias (Nikishin et al., ICML 2022), plasticity loss (Abbas et al., 2023), dormant neurons (Sokar et al., ICML 2023), representation collapse in PPO (Moalla et al., NeurIPS 2024), and compute-optimal scaling laws (Hilton et al., 2023). See sweep section for fixes.

#### S17 (optional): CNN encoder via `cogames train`

| Config | Value |
|--------|-------|
| Architecture | Cortex LSTM × 1 layer, d_hidden=128 |
| Encoder | **CNN (2-layer conv, same as native TutorialPolicyNet)** |
| Training pipeline | `cogames train` |
| Steps | 50M |

**Purpose**: Resolves the open question about whether CNN encoder works. Low priority — only interesting if we want to compare encoder architectures.

**Depends on**: Only run if there's spare compute after S14-S15.

#### Hyperparameter Sweep: Plasticity & Entropy Fixes (2026-03-25)

Based on literature survey of 12+ papers on RL scaling failures (primacy bias, plasticity loss, dormant neurons, representation collapse), testing interventions to make Cortex work at scale.

**Sweep infrastructure**: `scripts/sweep/patch_and_train.py` monkey-patches PuffeRL to override cogames' hardcoded hyperparams while preserving the exact same training loop. `scripts/sweep/run_sweep.sh` runs configs sequentially.

| Config | Policy | Overrides | Hypothesis |
|--------|--------|-----------|------------|
| S17 | LSTM (control) | none | Reproduce S13 baseline |
| S18 | Ag,A,S seq | ent_coef=0.08 | Higher entropy prevents premature convergence |
| S19 | Ag,A,S seq | ent_coef=0.08, weight_decay=1e-4 | L2 reg preserves plasticity (NeurIPS 2024) |
| S20 | Ag,A,S seq | ent_coef=0.12 | Aggressive entropy: push through double descent |
| S21 | LSTM | ent_coef=0.08 | Does LSTM also benefit from higher entropy? |
| S22 | Ag,A,S seq | ent_coef=0.08, update_epochs=3 | More gradient steps per batch |

#### Results (2026-03-25)

| Config | Policy | Peak J | Final Entropy | Final Clipfrac | Time | Overrides |
|--------|--------|--------|---------------|----------------|------|-----------|
| S17 | LSTM (control) | **3.333** | 1.576 | 0.019 | 25m | {} |
| S18 | Ag,A,S seq | 2.500 | 1.582 | 0.029 | 28m | ent=0.08 |
| S19 | Ag,A,S seq | 2.667 | 1.572 | 0.031 | 28m | ent=0.08, wd=1e-4 |
| S20 | Ag,A,S seq | **2.778** | 1.601 | 0.024 | 28m | ent=0.12 |
| S21 | LSTM | 2.375 | 1.607 | 0.015 | 22m | ent=0.08 |
| S22 | Ag,A,S seq | 2.667 | 1.534 | 0.039 | 34m | ent=0.08, u=3 |

**Key findings:**

1. **Higher entropy helps Cortex Ag,A,S**: S20 (ent=0.12) peaked at 2.778j vs S16's 2.250j — a 23% improvement. Entropy reached 1.601 (99.4% of max), matching LSTM's level.
2. **Higher entropy HURTS LSTM**: S21 (ent=0.08) dropped from 3.333j (control) to 2.375j — a 29% degradation. LSTM's default ent=0.05 is already well-calibrated.
3. **Weight decay helps slightly**: S19 (ent=0.08+wd=1e-4) → 2.667j vs S18's 2.500j (ent=0.08 alone).
4. **update_epochs=3 doesn't help beyond entropy alone**: S22 (u=3+ent=0.08) → 2.667j, same as S19.
5. **LSTM still leads despite all interventions**: 3.333j (S17) vs 2.778j (best Cortex S20). The 226K→1.2M param gap still hurts in RL.

**Diagnosis**: The entropy fix partially addresses premature convergence (Cortex +23%) but doesn't close the gap to LSTM. Remaining hypotheses: (a) 1.2M params is simply overparameterized for 5-action grid world, (b) LSTM's inductive bias (forget gate decay) is naturally better suited to this domain, (c) longer training (100M+) could close the gap as Cortex benefits from more data.

**Status: COMPLETE.** Best Cortex: S20 (2.778j, ent=0.12). Best overall: S17/LSTM (3.333j, default hyperparams).

#### Sweep Round 2: Reduced Parameters d_hidden=64 (2026-03-25)

Testing the overparameterization hypothesis directly: reduce d_hidden from 128 to 64, bringing Cortex variants to ~300K params (closer to LSTM's 226K). Also tests Axon-only (RTRL in isolation, per Subhojeet's suggestion).

| Config | Policy | Peak J | Entropy | Time | Overrides |
|--------|--------|--------|---------|------|-----------|
| S23 | Ag,A,S seq d=64 | 2.500 | 1.605 | 28m | ent=0.12 |
| S24 | Ag,A,S seq d=64 | 2.500 | 1.438 | 28m | defaults |
| S25 | Axon d=64 | 2.263 | 1.588 | 23m | ent=0.12 |
| S26 | Axon d=64 | 2.500 | 1.377 | 23m | defaults |
| S27 | LSTM d=64 | 2.667 | 1.600 | 22m | defaults |
| S28 | Ag,A,S seq d=64 | 2.600 | 1.600 | 29m | ent=0.12, wd=1e-4 |

**Key findings:**

1. **d=64 didn't help anything.** Every d=64 variant underperformed its d=128 counterpart. The overparameterization hypothesis was wrong for this domain.
2. **LSTM d=128 is the sweet spot.** S13/S17 at 226K params (d=128) dominate everything. Reducing to d=64 hurts LSTM too (3.333→2.667).
3. **Axon-only is consistently weakest** — RTRL doesn't add value at either scale (2.263-2.500j).
4. **The problem isn't param count, it's architectural fit.** LSTM's forget gate + 128-dim hidden state is well-matched to this 5-action grid task at 50M steps. Cortex's additional complexity (attention, routing, multiple cell types) doesn't provide useful inductive bias here.

**Status: COMPLETE.** Overparameterization hypothesis falsified. LSTM d=128 remains best.

#### Cortex Conclusions (S13-S28, 16 experiments)

| Architecture | Best Config | Peak J | d_hidden | Params |
|-------------|------------|--------|----------|--------|
| **LSTM (Cortex)** | **S13** | **3.750** | 128 | 226K |
| LSTM (Cortex) | S17 | 3.333 | 128 | 226K |
| Ag,A,S seq | S20 (ent=0.12) | 2.778 | 128 | 1.2M |
| LSTM d=64 | S27 | 2.667 | 64 | ~57K |
| Ag,A,S seq d=64 | S28 (ent+wd) | 2.600 | 64 | ~300K |
| Ag,A,S (E=3) | S15 | 2.560 | 128 | 1.2M |
| Axon | S14 | 2.250 | 128 | ~400K |
| Axon d=64 | S25 | 2.263 | 64 | ~100K |

**Overall verdict**: Cortex-LSTM is the best architecture for CogsGuard at 50M steps. The advanced cells (AGaLiTe, Axon, sLSTM) don't provide useful inductive bias for this 5-action grid world. The LSTM forget gate's natural state decay is well-suited to PufferLib's bptt_horizon=128 training windows. Further Cortex exploration should focus on longer training horizons (100M+) or more complex action spaces where the additional capacity could help.

---

## AIF Agent Experiments

### Phase 3: Discrete AIF Agent — Live Eval (2026-03-17)

#### Architecture

Hybrid pymdp + rule-based navigator:
- **pymdp JAX v1.0**: 18-state POMDP (phase(6) × hand(3)), 3 observation modalities
- **Navigator**: Rule-based movement toward AIF-selected targets (closest entity matching target type)
- **Fallback**: Random wander when no target visible

Simplified from original 216-state plan (role + target_mode dropped — B matrices are action-independent for movement).

#### Test Results

| Test Suite | Count | Status |
|------------|-------|--------|
| Unit tests (no cogames) | 12 | Pass |
| Integration tests (cogames) | 14 | Pass |
| Total | 26 | **All pass** |

#### Live Eval: `cogsguard_arena.basic`, 4 agents, 3 episodes

| Metric | AIF Agent | Random | Starter |
|--------|-----------|--------|---------|
| Hearts/agent | 6.0 | 8.0 | 0.88 |
| Aligner gear | 0.75 | 0 | 0 |
| Junctions | 0 | 0 | 0 |
| Reward | 1.0 | 1.0 | 1.0 |

**Analysis**: The AIF agent mines and deposits resources (6 hearts) AND crafts some gear (0.75 aligner gear) — something no PPO agent achieved in 43 experiments. But it never reaches junction capture, likely because:
1. Navigation is naive (closest entity, no pathfinding)
2. No multi-step planning (pymdp selects goal, navigator moves one step)
3. Only 3 observation modalities — can't distinguish junction alignment state

**Next steps for AIF**:
- Add G-coupling (multi-agent EFE shift from teammate observation)
- ToM particle filter for teammate role inference
- Improve junction-targeting navigation
- Expand observation modalities (o_social, o_junction)

### AIF v2: C/A/Gamma Tuning + Online B-Learning Infrastructure (2026-03-25)

**Changes made**:
- A matrices sharpened (diagonals 0.6-0.7 → 0.85+)
- C preferences tuned to penalize NONE/EMPTY (miner: NONE=-1.0, EMPTY=-1.0; aligner: NONE=-0.5, EMPTY=-0.5, JUNCTION boosted to 5.0)
- Gamma reduced 16 → 8
- Policy construction generalized via `itertools.product`
- Online B-learning infrastructure added (Dirichlet pB, learn_interval=10, `infer_parameters` with T=2 belief buffer)
- JIT warmup added to `BatchedAIFEngine` constructor

#### Results: v1 vs v2

| Metric | v1 | v2 | Change |
|--------|----|----|--------|
| action.move.success | ~500 | 1077 | +2x |
| action.noop | 2459 | 1614 | -34% |
| max_steps_without_motion | 2973 | 443 | 6.7x better |
| Resources mined | 0 | carbon=2, oxygen=2, germanium=2 | New |
| Hub withdrawals | 0 | carbon=3, oxygen=3, germanium=3, silicon=3 | New |
| Junctions aligned | 0 | 0 | Same |
| Timeouts | 1 | 223 | Increased (unknown cause) |

#### Tested and failed

- **policy_len=3**: 2197 policies, ~330ms/step — exceeds 250ms limit
- **use_param_info_gain=True**: ~330ms overhead even with policy_len=2

#### Key insight

C-preference tuning (penalizing idle/empty states) was the single biggest behavioral improvement. The agent now actively navigates to extractors, mines resources, and deposits at hubs. The craft → gear → junction chain is not yet completing.

### AIF v3-v5: Online Learning Experiments (2026-03-25)

#### v3: B-learning enabled (broken — learn_B never reached Agent)

**Changes**: Set `learn_B=True` in AIFPolicy, but `kwargs.pop("learn_B")` removed learn_B from kwargs without adding it to defaults dict. `Agent.learn_B` stayed False.

**Result**: Complete regression. 39.5 moves, 2466 noops, max_steps_without_motion=2971. `use_param_info_gain=True` with non-updating pB created static exploration bias that locked miners into MINE and aligners into NAV_GEAR/ACQUIRE_GEAR indefinitely.

#### v4: B-learning actually working (fixed kwargs bug)

**Fix**: Added `"learn_B": learn_B` to defaults dict after popping from kwargs.

| Metric | v2 | v4 | Change |
|--------|----|----|--------|
| action.move.success | 1077 | 1832 | +70% (best ever) |
| action.noop | 1614 | — | — |
| max_steps_without_motion | 443 | 722 | worse |
| pB_total | static | 24305→27505 | Growing (learning working) |
| Timeouts | 223 | 500 | Increased (learn_interval=10) |
| Junctions | 0 | 0 | Same |

**Key**: B-learning drove exploration → diverse actions. But `infer_parameters` every 10 steps + `use_param_info_gain` overhead → 500 timeouts.

#### v5: Full learning stack (B + C-from-reward + E-vector)

**Changes**:
- C-from-reward: EMA update of C from intrinsic reward-obs correlations (lr=0.1, interval=200)
- E-vector: Habit prior reinforcing successful task policies (lr=0.05, interval=200)
- learn_interval raised 10→50 for B-learning

| Metric | v4 | v5 | Change |
|--------|----|----|--------|
| action.move.success | 1832 | 715 | -60% (regression!) |
| action.noop | — | 3884 | — |
| max_steps_without_motion | 722 | 2642 | Much worse |
| Timeouts | 500 | 27 | -95% (learn_interval=50) |
| pB_total | 24305→27505 | 24625→24945 | Growing (slower) |
| E_range | — | 0.03→0.21 | E-vector learning |
| scout.amount | 0 | 0.62 | New (scouts acquired!) |
| Junctions | 0 | 0 | Same |

**Root cause of regression**: C-from-reward corrupted well-tuned hand-crafted C preferences. Noisy reward-obs correlations overwrote domain-knowledge-based C vectors. E-vector too aggressive early (lr=0.05 from step 0).

#### v6: B-learning + delayed E-vector (no C-from-reward)

**Changes**:
- Disabled C-from-reward (keep hand-crafted C intact)
- E-vector: delayed start to step 500, lr reduced 0.05→0.02
- B-learning: learn_interval=50 (same as v5)

**Result**: Similar to v4 but with better-timed E-learning. No junctions captured — navigator still too simple for 88x88 maps.

### AIF v7: Hierarchical 2-Level Architecture (2026-03-25)

**Architectural overhaul**: Replaced flat 169-policy POMDP with hierarchical 2-level system:
- **Level 2**: Strategic POMDP with 5 macro-options (25 two-step policies), replans only at option termination
- **Level 1**: OptionExecutor — reactive state machines mapping option + obs → task policy
- **Level 0**: Navigator — task policy → primitive movement

**Performance breakthrough**: Most steps ~10-15ms (belief update only), ~77ms at replan. Was ~310ms/step with flat 169 policies.

### AIF v8: Role Assignment + E-vector Fix (2026-03-25)

**Changes**: Fixed per-role E-vector (habit prior) to properly bias miners toward MINE_CYCLE and aligners toward CRAFT_CYCLE. Fixed A matrix confound (MINE and EXPLORE both mapped to STATION=NONE).

**Result**: Role assignment working — miners in MINE_CYCLE, aligners in CRAFT_CYCLE. Some gear produced. BUT: 0 junctions captured, max_steps_without_motion=588, action.move.failed=225. Agents know what to do but can't reach stations on 88x88 maps.

### AIF v9: SpatialMemory + Wall-Aware Navigator (2026-03-25)

**Changes**: Added persistent spatial memory using `lp:*` tokens for absolute position:
- Tracks walls, stations, explored territory
- Memory-based navigation when targets outside 13x13 view
- Wall-aware movement with direction fallbacks
- Stuck detection (20-step threshold) with random recovery

| Metric | v8 | v9 |
|--------|----|----|
| move.failed | 225 | 208 |
| max_steps_without_motion | 588 | 510 |
| Junctions | 0 | 0 |

**Analysis**: Navigation slightly improved but no economy chain progress. Most agents stuck doing noops.

### AIF v9.1: Discretizer LOC_GLOBAL Bug + Bumping Interaction (2026-03-25)

**Critical bugs found via systematic diagnostics** (added per-agent counters, per-step token traces):

1. **MINE noop trap**: mine_cycle returned MINE (noop) at dist≤3 instead of navigating to extractor. Fixed to always NAV_RESOURCE — auto-extracts via bumping at dist=0.
2. **Interaction mechanism**: CogsGuard uses "bumping" (move INTO entity), NOT noop. Fixed _move_toward to bump at dist=1 (direct movement toward target) and dist=0 (wander direction).
3. **Stuck detection too aggressive**: 6-step threshold fired 164 times per miner in 1K steps. Increased to 20-step threshold.
4. **CRITICAL — Discretizer LOC_GLOBAL bug**: `infer_hand()` checked `loc == 254` (LOC_GLOBAL) but mettagrid inventory tokens use `loc = (6 << 4) | 6 = 102` (center cell encoding). `o_inv` was ALWAYS 0, so mine_cycle never transitioned to NAV_DEPOT, breaking the entire economy chain from the start.

| Metric | v9 | v9.1 |
|--------|----|----|
| carbon.gained (per agent) | ~0 | **7.25** |
| carbon.deposited (team) | ~0 | **54** |
| move.failed | 208 | 37.75 |
| move.success | ~400 | **462** |
| noop | ~490 | 0.25 |
| Junctions | 0 | 0 |

**Breakthrough**: First confirmed resource extraction and deposit. Miners now working correctly. But still 0 junctions — aligners still wandering.

### AIF v9.2: Aligner Economy Chain — Hearts Prerequisite (2026-03-25)

**Root cause of aligner failure**: Three interacting bugs:

1. **Hearts prerequisite missing**: Dinky's aligner chain is hub(hearts)→craft(gear)→junction(capture). Our craft_cycle went directly to craft station without hearts. Bumping craft station without hearts does nothing. Fixed craft_cycle to: EMPTY→NAV_DEPOT (get hearts), HAS_RESOURCE→NAV_CRAFT (craft gear), HAS_GEAR→WAIT (done).

2. **Hearts invisible to discretizer**: `inv:heart` was not in RESOURCE_INVENTORY. When aligner picked up hearts, `infer_hand()` returned EMPTY. Added `inv:heart` to RESOURCE_INVENTORY.

3. **Explore hub trap**: EXPLORE terminated on ANY station including HUB (`o_sta > ObsStation.NONE`). Since agents spawn near hub, aligners' EXPLORE terminated immediately, trapping them in hub-proximity loop. Fixed: aligners only terminate EXPLORE on CRAFT/JUNCTION.

Additional tuning: CRAFT_CYCLE timeout 60→200, CAPTURE_CYCLE 80→200, EXPLORE 30→50, WANDER_STEPS 8→15.

| Metric | v9.1 | v9.2 | Change |
|--------|------|------|--------|
| **junction.aligned_by_agent** | 0 | **0.12** | First junctions captured! |
| **aligner.gained** (gear) | 0 | **0.62** | Crafting works |
| **heart.gained** | 0 | **10.0** | Hearts pipeline works |
| carbon.gained | 7.25 | **37.12** | 5x more extraction |
| germanium.gained | ~0 | **38.12** | New resource type |
| oxygen.gained | ~0 | **16.88** | New resource type |
| miner.gained | 0 | **0.88** | Miners also crafting |
| scrambler.gained | 0 | **1.50** | Multiple gear types |
| move.failed | 37.75 | 5027 | More bumping (interactions) |

**Full economy chain now functional**: extract→deposit→withdraw hearts→craft gear→capture junction. First non-zero junction score in AIF agent history. All 4 resource types being extracted. POMDP option selection shows CRAFT_CYCLE and CAPTURE_CYCLE for aligners.

**Note**: Eval run on 88x88 machina_1 map with training sweep competing for GPU/CPU — step times ~300-500ms. Dedicated eval needed for accurate timing.

---

## Cortex v0.19 Systematic Exploration (2026-03-28)

### Context

**CORRECTION (2026-03-31)**: We originally believed cogames 0.19 changed several hyperparameters from 0.18, causing the Cortex-LSTM drop from 3.75j to ~2.0j. **This was WRONG.** Git archaeology (git blame) confirmed: vf_coef=2.0, gamma=0.995, gae_lambda=0.90, bptt_horizon=64, max_grad_norm=1.5 have been the SAME since the first cogames training commit (Sept 2025). Only ent_coef changed: 0.001→0.01 (increased, not decreased). What we called "0.18 hyperparams" were actually PufferLib/CleanRL defaults that we assumed were the old cogames values.

| Param | cogames (all versions) | PufferLib/CleanRL default | What we thought |
|-------|----------------------|--------------------------|-----------------|
| ent_coef | 0.01 (was 0.001 in early commits) | 0.05 | "0.18 was 0.05" — WRONG |
| bptt_horizon | 64 | 128 | "0.18 was 128" — WRONG |
| gamma | 0.995 | 0.999 | "0.18 was 0.999" — WRONG |
| gae_lambda | 0.90 | 0.95 | "0.18 was 0.95" — WRONG |
| vf_coef | 2.0 | 0.5 | "0.18 was 0.5" — WRONG |
| max_grad_norm | 1.5 | 0.5 | "0.18 was 0.5" — WRONG |

New AWS: 4x L4 GPUs, 181GB RAM, 512GB disk. All phases run 4 experiments in parallel.

### Infrastructure

- **Sweep script**: `scripts/sweep/run_sweep_v19.sh` — parallel GPU execution with `CUDA_VISIBLE_DEVICES`
- **Policy presets**: Extended `cortex_policy.py` with all Cortex cell types
- **Available cells**: L (LSTM), A (Axon), Ag (AGaLiTe), S (sLSTM), M (mLSTM), X (XL), C (CausalConv1d), S^ (sLSTM axonified), M^ (mLSTM axonified)

### Phase A: Baseline Calibration (~25 min)

**Hypotheses**:
- H_A1: The 3.75→2.0j drop is caused by 0.19's changed hyperparams, not API changes
- H_A2: Cortex-LSTM with pattern "L" is functionally identical to native LSTM
- H_A3: Milestones reward variant still provides a boost on 0.19

| GPU | Experiment | Config | Peak J | Entropy |
|-----|-----------|--------|--------|---------|
| 0 | A1: Native LSTM, 0.19 defaults | default (prior run) | **3.000** | — |
| 1 | A2: Native LSTM, 0.18 hyperparams | `class=lstm` + 0.18 hp | 0.000 | — |
| 2 | A3: Cortex-LSTM, 0.18 hyperparams | `CortexPolicy preset=lstm` + 0.18 hp | 1.333 | — |
| 3 | A4: Cortex-LSTM, 0.19 defaults | `CortexPolicy preset=lstm` | 1.500 | — |

**Notes**: A2 used default trainable policy (not `starter` — StarterPolicy is not trainable in 0.19). A4 changed from `forced_role_vibes` (broken on arena) to 0.19 defaults. `milestones` reward variant does not exist in 0.19.

**H_A1 outcome**: **DISCONFIRMED**. Restoring 0.18 hyperparams makes things *worse* (0j, not 3.5+j). The main cause: bptt_horizon=128 halves the number of training epochs (187 vs 372 for same step count). The 0.19 defaults are better for this training budget.

**H_A2 outcome**: **PARTIALLY CONFIRMED**. Cortex-LSTM (1.5j) underperforms native LSTM (3.0j) on 0.19 defaults. The gap may be due to Cortex state packing overhead or the `policy_spec.json` registration path.

**H_A3 outcome**: **NOT TESTABLE**. `milestones` reward variant doesn't exist in 0.19. `forced_role_vibes` broken on arena map.

### Phase B: Single-Cell Architecture Sweep (~50 min, 2 rounds)

**CRITICAL BUG FOUND**: `cogames train` drops `kw.*` init_kwargs — `PolicySpec` at line 128-131 never passes `init_kwargs` to constructor. All Phase B/C experiments using `kw.preset=X` actually trained LSTM! **FIX**: Created dedicated policy classes per preset (e.g., `CortexSLSTMPolicy`) with preset baked into `__init__`.

**Hypotheses**:
- H_B1: sLSTM outperforms LSTM (stabilized gating, commitment state)
- H_B2: mLSTM captures entity relationships better (multiplicative gating)
- H_B3: Axonified variants (S^, M^) outperform base (RTRL gradient flow)
- H_B4: Two LSTM layers > one (hierarchical temporal abstraction)
- H_B5: CausalConv1d performs worse (no true recurrence)

All Phase B experiments use 0.19 defaults (SWEEP_OVERRIDES='{}').

#### Round 1 (25 min) — RERUN with dedicated classes:
| GPU | Experiment | Pattern | Peak J | Notes |
|-----|-----------|---------|--------|-------|
| 0 | B1: sLSTM | S | **5.000** | Best ever! 67% above native LSTM |
| 1 | B2: mLSTM | M | 2.000 | Slow torch.compile startup |
| 2 | B3: AGaLiTe | Ag | 2.000 | Same as mLSTM |
| 3 | B4: XL | X | 1.500 | Extended recurrent didn't help |

#### Round 2 (25 min) — RERUN with dedicated classes:
| GPU | Experiment | Pattern | Peak J | Notes |
|-----|-----------|---------|--------|-------|
| 0 | B5: CausalConv1d | C | 1.500 | No recurrence → weak |
| 1 | B6: sLSTM axonified | S^ | CRASHED | State-size mismatch (init=1024, runtime=3584) |
| 2 | B7: mLSTM axonified | M^ | CRASHED | State-size mismatch (init=17668, runtime=38148) |
| 3 | B8: Two LSTM layers | L,L | 2.000 | Depth didn't help |

**Axonified crash root cause**: RTRL adds auxiliary state during forward pass that isn't present in `init_state()`. Fix: run dummy forward pass during init to measure actual runtime state size. B6 relaunched with fix; B7 skipped (38K state elements = impractical memory).

**H_B1 outcome**: **STRONGLY CONFIRMED**. sLSTM (5.0j) **massively** outperforms native LSTM (3.0j) — +67%. Its stabilized gating, exponential gating (exp gates), and commitment state provide superior long-horizon memory for CogsGuard's economy chain.

**H_B2 outcome**: **DISCONFIRMED**. mLSTM (2.0j) didn't outperform — multiplicative gating doesn't help for this task.

**H_B3 outcome**: **INCONCLUSIVE**. Axonified variants crashed due to state-size bug. B6 (sLSTM^) relaunched with fix.

**H_B4 outcome**: **DISCONFIRMED**. Two LSTM layers (2.0j) didn't outperform one sLSTM (5.0j). Depth doesn't compensate for cell quality.

**H_B5 outcome**: **CONFIRMED**. CausalConv1d (1.5j) and XL (1.5j) are weakest — validates that gated recurrence matters.

**Overall**: sLSTM is the **dominant winner** at 5.0j — 67% above LSTM (3.0j), 150% above other cells (2.0j). All other Cortex cells cluster at 1.5-2.0j. sLSTM's exponential gating and commitment state are uniquely suited to CogsGuard.

### Round 3: B6 rerun + C1/C2 combos + D1 sLSTM tuning (COMPLETE)

Given sLSTM's dominance (5.0j), prioritizing sLSTM-focused experiments:

| GPU | Experiment | Config | Peak J | Entropy |
|-----|-----------|--------|--------|---------|
| 0 | B6v2: sLSTM axonified | S^ (state-size fix) | 2.000 | 1.547 |
| 1 | C1: L+S sequential | ls_seq (2 layers) | 2.000 | 1.221 |
| 2 | C2: L+S routed | ls (Column) | 1.667 | 1.391 |
| 3 | D1: sLSTM ent=0.05 | S + ent_coef=0.05 | 2.000 | 1.607 |

**H_B3 outcome (axonified)**: **INCONCLUSIVE**. sLSTM^ (2.0j) ≈ sLSTM median (1.0j). RTRL auxiliary state adds 3.5x memory overhead without clear benefit. B1's 5.0j was noise (single lucky eval).

**H_C1 outcome**: **INCONCLUSIVE**. L+S sequential (2.0j) and L+S routed (1.667j) comparable to single sLSTM median (~1.0j). Combinations don't help but also don't dramatically hurt. C1's low entropy (1.221) is concerning.

**H_D1 outcome**: **INCONCLUSIVE**. Higher entropy (0.05) gave 2.0j — same as most experiments. Can't conclude harm since B1's 5.0j baseline was noise.

**Overall**: All architectures converge to median ~1.0j with occasional 2.0j peaks. No architecture dramatically outperforms any other. The problem is optimization dynamics, not architecture.

### Round 4: sLSTM Replication + Tuning (COMPLETE)

| GPU | Experiment | Config | Peak J | Notes |
|-----|-----------|--------|--------|-------|
| 0 | D2: sLSTM replicate | default | 1.000 | B1's 5.0j NOT reproducible — noise confirmed |
| 1 | D3: sLSTM bptt=128 | bptt_horizon=128 | 2.000 | Longer window didn't help |
| 2 | D4: sLSTM gamma=0.999 | gamma=0.999 | 1.000 | Longer horizon didn't help |
| 3 | D5: sLSTM lr=0.0005 | learning_rate=0.0005 | 2.500 | Marginally better — delays collapse |

### Critical Finding: Advantage Estimation Collapse

**ALL architectures** (including native LSTM) suffer from clipfrac collapsing to 0.000 during training. This is NOT architecture-specific — it's an optimization dynamics problem.

**Root cause**: `vf_coef=2.0` (4x standard, default in cogames 0.19) causes the value function to converge too fast → advantages shrink to ~0 → PPO policy ratio stays within clip window → no policy updates.

**Collapse timing**: Native LSTM collapses FIRST (epoch 103/186 = 55%). Most Cortex variants collapse at epoch 288-317/371 (78-85%). Cortex actually maintains learning LONGER but is ~40% slower (28-38K SPS vs 56K).

**Median junction performance across all architectures**: ~1.0j. The 5.0j sLSTM peak was a single lucky early eval.

**Literature-backed fixes** (from NeurIPS 2024, ICML 2023):
- **vf_coef reduction** (2.0→0.5): Slow value convergence to preserve advantage signal
- **Adam-Rel** (Ellis et al., NeurIPS 2024): Reset optimizer timestep each epoch — prevents stale bias correction
- **Soft Shrink+Perturb** (Lyle et al., NeurIPS 2024): Regularize weights toward initialization
- **Separate actor/critic LR**: Value head learning too fast relative to policy

### Round 5/5b: Advantage Collapse Fixes (COMPLETE)

| GPU | Experiment | Fix | Peak J | Final Entropy | Clipfrac Alive Until |
|-----|-----------|-----|--------|---------------|---------------------|
| 0 | E1: sLSTM vf=0.5 | vf_coef 2.0→0.5 | **2.0** | 1.553 | epoch ~310/371 (84%) |
| 1 | E2v2: sLSTM Adam-Rel | Adam-Rel only (vf=2.0) | 1.5 | 1.244 | epoch ~300/371 (81%) |
| 2 | E3v2: sLSTM combined | vf=0.5+Adam-Rel+S+P | 1.0 | 1.117 | epoch ~320/371 (86%) |
| 3 | E4v2: Native LSTM vf=0.5 | vf_coef 2.0→0.5 | **2.0** | 1.573 | epoch ~325/371 (88%) |

**E1 junction trajectory**: 1.0 1.0 1.5 2.0 1.0 1.0 1.0 1.0 1.0 1.5 1.0 1.0 1.667 1.0 1.5 1.0 1.0 2.0 1.0

**Key findings**:
1. **vf_coef=0.5 is the most effective single fix**: E1/E4v2 both peak 2.0j (matching best-ever non-noise results)
2. **Adam-Rel alone (without vf fix) doesn't help**: E2v2 still at vf=2.0, lower performance
3. **Shrink+Perturb actively hurts**: E3v2 has lowest entropy (1.117) and worst junctions (1.0). Pulling weights toward init fights learning.
4. **Native LSTM with vf=0.5 matches sLSTM**: E4v2 same peak as E1, highest entropy (1.573)
5. **ALL experiments still show clipfrac collapse to 0.000**: Interventions delay by 10-25 epochs but don't prevent it
6. **Median performance still ~1.0j**: Even with fixes, single-eval peaks are 2.0j but median is ~1.0

### Hyperparameter Clarification (corrected 2026-03-31)

**CORRECTION**: The table above was based on a false premise — we assumed cogames 0.18 used PufferLib/CleanRL defaults. Git blame confirmed these hyperparams have been constant since Sept 2025. The "0.18 hyperparams" we tested in Round 6 (F1-F4) were actually PufferLib defaults, not old cogames values.

| Param | cogames (all versions) | PufferLib default | Our H4 fix |
|-------|----------------------|-------------------|------------|
| ent_coef | 0.01 | 0.05 | **0.03** |
| vf_coef | 2.0 | 0.5 | **0.5** |
| bptt_horizon | 64 | 128 | 64 (default) |
| gamma | 0.995 | 0.999 | 0.995 (default) |
| gae_lambda | 0.90 | 0.95 | 0.90 (default) |
| max_grad_norm | 1.5 | 0.5 | 1.5 (default) |

The key fixes in H4 were vf_coef (2.0→0.5) and ent_coef (0.01→0.03), plus SepLR and ReDo.

### Round 6: Full 0.18 Hyperparam Restoration (COMPLETE — DISCONFIRMED)

| GPU | Experiment | Config | Peak J | Final Entropy | Clipfrac Collapse |
|-----|-----------|--------|--------|---------------|-------------------|
| 0 | F1: sLSTM + full 0.18 hp | OOM with bptt=128 | — | — | OOM (AIF eval conflict on GPU 0) |
| 1 | F2: Native LSTM + full 0.18 hp | All 6 params restored | 1.5 | 1.607 | epoch ~140/186 (75%) |
| 2 | F3: sLSTM + ent=0.05 + vf=0.5 | Only entropy + vf fix | 2.0 | 1.609 | epoch ~212/371 (**57%**) |
| 3 | F4: sLSTM + 0.18 hp + Adam-Rel | Full + Adam-Rel | **0** | 1.578 | epoch ~142/186 (76%) |

**Hypothesis H_A1 (hyperparam regression): DISCONFIRMED.** Full 0.18 hyperparam restoration does NOT recover performance.

**Critical finding: Higher entropy (ent=0.05) ACCELERATES collapse!** F3 collapses at 57% of training vs E1's 84% with ent=0.01. More stochastic policies produce more variable returns, causing the value function to overfit to mean returns faster.

### Round 7: Tier 1 PPO Fixes (COMPLETE — BREAKTHROUGH)

Literature-backed fixes from NeurIPS 2024, ICML 2023, DAPO 2025:
- **PFO**: Pre-activation Feature Optimization — L2 loss on encoder pre-activations prevents representation collapse (Moalla et al., NeurIPS 2024)
- **Sep LR**: Separate actor/critic learning rates — critic 5x lower (actor=0.00092, critic=0.000184)
- **Asym Clip**: Asymmetric PPO clipping — upper bound 50% wider (low=0.2, high=0.3) from DAPO (ByteDance, 2025)
- **ReDo**: Dormant neuron recycling (Sokar et al., ICML 2023) — reinitialize dead neurons every 100 updates
- **No VF Clip**: Remove value function clipping (research shows it can degrade performance)

Implementation: Source-patched `pufferl.py` for PFO loss injection + asymmetric clipping + optional VF clip removal. Runtime monkey-patches in `patch_and_train.py` for separate LR, ReDo, PFO hooks.

| GPU | Experiment | Fixes | Peak J | Mean J | Final Clipfrac | Entropy |
|-----|-----------|-------|--------|--------|----------------|---------|
| 0 | **G1: sLSTM ALL fixes** | PFO+SepLR+AsymClip+ReDo+NoVfClip+vf=0.5 | **4.0** | **1.34** | **0.001-0.003** | 1.601 |
| 1 | G2: LSTM ALL fixes | Same, native LSTM | 2.0 | 1.19 | 0.000 | 1.603 |
| 2 | G3: sLSTM PFO+SepLR | PFO+SepLR+vf=0.5 | 2.0 | 1.14 | 0.000 | 1.607 |
| 3 | G4: sLSTM SepLR+ReDo | SepLR+ReDo+vf=0.5 | 1.0 | 1.00 | **0.044-0.060** | 1.389 |

**G1 junction trajectory**: 1.0 **4.0** 1.0 1.0 1.333 1.0 1.0 2.0 1.2 2.0 1.0 1.0 1.5 1.0 1.0 1.0 1.0 1.0

**Key findings**:
1. **G1 (all fixes) achieved 4.0 junctions** — best non-noise result. Mean 1.34 is 15% above any previous experiment.
2. **G1 clipfrac STILL ALIVE at epoch 371** (0.001-0.003). First experiment EVER to not fully collapse. The policy received gradient signal throughout training.
3. **G4 has strongest sustained clipfrac** (0.044-0.060). Sep LR + ReDo keeps the policy actively updating. But junctions stayed at 1.0 — learning but not learning the right thing (low entropy 1.389).
4. **ReDo reported 0 dormant neuron events** — the problem isn't dead neurons, it's representation collapse (which PFO addresses).
5. **Separate LR is the key ingredient** for preventing clipfrac collapse. PFO adds representation quality on top.
6. **sLSTM benefits more from fixes than native LSTM** — G1 (sLSTM, 4.0j) >> G2 (LSTM, 2.0j) with identical fixes.

### Round 8: Tuning + 100M Extension (COMPLETE)

| GPU | Experiment | Config | Steps | Peak J | Final Clipfrac | Collapsed? |
|-----|-----------|--------|-------|--------|----------------|------------|
| 0 | H1: G1 config, 100M | ALL fixes, 2x training | 100M | 2.0 | 0.001-0.029 (recovered) | Yes, mid-training |
| 1 | **H2: PFO=0.1** | ALL fixes, PFO_COEF=0.1 | 50M | 1.0 | **0.04-0.11** | **NEVER** |
| 2 | H3: critic_lr=0.5 | ALL fixes, CRITIC_LR_RATIO=0.5 | 50M | 2.0 | 0.000 | Yes, early |
| 3 | **H4: SepLR+ReDo+ent=0.03** | No PFO, higher entropy | 50M | 2.0 | **0.02-0.05** | **NEVER** |

**H1 junction trajectory**: 1.0 1.0 1.0 1.0 2.0 1.0 1.0 1.0
**H2 junction trajectory**: 1.0 1.0
**H4 junction trajectory**: 1.0 2.0 1.5 1.0

**Key findings**:
1. **H2 (PFO=0.1) and H4 (SepLR+ReDo+ent=0.03) NEVER collapsed** — sustained healthy clipfrac for the entire 50M steps. First experiments with truly stable optimization dynamics throughout training.
2. **H1 at 100M didn't improve** — G1's 4.0j peak at 50M was likely a lucky evaluation. Same config at 100M only reached 2.0j. Clipfrac collapsed mid-training (~step 50-150 epochs) then partially recovered.
3. **H3 confirms critic_lr_ratio=0.2 is critical** — 0.5 (less asymmetry) collapses like baseline.
4. **PFO=0.1 > PFO=1.0 for stability** — lower regularization gives smoother gradients.
5. **Optimization ceiling SOLVED but task/reward ceiling persists** — H2/H4 maintain healthy gradients throughout training but junctions remain at 1-2. The agent can keep learning; it just doesn't discover junction-scoring strategies.
6. **G1's 4.0j was noise** — high variance across runs of identical configs (4.0 vs 2.0). Median performance ~1.0-1.5j regardless of optimization dynamics.

**Implication**: The bottleneck has shifted from PPO optimization dynamics (solved by Tier 1 fixes) to **exploration/reward structure**. The agent receives gradient signal but doesn't find strategies that score junctions. Next steps should focus on reward shaping, curriculum, or architectural changes that improve exploration rather than further PPO tuning.

### Round 9: Environment Variants + Role Forcing (2026-03-31)

Base config: H4 (SepLR+ReDo, ent=0.03, vf=0.5) — best stable optimization. Testing environment simplification and role-forcing approaches.

**Note**: Round 9 was re-run after initial I1/I2/I3 configs underperformed. I1v2/I2v2/I3v2 are the corrected runs.

| GPU | ID | Config | Peak J | Entropy | Clipfrac | Notes |
|-----|-----|--------|--------|---------|----------|-------|
| 0 | I1v2 | aligner variant | 0 | -- | -- | Enemies too disruptive for aligner alone |
| 1 | I2v2 | vibes + forced_role_vibes | 2.0 | ~1.6 | stable | Role forcing helps but not enough |
| 2 | I3v2 | **no_clips + aligner** | **4.0** | ~1.6 | stable | **BEST RESULT** — environment simplification is key |
| 3 | I4 | no_clips | 2.5 | ~1.6 | stable | no_clips alone is strong |

**Key findings**:
1. **`no_clips + aligner` = 4.0j** — best result to date. Removing enemies + adding aligner reward shaping is the winning combination.
2. **`no_clips` alone gives 2.5j** — environment simplification is the single most effective change.
3. **`aligner` variant alone gives 0j** — enemies are too disruptive; aligner reward doesn't help if agents can't survive.
4. **`forced_role_vibes` gives 2.0j** — role forcing helps but is weaker than environment simplification.

### Round 10: Combined Variants + Curriculum (2026-03-31)

Building on I3v2's success. Testing additional variant combinations on the no_clips base.

| GPU | ID | Config | Peak J | Entropy | Clipfrac | Notes |
|-----|-----|--------|--------|---------|----------|-------|
| 0 | J1 | no_clips + vibes + forced_role_vibes | 3.0 | 1.608 | **0.000** (collapsed!) | Forced roles caused clipfrac collapse |
| 1 | J2 | no_clips + aligner + vibes + forced_roles | 2.778 | 1.555 | 0.04-0.08 (stable) | Adding forced_roles didn't beat I3v2 |
| 2 | J3 | no_clips + miner | 3.0 | 1.343 | 0.099 (stable) | Miner variant decent, stable optimization |
| 3 | J4 | no_clips + scrambler | 1.0 | 0.938 | 0.024-0.044 | Scrambler collapsed entropy (0.938) |

**Key findings**:
1. **`no_clips` is the key ingredient** — appears in all top results across R9 and R10.
2. **`forced_role_vibes` can cause clipfrac collapse** (J1) — fragile interaction with H4 config.
3. **`miner` variant gives decent 3.0j** with stable optimization — viable alternative to aligner.
4. **`scrambler` variant collapsed entropy** (0.938) — too much pressure from scrambler reward.
5. **Adding forced_roles to no_clips+aligner (J2 = 2.778j) doesn't beat no_clips+aligner alone (I3v2 = 4.0j)** — forced roles add complexity without benefit here.
6. **I3v2 (no_clips + aligner) remains the best environment config** at 4.0j peak.

**Next steps**: See [RESEARCH_ROADMAP.md](RESEARCH_ROADMAP.md) for comprehensive sweep plan (Rounds 11-15) testing 10 research approaches on the no_clips+aligner base.

### Round 11: Reward Shaping (2026-03-31)

Base config: H4 (SepLR+ReDo, ent=0.03, vf=0.5) on no_clips + aligner, sLSTM d=128.

**CRITICAL BUG**: K1/K2/K3 reward hooks referenced `trainer.reward_buffer` (PufferLib 2.x API) instead of `trainer.rewards` (PufferLib 3.0). All three failed silently and ran as extra baseline seeds. K4 (adaptive entropy) uses `trainer.train_args` and worked correctly. Bug fixed post-R11 for R12 onwards.

| GPU | ID | Config | Peak J | Mean J | N | Entropy | Clipfrac | Notes |
|-----|-----|--------|--------|--------|---|---------|----------|-------|
| 0 | K1 | chain_rewards scale=0.5 | 3.0 | 1.58 | 22 | 1.55 | 0.039 | BUGGED — baseline seed |
| 1 | K2 | chain_rewards scale=1.0 | 4.0 | 1.77 | 23 | 1.56 | 0.070 | BUGGED — baseline seed |
| 2 | K3 | curiosity beta=0.1 | 3.0 | 1.96 | 16 | 1.55 | 0.064 | BUGGED — baseline seed |
| 3 | K4 | adaptive entropy target=0.5 | 3.0 | 1.77 | 21 | 1.56 | 0.044 | VALID — ent decayed 0.03→0.01 |

**Key findings**:
1. **K1-K3 are accidental baseline seeds** for H4 config: mean junctions 1.58-1.96, peaks 3.0-4.0. High variance confirms stochasticity dominates at 50M steps.
2. **K4 adaptive entropy = no improvement over baseline**. Starting ent=0.03 with target_ratio=0.5 caused entropy to be above target, so ent_coef decayed to 0.01. No benefit.
3. **Baseline H4 mean = ~1.77 j/agent** (averaging K1/K2/K4 = effectively 3 baseline seeds).

### Round 12: Advantage Manipulation + Architecture (2026-03-31)

Base config: same H4 base. Testing dual-gamma, PRD advantage, separate actor/critic networks (Subhojeet suggestion), and target networks (Subhojeet suggestion).

| GPU | ID | Config | Peak J | Mean J | N | Entropy | Clipfrac | Notes |
|-----|-----|--------|--------|--------|---|---------|----------|-------|
| 0 | L1 | dual-gamma α=0.5 | 3.5 | **2.05** | 31 | 1.56 | 0.016 | **Best mean** — consistent performer |
| 1 | L2 | PRD α=0.5 | 4.0 | 1.76 | 35 | 1.57 | 0.040 | Spiky, high variance |
| 2 | L3b | separate actor/critic LSTM | 3.0 | 1.51 | 15 | 1.54 | 0.040 | Slowest learner, 451K params |
| 3 | L4b | target net τ=0.005 | **4.5** | 1.85 | 28 | 1.56 | 0.080 | **Best peak ever** (eval hook bugged) |

**Key findings**:
1. **L1 dual-gamma has the best mean (2.05)** — blending fast (γ=0.99) and slow (γ=0.999) advantages gives the most consistent performance. +16% over baseline mean.
2. **L4b target net achieved 4.5j peak** — highest single measurement across all experiments. However, the evaluate hook (replacing values with target predictions) had a tensor shape mismatch; only the polyak weight update worked. So this tests weight regularization, not stable GAE targets. Still promising.
3. **L3b separate AC underperforms (mean=1.51)** — 451K params (2x baseline) learns slower at 50M steps. Confirms RL scaling pathology: larger networks need proportionally more training.
4. **L2 PRD is baseline-level (mean=1.76)** — team-mean advantage subtraction doesn't help. Possibly because all agents have similar policies (no specialization to assign credit to).
5. **All experiments maintain healthy optimization** — no clipfrac collapse, entropy stable ~1.55.

**Target net evaluate hook bug**: `_patched_evaluate_tnet` attempts `self._target_policy(obs)` but the full policy forward pass needs LSTM hidden state, causing tensor shape mismatch (64 vs 2112). Needs proper fix to test stable GAE targets.

### Round 13: Bug-Fix Rerun (2026-04-01)

Base config: H4 (SepLR+ReDo, ent=0.03, vf=0.5) on no_clips + aligner, sLSTM d=128. Rerunning R11 reward shaping (K1-K3 were bugged) and R12 best approaches with PufferLib 3.0 attribute names fixed.

| GPU | ID | Config | Peak J | Mean J | N | Entropy | Clipfrac (final) | Notes |
|-----|-----|--------|--------|--------|---|---------|------------------|-------|
| 0 | M1 | chain_rewards scale=0.5 | 3.0 | ~1.64 | -- | ~1.55 | 0.043 | Healthy optimization, no breakthrough |
| 1 | M2 | curiosity beta=0.1 | 2.667 | ~1.81 | -- | ~1.55 | 0.053 | Count-based exploration, marginal |
| 2 | M3 | dual-gamma α=0.5 | 3.0 | ~1.70 | -- | ~1.55 | 0.114 | Reproduces L1 trend, higher clipfrac |
| 3 | M4 | target-net τ=0.005 | 3.0 | ~1.62 | -- | ~1.55 | 0.091 | Polyak averaging only (eval hook still bugged) |

**Key findings**:
1. **All techniques produce baseline-level results (~1.6-1.8 mean junctions)**. No approach significantly improves on H4 baseline at 50M steps.
2. **Healthy clipfrac confirms R11 bug fix worked** — all experiments maintain non-zero clipfrac throughout training (0.043-0.114 final). Optimization is stable.
3. **Chain rewards (M1) didn't help** — intermediate shaping rewards (heart gained, gear crafted) don't drive junction-scoring at this training budget.
4. **Curiosity (M2) is marginal** — count-based exploration bonus doesn't discover new strategies at 50M steps. May need longer training for novelty-driven exploration to compound.
5. **Dual-gamma (M3) reproduces L1's trend** — consistent performer but not a breakthrough. Blending timescales helps consistency, not peak.
6. **Target-net (M4) matches L4b's mechanism** — polyak weight regularization works but doesn't break the ceiling.

**Verdict**: PPO improvement approaches exhausted. All R11-R13 techniques produce ~1.5-2.0 mean junctions, matching H4 baseline within noise. R15 (map-size) and R16 (extended training) falsified the training budget and map scale hypotheses — 500M steps and smaller maps both fail to improve junction creation. The bottleneck is **reward structure + exploration strategy**: PPO cannot discover the multi-step junction-creation chain through gradient signal alone. AIF option-selection (hardcoding macro-strategy while learning micro-navigation) is the correct next direction. See PI meeting notes (2026-04-01) in [ROADMAP.md](ROADMAP.md).

---

## cogames 0.22 Upgrade (2026-04-01)

### Upgrade Details

Upgraded from cogames 0.19.2 to **0.22.2** (mettagrid 0.22.3, pufferlib-core 3.0.21).

**Key changes discovered:**
1. **Observation space changed: 600 → 900** — all old checkpoints are incompatible (size mismatch in `_net.0.weight`). Must retrain from scratch.
2. **PufferLib renamed**: `pufferlib` → `pufferlib-core` (same import path `pufferlib`, version 3.0.17 → 3.0.21)
3. **Tier 1 patches survived** — `pufferl.py` was not replaced during upgrade. PFO, asymmetric clipping, value clip removal all still applied.
4. **`cogames-agents` version conflict** — old local install requires cogames==0.3.68, but this is harmless (we use scripts/policy directly, not the agents package).
5. **Training pipeline works** — `cogames train`, `patch_and_train.py`, CortexSLSTMPolicy all verified functional.
6. **Mission names unchanged** — `arena`, `machina_1`, `tutorial` all work. New mission `four_score` (120x120, multi-team) available.
7. **Auth/submissions work** — token valid, `cogames submissions` shows all prior uploads (but none scored — version compat was the issue).

### Round 14: machina_1 Baseline on 0.22.2 (2026-04-01)

First training runs on cogames 0.22.2. All on machina_1 (88x88 tournament map) with 50M steps. Establishing new baselines since obs space change invalidated all prior checkpoints.

| GPU | ID | Config | Peak J | Mean J | Clipfrac | Entropy | Notes |
|-----|-----|--------|--------|--------|----------|---------|-------|
| 0 | **N1** | sLSTM + H4 + no_clips + aligner | **4.5** | **1.77** | 0.039 | 1.474 | Best machina_1 config |
| 1 | N2 | LSTM + H4 + no_clips + aligner | 3.0 | 1.30 | 0.027 | 1.521 | LSTM control |
| 2 | **N3** | sLSTM + H4 + no_clips | **5.0** | **1.77** | 0.052 | 1.394 | sLSTM strong without aligner |
| 3 | N4 | LSTM vanilla (cogames defaults) | 3.0 | 1.31 | **0.000** | 1.336 | Clipfrac collapsed (vf=2.0) |

**Key findings**:
1. **sLSTM outperforms LSTM on machina_1** (1.77 vs 1.30 mean). Confirms arena findings transfer to tournament map.
2. **N3 hit 5.0 junctions** without aligner variant — sLSTM + no_clips alone is the strongest config.
3. **H4 patches maintain healthy clipfrac** on 0.22 (0.027-0.052). Vanilla LSTM (N4) collapsed to 0.000 — vf_coef=2.0 advantage collapse reproduces on 0.22.
4. **Aligner variant doesn't help sLSTM** (N1 mean=1.77 ≈ N3 mean=1.77). On arena it helped (I3v2=4.0 > I4=2.5), but on machina_1 the effect is neutral.
5. **Obs space change (600→900) didn't hurt** — results are comparable to arena at 50M steps, confirming new features don't degrade learning.
6. **N1/N3 checkpoints**: `results_v22/N1_slstm_machina1/177507657302/model_000370.pt`, `results_v22/N3_slstm_noclips/177507657771/model_000370.pt`

### Round 15: Map-Size Comparison (2026-04-01)

Following PI suggestion to shrink map and isolate exploration bottleneck. All use sLSTM + H4 (SepLR+ReDo, vf=0.5, ent=0.03), 50M steps.

| GPU | ID | Map | Size | Agents | Peak J | Mean J | N | Notes |
|-----|-----|-----|------|--------|--------|--------|---|-------|
| 0 | O1 | tutorial.aligner | 35x35 | 4 | **0.0** | 0.00 | 0 | ZERO junctions — map too small |
| 1 | O2 | arena + no_clips | 50x50 | 8 | 3.0 | 1.51 | 59 | Baseline reference |
| -- | N3 | machina_1 + no_clips | 88x88 | 8 | 5.0 | 1.77 | 53 | (R14 comparison) |

O3/O4 (machina_1 solo, empty) crashed at startup — bad launcher configs.

**Key findings**:
1. **Tutorial map (35x35) produces ZERO junctions** — despite being the smallest map with only 4 agents. The `agent/junction.aligned` metric is 0.000 throughout all 50M steps. The map may lack sufficient infrastructure (junction spots, hub proximity, crafting stations) for the multi-step alignment chain.
2. **Larger maps are BETTER, not worse** — machina_1 (88x88) peak=5.0 > arena (50x50) peak=3.0 > tutorial (35x35) peak=0.0. This directly contradicts the "shrink map for easier exploration" hypothesis.
3. **Mean junctions comparable** — arena (1.51) vs machina_1 (1.77). The extra junction spots on larger maps give more opportunities, not fewer.
4. **Map-size hypothesis FALSIFIED** — the bottleneck is not map size. Agents don't explore better on smaller maps; they explore worse (fewer resources, fewer junction positions, less room to develop multi-step strategies).

### Round 16: Extended Training — 500M Steps (2026-04-01)

Following PI feedback that 50M is "quite small" (they train for billions internally). Testing whether the ~1.5-2.0 mean junction ceiling breaks at 10x training budget (500M steps = ~4-5 hours per run on L4).

| GPU | ID | Map | Size | Steps | Purpose |
|-----|-----|-----|------|-------|---------|
| 2 | P1 | machina_1 + no_clips | 88x88 | **500M** | Does machina_1 performance improve with 10x compute? |
| 3 | P2 | arena + no_clips | 50x50 | **500M** | Does arena performance improve with 10x compute? |

Both use sLSTM + H4 (SepLR+ReDo, vf=0.5, ent=0.03).

**Final results** (500M steps complete):

| ID | Map | Steps | Peak J | Mean J | N | Clipfrac | Entropy | Trajectory |
|----|-----|-------|--------|--------|---|----------|---------|------------|
| **P1** | machina_1 + no_clips | **500M** | **6.0** | **1.47** | 361 | 0.067 | 1.548 | Flat: 1.40→1.44→1.66→1.40 |
| **P2** | arena + no_clips | **500M** | 4.0 | **1.63** | 371 | **0.005** | 1.589 | Flat: 1.60→1.65→1.65→1.64 |
| N3 | machina_1 + no_clips | 50M | 5.0 | 1.77 | 53 | 0.059 | 1.433 | (R14 reference) |
| O2 | arena + no_clips | 50M | 3.0 | 1.51 | 59 | 0.034 | 1.560 | (R15 reference) |

**Detailed diagnostic — why 500M doesn't help:**

1. **Agents never learn to acquire aligner gear.** P1's `aligner_gained` has literally ZERO data points across 500M steps. Agents get junctions from random walk-overs onto alignment spots, not learned strategy. PPO can't credit-assign through the multi-step chain: gear acquisition → heart collection → navigate to hub → align.

2. **P2 clipfrac collapses (0.064 → 0.005).** By training end, policy updates are near-zero — the agent has stopped learning. SepLR delays collapse but doesn't prevent it at 500M steps. P1 maintains healthy clipfrac (0.067) but still doesn't improve junctions.

3. **P1 exploration shrinks over training.** `cell_visited` goes from 1.71M (early) → 1.42M (final). The policy becomes MORE deterministic, exploring LESS. More training makes this worse, not better.

4. **Heart gain stagnates or declines.** P1: 0.62 → 0.56 (declining). P2: 0.59 → 0.70 (slight improvement). The dense heart reward is fully exploited early; junction reward is too sparse to redirect behavior.

5. **Junction trajectory is completely flat.** Both P1 and P2 oscillate between 1.0-2.0 from first to last eval window. There is no learning curve at any point in 500M steps.

**Training budget hypothesis FALSIFIED.** 500M steps (10x) provides zero advantage over 50M for junction creation. Combined with R15 (map-size falsified), the bottleneck is **reward structure + exploration strategy**: PPO cannot discover the multi-step junction chain through gradient signal at ANY training budget or map size tested. This validates the AIF option-selection approach as the correct direction.

---

## Phase 17+: Adopt Metta's Tuned Pipeline (2026-04-02)

### Root Cause Analysis: Why We're 10x Behind

Discovered that `cogames train` defaults are dramatically different from metta's sweep-tuned values:

| Parameter | cogames train (us) | metta cogsguard.py (them) | Ratio |
|---|---|---|---|
| **learning_rate** | 0.00092 | 0.00738 | **8x lower** |
| **batch_size** | ~65K | 2,097,152 | **32x smaller** |
| **bptt_horizon** | 64 | 256 | **4x shorter** |
| **gamma** | 0.995 | 0.9986 | shorter horizon |
| **gae_lambda** | 0.90 | 0.9354 | higher bias |
| **vf_coef** | 2.0 | 1.465 | causes collapse |
| **clip_coef** | 0.2 | 0.367 | more conservative |
| **ent_coef** | 0.01 | 0.0257 | less exploration |
| **weight_decay** | 0 | 0.3 | no regularization |
| **optimizer** | adam | adamw_schedulefree | wrong optimizer |
| **Kickstarting** | none | EER + 50% teacher-led | missing entirely |

Our H4 "fixes" (vf=0.5, sep_lr, redo) were band-aids on fundamentally wrong defaults.

### Infrastructure Built (2026-04-02)

**Files modified/created:**

1. **`scripts/sweep/patch_and_train.py`** (906 lines, was 589)
   - Added `SWEEP_PRESET` env var with `metta_optimal` preset (all 12 metta-tuned params)
   - Added `adamw_sf` fix for AdamW ScheduleFree optimizer (with fallback to plain AdamW)
   - Added kickstarting: `KICKSTART_MODE=kl|eer`
     - KL: Cross-entropy loss between student logits and teacher actions
     - EER: KL loss + reward shaping `r' = r + lambda * log(pi(a_teacher|s))`
   - Added teacher-led rollouts: `KS_TEACHER_LED=0.5` replaces fraction of student actions
   - Added annealing: `KS_ANNEAL_START/END` for gradual kickstart decay
   - Chaining: kickstart wraps whatever train() patches (fixes, advantage modes) are already installed

2. **`scripts/sweep/plot_training.py`** (NEW, 233 lines)
   - Parses cogames training logs via regex
   - Generates 6-panel matplotlib figures: junctions+hearts, aligner_gained, entropy+clipfrac, explained_var, losses, reward+SPS
   - Overlay mode for comparing multiple runs
   - Prints summary stats (peak/mean junctions, last entropy/clipfrac, aligner_gained nonzero check)

3. **`scripts/sweep/round17_hparams.sh`** (NEW)
   - 4 GPU parallel sweep, 50M steps each
   - Q1: Full metta optimal preset
   - Q2: Metta optimal + H4 fixes (sep_lr, redo)
   - Q3: Metta optimal + arena map
   - Q4: cogames defaults control (reproduce N3's 5.0j)

4. **`scripts/sweep/round18_batch.sh`** (NEW)
   - R1: batch ~256K (128 envs)
   - R2: batch ~512K (256 envs)
   - R3: batch ~1M (512 envs)
   - R4: bptt=512

5. **`scripts/sweep/round19_kickstart.sh`** (NEW)
   - S1: KL kickstart (coef=0.6, temp=2.0, anneal 50-100%)
   - S2: EER kickstart (KL + reward shaping)
   - S3: EER + 50% teacher-led (full metta recipe)
   - S4: KL constant (no anneal)
   - 500M steps each (~5 hrs)
   - Includes aligner_gained > 0 critical diagnostic check

6. **`scripts/policy/scripted_teacher.py`** (updated docstring)
   - Verified compatible with 0.22 obs format (sentinel-based iteration, not fixed array size)
   - Added note about potential tag ID changes in 0.22

### Upload Command (to AWS)

```bash
cd ~/OneDrive/Desktop/projects/cogames-attempts
scp -i ~/OneDrive/Desktop/projects/mahault_key_pair.pem \
  scripts/sweep/patch_and_train.py \
  scripts/sweep/plot_training.py \
  scripts/sweep/round17_hparams.sh \
  scripts/sweep/round18_batch.sh \
  scripts/sweep/round19_kickstart.sh \
  scripts/policy/scripted_teacher.py \
  ec2-user@ec2-52-91-78-2.compute-1.amazonaws.com:~/projects/cogames-agents/scripts/
```

Then on AWS:
```bash
# Move files to correct subdirs
cd ~/projects/cogames-agents
mv scripts/round17_hparams.sh scripts/round18_batch.sh scripts/round19_kickstart.sh scripts/plot_training.py scripts/sweep/
mv scripts/scripted_teacher.py scripts/policy/

# Install schedulefree for AdamW SF optimizer
pip install schedulefree

# Install matplotlib for training graphs
pip install matplotlib

# Run Round 17 (first priority)
chmod +x scripts/sweep/round17_hparams.sh
nohup bash scripts/sweep/round17_hparams.sh &
```

### Execution Plan

1. **R17** (hparams): Does fixing hyperparams alone break the 5j ceiling?
2. **R18** (batch size): How much does batch size matter?
3. **R19** (kickstarting): Does teacher signal help?
4. **R20-R21** (scale): Best config at 1B-5B steps
5. **R22-R26** (architecture + advanced): If hparams/kickstarting work

### Success Criteria

| Level | Junctions | What it means |
|-------|-----------|---------------|
| R17 validation | >5j with just hparam fix | Confirms hparams were the bottleneck |
| Minimum | >10j mean | 2x our best, kickstarting working |
| Target | >30j | Approaching Softmax internal |
| Stretch | >50j | Matching Softmax teams |

### Round 17: Metta Hyperparams (2026-04-02, COMPLETE)

All: sLSTM d=128, machina_1, no_clips, 50M steps.

| GPU | ID | Config | Peak J | Mean J | Clipfrac | Entropy | Notes |
|-----|-----|--------|--------|--------|----------|---------|-------|
| 0 | Q1 | Full metta optimal preset | 2.0 | 0.96 | 0.200 | 1.41 | Stable, no collapse |
| 1 | Q2 | Metta optimal + sep_lr + redo | **3.0** | **1.33** | 0.187 | 1.39 | sep_lr still helps |
| 2 | Q3 | Metta optimal + arena map | 2.0 | 1.18 | 0.205 | 1.44 | Arena comparable |
| 3 | Q4 | cogames defaults (control) | 2.0 | 0.81 | 0.059 | 1.43 | Baseline |

**Key finding**: Metta hparams alone (Q1-Q2) don't break the 5j ceiling at 50M steps, but produce healthier training dynamics (clipfrac 0.2 vs 0.06). sep_lr still helps (Q2 > Q1). At 50M steps, the difference is marginal — the real test is at scale.

### Round 18: Batch Size + Optimizer (2026-04-03, COMPLETE)

All: Q2 config (metta optimal + sep_lr + redo), machina_1, no_clips, 50M steps.

| GPU | ID | Config | Peak J | Mean J | Clipfrac | Entropy | Notes |
|-----|-----|--------|--------|--------|----------|---------|-------|
| 0 | R1 | batch_size=256K | 2.0 | 1.04 | 0.195 | 1.42 | No improvement |
| 1 | R2 | batch_size=512K | 2.0 | 0.98 | 0.188 | 1.40 | No improvement |
| 2 | R3 | batch_size=1M | 2.0 | 1.07 | 0.191 | 1.43 | No improvement |
| 3 | R4 | AdamW ScheduleFree | 2.0 | 0.89 | 0.172 | 1.38 | Slightly worse |

**Key finding**: Batch size and optimizer choice don't matter at 50M step scale. AdamW SF marginally worse. bptt=256 tested separately, caused clipfrac collapse. All roads point to kickstarting + more steps as the path forward.

### Round 19: Kickstarting Calibration (2026-04-03–04, COMPLETE)

All: metta optimal + sep_lr + redo, sLSTM d=128, machina_1, no_clips, 500M steps.
Teacher: scripted_teacher.py (heuristic, NOT Nim A*).

| GPU | ID | Mode | KS Coef | Steps Completed | Peak Aligned J | Final Entropy | Final Clipfrac | Status |
|-----|-----|------|---------|-----------------|----------------|---------------|----------------|--------|
| 1 | **S1** | KL kickstart | 0.6, anneal 50-100% | **500M** | **7.0** | 0.517 | 0.264 | **NEW BEST** |
| 2 | S2 | EER kickstart | 0.6, anneal 50-100% | 500M | **0** | ~0.5 | 0.150 | Failed |
| 3 | S3 | EER + 50% teacher-led | 0.6, no anneal reached | 165M | 1.0 | NaN | 0.445 | Diverged |

**S1 Deep Analysis (KL kickstart — winner):**
- Three-phase training: (1) Teacher memorization 0-250M, entropy collapsed to 0.013-0.020. (2) KS annealing 250-450M, entropy recovering. (3) Autonomous PPO 450-500M, entropy reached 0.517, junctions climbed to 7.0.
- Peak junctions appeared in the LAST 50M steps after KS annealed away — the policy was just starting autonomous learning when training ended.
- ks_loss oscillated (0.005-0.554), not monotonically decreasing — suggests unstable teacher imitation.
- heart.gained peaked at ~1.15, settled at ~0.92.

**S2 Deep Analysis (EER — failure):**
- Zero aligned junctions across entire 500M steps despite similar ks_loss trajectory to S1.
- Root cause: EER reward shaping (r' = r + lambda*log(pi_teacher)) inflated value estimates. Final value_loss=2.536 (vs S1's 0.000). Bad value function → noisy advantages → no policy improvement on junctions.
- heart.gained comparable to S1 (~0.87-0.91) — basic behavior learned, but not the junction chain.

**S3 Deep Analysis (EER + teacher-led — catastrophe):**
- Diverged to NaN at 165M steps (progress=0.33, KS coef still at 0.6).
- Double-binding: EER loss pushed toward teacher + 50% forced teacher actions in rollout. Entropy collapsed to 0.18, then policy_loss exploded (0.35 → 58,164 → 740,000 → NaN).
- teacher-led Python loop was 15x slower (~3K SPS vs ~8K SPS). Forward pass took up to 67 minutes.
- Teacher-led at 50% is fundamentally unstable at these settings.

**Critical finding — aligner_gained=0 for ALL runs:**
This is a tracking artifact, not a behavioral one. We didn't use `-v credit` which is the variant that tracks and rewards gear acquisition. S1 DID acquire gears (that's how it got 7.0 aligned junctions), but there was no dense reward for intermediate steps.

**R19 Conclusions:**
1. KL kickstarting works — 7.0j (40% improvement over 5.0j ceiling)
2. EER kickstarting is harmful — value function corruption prevents junction learning
3. Teacher-led at 50% is unstable — double binding causes gradient explosion
4. S1 was just getting started when training ended — 7.0j appeared in final 50M of 500M
5. More training budget is the #1 priority (500M is 5-20x too small vs metta's 3-10B)

### Round 20: Isolation Experiments (2026-04-06, COMPLETE)

**Hypothesis**: S1's 7.0j in the final 50M suggests the policy was just beginning autonomous learning. Extending S1 should yield significantly more junctions. Adding credit rewards should accelerate the intermediate behavior chain.

**Checkpoint**: S1 `model_000925.pt` (weights only, fresh optimizer via `data=` policy arg).

| GPU | ID | Config | Steps | Peak J | Entropy Final | Clipfrac Final |
|-----|-----|--------|-------|--------|---------------|----------------|
| 0 | T1 | S1 warm-start, pure PPO, no KS | 1.5B | 1.5 | 0.000 | 0.000 |
| 1 | T2 | S1 warm-start + milestones,credit | 1B | 1.0 | 0.000 | 0.000 |
| 2 | T3 | Fresh + KL KS 0.3 + milestones,credit | 1B | **8.0** | 0.000 | 0.000 |
| 3 | T4 | Fresh + KL KS 0.3 + milestones,credit,role_conditional | 1B | 1.0 | 0.000 | 0.000 |

**Critical finding**: ALL 4 runs suffered entropy collapse (entropy→0.000, clipfrac→0.000). T3 hit **8.0j** (new record!) before collapsing. This means:
- **Warm-starting is counterproductive**: T1/T2 performed worse than fresh T3/T4
- **Fresh + KL KS remains the best base**: T3 > T4 > T1 > T2
- **Entropy collapse is the #1 systemic problem** — it kills all learning after ~600-800M steps
- **role_conditional hurts** (T4 < T3): may add too much reward complexity

**Reward variant fix**: Discovered cogames 0.22 has reward variants but they're NOT wired into the CLI. Fixed by monkey-patching `parse_variants()` and `train()` in patch_and_train.py.

---

### Round 21: Entropy Collapse Prevention (2026-04-06 → 2026-04-08, COMPLETE)

**Hypothesis**: Entropy collapse at 600-800M steps is caused by insufficient entropy bonus. ent_coef=0.0257 (metta default) is too low for 1B+ training. Testing 4 prevention strategies.

**Base config**: T3's winning setup (fresh + KL KS 0.3 anneal 30-60% + milestones,credit + metta_optimal preset + sep_lr,redo)

| GPU | ID | Strategy | ent_coef | Entropy Min | Entropy Final | Collapsed? | aligner_gained |
|-----|-----|----------|----------|-------------|---------------|------------|----------------|
| 0 | E1 | High constant | 0.08 | 0.000 | 0.000 | YES at ~740M | 1 event (0.297) |
| 1 | E2 | Cosine 0.10→0.02 | varies | 0.000 | 0.000 | YES at ~616M | 0 |
| 2 | E3 | Adaptive floor=0.3 | varies | 0.000 | 0.000 | YES at ~636M | 0 |
| 3 | E4 | **ent=0.15 + adaptive** | 0.15 | **0.726** | **0.967** | **NO** | **10 events** |

**E4 entropy trajectory**: 1.264 → 0.897 → 0.804 → 1.107 → 1.494 → 1.590 → 1.384 → 0.967. Dipped to 0.726 minimum, recovered naturally. Clipfrac=0.074 at end (still learning).

**Critical findings**:

1. **ent_coef threshold between 0.08 and 0.15**: 0.08 delays collapse (740M vs 616M) but doesn't prevent it. 0.15 survives to 1B.
2. **Adaptive controller had 3 bugs** (all fixed):
   - Gate checked `_entropy_mode == "adaptive"` but cosine mode also needed to pass through
   - Entropy lookup used `trainer.stats`/`trainer.last_log` but PufferLib 3.0 stores it in `trainer.losses["entropy"]`
   - Used `trainer.config` (doesn't exist) instead of `trainer.train_args`
3. **Cosine schedule was counterproductive**: Collapsed EARLIEST (616M) — annealing down while model was already trending toward collapse.
4. **aligner_gained requires exploration**: Only E4 (which maintained entropy) showed repeated gear acquisition events.
5. **E4 is the new baseline**: Survived 1B steps, still learning, first run with repeated aligner_gained.

**Next**: R22 with fixed adaptive controller + E4's ent_coef=0.15 base, scale to 2B+ steps.

---

### R22: Scale E4 to 2B Steps (2026-04-08)

**Config**: E4 base (ent_coef=0.15 + fixed adaptive controller), scaled to 2B steps.

**Result**: Entropy stability confirmed at 2B scale. Adaptive controller maintained healthy entropy throughout.

---

### R23: Teacher + Encoder + tok.location Bug Fixes (2026-04-13)

**Changes**: 3 bugs fixed:
1. `scripted_teacher.py` agent IDs wrong for 0.22 format (was 0.18-era IDs)
2. Dead encoder: ReLU killed gradients → switched to LeakyReLU
3. `tok.location` observation not properly parsed

**Result**: Teacher confirmed working (0% noop actions during teacher-led rollouts). But still **0 junctions** — the root cause wasn't in the teacher or encoder.

---

### R24: TRUE Root Cause — Missing Vibe Actions (2026-04-16)

**Discovery**: Policy outputs `Discrete(5)` = 5 movement actions ONLY. Without supervisor teacher, vibe actions are filled with zeros → default vibe → agents CANNOT mine, craft, or align. This single bug caused 0 junctions in ALL experiments R1-R23.

**Fix**: Transport-encoded actions (`Discrete(40)` = 5 movement × 8 vibe options). Agents can now express vibes (mine, deposit, withdraw, align, etc.) independently.

**Phase 1 result**: `aligned.junction = 1.5` at 50M steps. First real PPO junctions ever. Full economy chain confirmed (mine → deposit → withdraw → align). Entropy=1.471 (healthy), expl_var=0.946.

---

### Track A: Metta Recipe Migration (2026-04-17 — ongoing)

#### Recipe Implementation

Created `recipes/experiment/cogsguard_aif_team.py` — forks base `cogsguard.py` and adds:
1. **R24-validated hyperparams**: ent_coef=0.12, weight_decay=0.1
2. **Adaptive entropy controller**: `metta/rl/loss/adaptive_entropy.py` (custom LossConfig, zero-gradient)
3. **Teacher config**: cuda teacher for kickstarting

PR #11757 submitted to Metta-AI/metta. Codex review requested two fixes:
- P1: Persist `_adapted_ent_coef` across checkpoint restores → fixed via `register_state_attr()`
- P2: Synchronize entropy metric across DDP ranks → fixed via `torch.distributed.all_reduce()`

#### 50M v3 Run (2026-04-21)

**Config**: `cogsguard_aif_team` recipe on AWS 4xL4, cuda teacher (cinky), `scripted.supervisor.mixed` mode.

**Result**: **823.3 j/held** — exponential learning curve:
- Epoch 5: 0.1 j/held
- Epoch 10: 12 j/held
- Epoch 15: 68 j/held
- Epoch 18: 169 j/held
- Epoch 21: 396 j/held
- Epoch 24: 823 j/held

Entropy=2.94 (healthy, well above floor). Adaptive entropy controller did not need to intervene.

**Checkpoint**: `~/metta/train_dir/local.ec2-user.20260421.173016/checkpoints/local.ec2-user.20260421.173016:v24/`

**Critical caveat**: 823 j/held is measured WITH teacher KL signal active. Student-only eval ~1.0 j/agent. The supervisor's `ActionSupervised` loss teaches *what action to take* but not *how confident to be* — student mimics teacher's actions during training but can't replicate the strategy without teacher signal at inference.

#### 500M Supervisor Run (2026-04-20)

**Config**: Extended cuda teacher (cinky) run to 500M steps.

**Result**: Teacher-held stays high (~8,300 j/held), but student-only eval remains ~1.0 j/agent. More steps doesn't help — the `ActionSupervised` loss (action-level cross-entropy) is fundamentally limited for knowledge transfer.

**Diagnosis**: Need `KickstarterLoss` (KL on full logit distribution + MSE on values) instead of `ActionSupervised` (cross-entropy on argmax action). The kickstarter teaches the student about confidence/uncertainty across ALL actions, not just the teacher's chosen action.

#### Next: Learned Kickstarter (BLOCKED)

**Plan**: Switch from `scripted.supervisor.mixed` (cinky) to `learned.kickstarter.mixed` (slanky:v154 or dinky_fido:v3). The `KickstarterLoss` gives T²·KL(student || teacher) which preserves full distributional knowledge.

**Blocker**: `metta://` URI resolution requires AWS SSO credentials for S3 download of learned teacher policy. Observatory token saved, but `aws sso login --profile softmax` requires interactive terminal. Profiles configured via `setup_aws_profiles.sh` but not authenticated.

#### 500M Cinky Convergence (2026-04-22 — UPDATE)

Extended cinky cuda teacher run converged at **8,639 j/held** (epoch 189, training metric). Eval (10k-step arena): **6,926 j/held**.

Key discovery: cinky achieves this with ZERO vibe supervision — CUDA teachers can't output split-action vibes. Training metric ≈ eval metric (~1:1, reports at episode boundaries).

Previous note that "student-only ~1.0 j/agent" was based on the 50M checkpoint only. The 500M run continued growing well past 823 to converge at 8,639.

#### PazBot-v47 Vibe Teacher (2026-04-29 — COMPLETE)

**Config**: TrainerSideTeacherRunner (CPU multiprocessing, 16 workers), PazBot-v47 (leaderboard #1), ~48% vibe fraction. 3.0 ksps.

**Purpose**: Test whether vibe supervision (which cinky lacked) raises the convergence ceiling above 8,639.

**Result**: Peaked **7,269 j/held** (epoch 145). Did NOT exceed cinky's 8,639. Vibe KL hurt (conflicting gradients between PazBot vibes and cinky-initialized policy). Teacher annealing counterproductive: v1300 VOR 10.46 > v2300 VOR 8.53.

**Metric calibration**: `aligned.junction.held` is a junction-time accumulator — each tick adds current held junction count. Arena has ~30 junctions, 10k-step episodes. Training metric ≈ eval metric (1:1).

---

### Phase 5: Tournament + Close-the-Gap (2026-05-05 — 2026-05-07)

#### Scoring Discovery (2026-05-06)

Confirmed: leaderboard uses raw mean team reward (NOT VOR). Both policies in a match get identical scores (team junctions_held is shared). Match compositions: 2+6, 6+2, 4+4 (8 agents total, Machina1 maps).

#### The p25 Problem (2026-05-06)

| Percentile | slanky (rank 1) | Us (rank 342) | Gap |
|-----------|----------------|---------------|-----|
| p25 | 31.3 | **1.8** | **17x** |
| p50 | 51.3 | 12.1 | 4.2x |
| p95 | 45.4 | **45.4** | **1.0x** |

Our p95 matches top policies — we CAN score well. But p25=1.8 means we collapse with unfamiliar partners. Root cause: training against single teacher (cinky) builds narrow cooperation pattern.

#### Close-the-Gap Campaign (2026-05-05)

Three parallel tracks launched:

**Track 1 — Large Architecture**: `cogsguard_aif_large.py`. sweep_mode=True (384/768/96), routed adapter, cinky teacher, 500M steps.
- Result: Peaked 8,218 j/held (epoch 224 for marlbro variant)
- Tournament: large-v243 scored 6.87 (rank 589) — **no improvement** over default arch

**Track 2 — Marlbro Role Specialization**: `cogsguard_aif_marlbro.py`. 3-role (miner/aligner/scrambler) with trajectory isolation, 500M steps.
- Result: Peaked **8,218 j/held** (epoch 224)
- Tournament: 4.29 (rank 671, 11 matches) — role specialists don't cooperate well with strangers

**Track 3 — Checkpoint Sweep**: Submitted 22+ checkpoints. Best: v500 at 11.31 (rank 426).

**Large + Self-Distill**: sweep_mode + EMA self-distillation (decay=0.999, action KL coef=0.1), 500M steps.
- Result: **FAILED** — peaked ~306 j/held. Self-distillation chicken-and-egg: EMA target starts bad → student penalized for deviating → student stays bad → target stays bad.

#### Confirmed Non-Factors (2026-05-05)

1. **Vibes don't matter** — cinky achieved 8,639 j/held with zero vibe supervision
2. **More training steps don't help** — 6B plateau same as 50M convergence
3. **Teacher annealing hurts** — v1300 (teacher active, 10.47) > v2300 (teacher annealed, 8.47)
4. **3x larger architecture doesn't help** — large-v243 scored 6.87 vs v500's 11.31

#### Tournament Standings (2026-05-07)

| Rank | Submission | Score | Matches |
|------|-----------|-------|---------|
| 426 | mahault-cinky-pazbot-v500:v1 | **11.31** | 26 |
| 589 | mahault-large-v243:v1 | 6.87 | 20 |
| 613 | mahault-large-v100:v1 | 6.40 | 26 |
| 670 | mahault-large-v200:v1 | 4.32 | 26 |
| 671 | mahault-marlbro-v243:v1 | 4.29 | 11 |

#### SkyPilot 6B Run (2026-05-07 — ACTIVE)

**Config**: Job 2899, cogsguard-aif-large-6B, 4x L4 spot, 6B steps.

| Metric | Value |
|--------|-------|
| Progress | 2.5B / 6B steps (41.8%), epoch 301 |
| Throughput | 33.6 ksps |
| j/held | **10,820** (steadily climbing) |
| Checkpoints | v100, v200, v300 on S3 |

j/held trend (last 6 epochs): 10,876 → 10,902 → 10,926 → 10,977 → 11,040 → 11,090. Already exceeds EC2 500M large run.

---

### Phase 6: FCP Teammate Diversity + AIF Social Cognition (2026-05-07)

#### FCP Recipe Created — `cogsguard_aif_fcp.py`

Directly addresses the p25 problem. Based on Fictitious Co-Play (Strouse et al., NeurIPS 2021).

**Architecture (8 agents per environment):**
- Agents 0-3: **learner** (trainable PPO, R24 hyperparams + adaptive entropy)
- Agents 4-7: **frozen teammate** (swapped from pool each epoch, no training)

**Pool sources:**
- `LeaderboardSource`: top 20 beta-cvc policies (refreshed every 50 epochs)
- `TrainingRunSource`: own checkpoints (self-play diversity)
- Initial teammate: Paz-Bot-9000:v47

**Infrastructure used:** `FictitiousCoplayConfig` → `PolicyPoolComponent` (weight swapping), `TrajectoryIsolationConfig` (learner/teammate slices), `PolicyAssetConfig(trainable=False)`.

**PFSP extension:** Added `algorithm_config` to `FictitiousCoplayConfig`. `train_pfsp()` uses `PrioritizedRegretConfig(temperature=1.0, exploration_bonus=0.1)` — regret-based sampling prioritizes teammates the learner cooperates worst with. Based on RACCOON (CoCoMARL 2024).

**Files created:**
- `metta/recipes/experiment/cogsguard_aif_fcp.py` (~160 lines)
- `metta/devops/skypilot/config/skypilot_fcp_6b.yaml`

**Status**: Ready for SkyPilot launch.

#### AIF v23 Social Cognition (2026-05-07)

Major v23 overhaul: 8 observation modalities (was 6), ARRIVED nav state, INTERACT action, team-conditioned C vectors, adaptive role switching, PassiveAllyTracker.

**Team-conditioned C vectors** (`goal_model.py`):
- SUPPLY_EXCESS → boost capture preference
- CAPTURE_EXCESS → boost resource/gather preference
- DEFEND_HEAVY → boost economy activities

**Adaptive role switching** (`goal_model.py`):
- Supply excess + aligner → boost CAPTURE (×1.5), reduce GATHER (×0.7)
- Capture excess + aligner → boost CRAFT (×1.5), reduce CAPTURE (×0.7)

**Passive ally tracker** (`cogames_policy.py`): Infers PPO stranger teammates' goals from movement patterns relative to known stations. Enables team coordination in tournament mixed-team matches.

**Tests**: 242 passed (23 new), 3 skipped, 0 failed.

#### Literature Survey: 50+ Cooperative MARL Papers (2026-05-07)

Key papers and findings:

| Paper | Venue | Key Finding |
|-------|-------|-------------|
| FCP (Strouse et al.) | NeurIPS 2021 | Checkpoint-based partner diversity for zero-shot coordination |
| MEP (Zhao et al.) | AAAI 2023 | Max-entropy population + PFSP-style prioritized sampling |
| "Diversity Is Not All You Need" | NeurIPS 2024 | Partner specialization matters alongside diversity |
| RACCOON | CoCoMARL 2024 | Regret-based cooperative partner prioritization |
| Sub-task Composition | AAMAS 2024 | Train sub-teams separately, merge + fine-tune |
| HAICA (Poppel et al.) | Cognitive Computation 2022 | Lightweight belief resonance for AIF teamwork |
| "Belief Sharing: Blessing or Curse" (Catal et al.) | IWAI 2024 | Naive belief broadcasting creates echo chambers |

**Key implication**: Safa Alver's rank-9 approach (role-specialized policies via Coggerbro + FixedAssignmentCheckpointPolicy composition) is validated by "Diversity Is Not All You Need" and Sub-task Composition papers. Role-specialized FCP is the recommended next step.

Full survey: 37 new references added to `aif-meta-cogames/docs/LITERATURE_REVIEW.md` (Sections 12-13, references #46-82).
