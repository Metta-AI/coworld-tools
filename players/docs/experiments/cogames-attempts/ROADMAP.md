# Softmax Contract Roadmap: Active Inference for CogsGuard

**Contract**: 80 hours (~10 hrs/week, 8 weeks)
**Meetings**: Tuesdays with Subhojeet (may adjust frequency)
**Objective**: Understand the Alignment League benchmark, identify bottlenecks, propose and prototype a research-driven approach

**Links**:
- Leaderboard: https://softmax.com/observatory/
- ALB landing: https://softmax.com/alignmentleague
- CoGames repo: https://github.com/Metta-AI/cogames
- Scripted agents: https://github.com/Metta-AI/cogames-agents

**Related docs**:
- [README.md](README.md) — Project overview, quick start, doc index
- [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md) — All training runs, sweep results, experimental findings
- [AIF_DESIGN.md](AIF_DESIGN.md) — Full AIF architecture: 288-state POMDP, VFE/EFE math, G-coupling, ToM, 5 approaches
- [LITERATURE.md](LITERATURE.md) — Papers on MARL methods and recurrent architectures for RL

**Archived docs** (historical, mostly superseded by above):
- [RESEARCH_ROADMAP.md](RESEARCH_ROADMAP.md) — 10 research approaches, Cortex exploration, sweep schedule (Rounds 11-15). Now superseded by this roadmap's Phase 4 section.
- [RESEARCH_PROPOSAL.md](RESEARCH_PROPOSAL.md) — Five-step research pipeline sent to PI (2026-03). AIF sections superseded by AIF_DESIGN.md.

---

## Current Status (2026-05-07)

**Phase 1** (env mastery): ✅ Complete
**Phase 2** (bottleneck analysis + training sweeps): ✅ Complete — 18 A3 sweeps, A1.5 role training, scout investigation, kickstarting (Path A + B)
**Phase 2b** (approach evaluation): ✅ Complete — decision matrix, PI meetings, AIF direction approved
**Phase 3** (metta pipeline adoption): ✅ Complete — R17-R22 (metta hparams, batch size, kickstarting, entropy control)
**Phase 4** (scale + architecture): ✅ Complete — R22 (2B steps), R23 (teacher/encoder/tok.location fixes), R24 (vibe actions — **validated: 1.5 aligned junctions**)
**Phase 4b** (deep metta repo analysis): ✅ Complete — Read entire loss system, policy system, training pipeline, all recipe variants from local clone
**Phase 4c** (Track A recipe + PR): ✅ Complete — `cogsguard_aif_team.py` recipe + `adaptive_entropy.py` loss. PR #11757 submitted.
**Phase 4d** (Scale training): ✅ Complete — cinky teacher converged at **8,639 j/held** (500M). PazBot teacher converged at **7,269 j/held** (epoch 145).
**Phase 5** (tournament + close-the-gap): ✅ Complete — 22+ submissions, best 11.31 (rank 426/635+). Large arch no improvement. p25 analysis → cooperation-with-strangers diagnosis.
**Phase 6** (AIF v23 social cognition): ✅ Complete — 8 observation modalities, team coordination, passive ally tracker. 242 tests.
**Phase 7** (FCP + PFSP): ✅ Complete — `cogsguard_aif_fcp.py` recipe with FCP teammate diversity + PFSP regret-based sampling.
**Phase 8** (literature survey): ✅ Complete — 50+ cooperative MARL papers surveyed, approach grounded in academic literature.
**SkyPilot 6B run**: Running — 41.8% (2.5B / 6B steps), 10,820 j/held, climbing.

**Key milestones:**
- **R17 (2026-04-03)**: Adopted metta's sweep-optimal hyperparams (8x higher LR, weight_decay=0.3, etc.)
- **R18 (2026-04-03)**: Batch size scaling tests (256K/512K/1M)
- **R19 (2026-04-04)**: KL kickstarting = 7.0j peak (S1). EER mode corrupts value function. Teacher-led diverges.
- **R20 (2026-04-06)**: Isolation experiments — T3 hit **8.0j peak** (new record). ALL 4 runs entropy collapsed.
- **R21 (2026-04-08)**: Entropy collapse prevention — E4 (ent=0.15) **survived 1B steps** (first ever). Adaptive controller had 3 bugs, all fixed.
- **R22 (2026-04-08)**: Scale E4 config to 2B steps — confirmed entropy stability at scale.
- **R23 (2026-04-13)**: Fixed 3 bugs: scripted_teacher.py IDs (0.18→0.22), dead encoder (ReLU→LeakyReLU), tok.location fix. Teacher confirmed working (0% noop), but still **0 junctions**.
- **R24 (2026-04-16)**: **TRUE ROOT CAUSE FOUND AND VALIDATED** — Policy outputs Discrete(5) = movement only. Without supervisor, `vibe_actions.fill(0)` → default vibe → agents CANNOT mine/craft/align. This caused 0 junctions in ALL R1-R23. Fix: transport-encoded actions. **Phase 1 result: `aligned.junction = 1.5` at 50M steps** — first PPO junctions ever. Full economy chain confirmed (mine → deposit → withdraw → align).
- **50M v3 (2026-04-21)**: Track A recipe on AWS 4xL4 with cuda teacher (cinky). **823.3 j/held** at 50M steps (exponential learning curve: 0.1→12→68→169→396→823). Entropy healthy at 2.94.
- **500M cinky (2026-04-22)**: Converged at **8,639 j/held** (epoch 189). Eval: **6,926 j/held** (10k-step arena). Note: cinky achieves this with ZERO vibe supervision (CUDA teachers can't output split-action vibes). Training metric ≈ eval metric (~1:1).
- **PazBot-v47 teacher (2026-04-29, ACTIVE)**: TrainerSideTeacherRunner, 16 workers, ~48% vibe fraction. Epoch 29: **1,218 j/held**, growing ~72 j/epoch. 14% ahead of cinky at same step count. Eval: **1,863 j/held** = 27% of cinky convergence. Throughput: 3.0 ksps / ~380 j/hr (vs cinky's 17 ksps / ~2,800 j/hr = 7.4× wall-clock gap). Testing whether vibe supervision raises ceiling above cinky's 8,639.
- **PR #11757 (2026-04-21)**: Submitted to Metta-AI/metta: `adaptive_entropy.py` + `cogsguard_aif_team.py`. Codex review requested P1 (checkpoint persistence) + P2 (DDP entropy sync) — both fixed.

**Best results to date:**
- **PPO tournament (cinky-pazbot-v500)**: **11.31** score (rank 426/635+). Best tournament submission.
- **PPO track (SkyPilot 6B, ACTIVE)**: **10,820 j/held** at 2.5B steps (41.8%), climbing. Job 2899, 4x L4. v100/v200/v300 checkpoints on S3.
- **PPO track (cinky teacher, 500M)**: Converged at **8,639 j/held** (training), **6,926 j/held** (eval). No vibe supervision (CUDA teacher limitation).
- **PPO track (cinky-from-PazBot)**: Peaked **7,269 j/held** (epoch 145). Teacher annealing counterproductive (v1300 VOR 10.46 > v2300 VOR 8.53).
- **PPO track (marlbro role-specialized, 500M)**: Peaked **8,218 j/held** (epoch 224). Tournament: 4.29 (role specialists don't cooperate well with strangers).
- **PPO track (large arch, 500M)**: sweep_mode 384/768/96, **no improvement** over default (6.87 tournament vs 11.31).
- **AIF track (v23)**: 8-modality social AIF agent with team coordination, passive ally tracker. 242 tests.
- **AIF track (v19 standalone)**: **12,303 j/held** (first non-zero alignment). Structure learning: 22.63 j/agent (4x baseline).
- **Note**: ALL PPO results R1-R23 had 0 actual junctions due to missing vibe actions.

**Tournament standings (2026-05-07):**

| Rank | Submission | Score | Matches |
|------|-----------|-------|---------|
| 426 | mahault-cinky-pazbot-v500:v1 | **11.31** | 26 |
| 589 | mahault-large-v243:v1 | 6.87 | 20 |
| 613 | mahault-large-v100:v1 | 6.40 | 26 |
| 670 | mahault-large-v200:v1 | 4.32 | 26 |
| 671 | mahault-marlbro-v243:v1 | 4.29 | 11 |

**p25 analysis**: Our p25=1.8 vs slanky p25=31.3 (17x gap). Our p95=45.4 matches top policies. Problem is cooperation-with-strangers, not raw capability.

**Active workstreams:**

- **FCP + PFSP (COMPLETE)**: `cogsguard_aif_fcp.py` recipe with Fictitious Co-Play (4 learner + 4 frozen teammate agents, LeaderboardSource top 20 + TrainingRunSource). PFSP variant with PrioritizedRegretConfig. SkyPilot config ready. **Next**: Launch FCP training.
- **SkyPilot 6B (RUNNING)**: Job 2899, 41.8% complete (2.5B / 6B steps), 10,820 j/held. v300 checkpoint available as teacher.
- **AIF v23 social cognition (COMPLETE)**: 8 observation modalities (added team_coord, map_coverage), ARRIVED nav state, INTERACT action, team-conditioned C vectors, adaptive role switching, PassiveAllyTracker for PPO stranger teammates. v23 kickstart running on EC2 with PazBot teacher.
- **Literature survey (COMPLETE)**: 50+ cooperative MARL papers surveyed. Key finding: partner specialization matters alongside diversity (NeurIPS 2024). Validates Safa's Coggerbro approach. See `aif-meta-cogames/docs/LITERATURE_REVIEW.md`.
- **Track C — VFE as a loss function (research frontier)**: Implement VFE/EFE as a LossConfig that augments PPO. Deferred pending FCP results.
- Meta-learning (S7b): **POMDP module complete (288-state)** — Collaboration with Luca, Alejandro & Daniel

**Next priorities:**
1. Launch FCP training on SkyPilot (highest-impact intervention for p25)
2. Role-specialized FCP (combine Safa's Coggerbro pattern with FCP diversity)
3. Submit SkyPilot 6B checkpoints (v300+) to tournament
4. Confidence-weighted belief sharing for AIF agent (addresses echo chamber risk)

---

## Research Hypothesis

**Claim**: An active inference agent with hierarchical role selection and teammate modeling will outperform flat PPO agents on VOR scoring, because:

1. **Role specialization emerges** from EFE minimization — the agent selects the role that most reduces expected free energy given current team composition
2. **Spatial memory** from the generative model enables long-horizon planning that LSTM cannot learn from reward signal alone
3. **Teammate modeling** enables adaptive coordination — the agent complements unknown teammates instead of duplicating their behavior
4. **Epistemic foraging** drives efficient exploration of the partially observable map

**Methodology**: Rather than jumping straight to AIF, we systematically evaluate MARL approaches (neural architectures, role discovery methods, hierarchical planning, communication) to identify which bottlenecks they solve and where they fail. Each approach's failure modes inform the AIF agent design — AIF is the capstone that integrates lessons from all prior experiments.

**Context update**: slanky is confirmed scripted (PI, 2026-03-11), not learned. No learned agent has scored >6 on the leaderboard. Our best learned submission: flat PPO = 1.77.

**Minimum success criterion**: Produce a learned agent that scores >6 on the leaderboard (no learned agent has achieved this — PI confirmed 2026-03-11).
**Stretch goal**: Approach the scripted dinky policy (21.09).

---

## Key Risks

| Risk | Mitigation |
|------|------------|
| Active inference too slow for 10,000-step episodes | Amortized inference, coarse temporal resolution for high-level, neural low-level |
| Generative model doesn't scale to 100x100 maps | Hierarchical spatial representation (local detail + global summary) |
| Observation token format is complex | Reuse Planky's obs_parser.py and entity_map.py patterns |
| 80 hours too few for full implementation | Prioritize PoC over polish; hybrid approach (Planky-style low-level + AIF high-level role selection) |
| Disk space on AWS (30GB, 3GB free) | Request volume expansion from Subhojeet; minimize CUDA cache |
| ~~PufferLib GPU training crashes~~ | **RESOLVED**: See [README.md](README.md#pufferlib-cuda-kernel-fix) |
| Version incompatibility blocks submissions | Upgrade to cogames 0.22; test all patches still work; verify ship bundle includes dependencies |

---

## What Tier 1 Results Taught Us About AIF Design

| Result | What it told us | AIF implication |
|--------|----------------|-----------------|
| A1 (forced roles) → 2.5 junctions | Role discovery IS the bottleneck | Economy chain must be in generative model (B matrix) |
| A3 sweep → 3.214 junctions | PPO learns economy with right reward signal | But ceiling is low — model-based planning needed |
| A4 (curriculum) → 0 junctions on machina_1 | Arena configs don't transfer | Per-variant adaptation needed → meta-learning (H1) |
| A1.5 (individual roles) → 12+ junctions | Specialization works, composition is the challenge | AIF role selection via EFE, not learned roles |
| Kickstarting failed | Teacher-student doesn't compose easily | AIF coordination via G-coupling, not distillation |
| slanky is scripted | No learned agent >6 on leaderboard | Model-based (AIF) may be the only viable path |

*Full experiment details: [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md)*

---

## Mapping to Social-Layer Architecture

The CogsGuard environment maps remarkably well to the social-layer project:

| Social-Layer Component | CogsGuard Equivalent |
|----------------------|---------------------|
| UnifiedTaskController | Role selection (mine/align/scramble/scout) |
| Generative model (288-state POMDP) | CogsGuard state: phase(6) x hand(4) x target_mode(3) x role(4) |
| Intent particle filter | Teammate role inference from vibes + behavior |
| G_self (risk) | Junction control preference, resource sufficiency |
| G_other (social) | Team-level territory control, complementary roles |
| Obstruction geometry | Resource contention between teammates |
| Commitment inference | Stick with current role vs switch |
| EFE-based policy selection | Role + action selection minimizing expected free energy |
| VFE for valence/arousal | Could drive adaptive exploration intensity |

This is the strongest argument for using active inference here: **the problem structure is nearly identical to what the social-layer already solves** — multi-agent coordination through emergent role specialization under partial observability.

---

## Meta-Learning × Active Inference: Research Collaboration

**Collaborators**: Mahault Albarracin, Luca Manneschi, Alejandro

**Dual purpose**: CogsGuard serves as both (a) the Softmax contract deliverable and (b) an empirical testbed for an AIF meta-learning research paper.

### How CogsGuard Enables Meta-Learning Research

CogsGuard provides a natural **task family** with structured variation:

| Dimension | Variations | What changes structurally |
|-----------|-----------|--------------------------|
| Map topology | arena (50x50), machina_1 (88x88), cave variants | Spatial structure, resource density, junction layout |
| Team size | 4, 8 cogs | Coordination complexity, role allocation pressure |
| Clip strategy | no_clips, fast_clips, slow_clips | Adversarial pressure, territory defense needs |
| Role distribution | all miners, balanced, VOR mixed teams | Coordination requirements, complementarity |
| Event profiles | standard, miner_tutorial, aligner_tutorial | Available roles, reward structure |

This gives a rich enough distribution P(task) for meta-learning while keeping the core game mechanics constant — exactly what hierarchical Bayesian approaches need.

### Synergies with Luca/Alejandro's Projects

| Their project | Synergy with CogsGuard |
|--------------|----------------------|
| **Dreamer self/other distinction** | World model that explicitly models self vs teammates vs opponents — directly applicable to ToM in CogsGuard |
| **LSA as layer-wise energy minimisation** | Could serve as efficient inner-loop mechanism for neural AIF (H3/H4) |
| **Test-time OOD adaptation router/teacher** | VOR scoring IS distribution shift — agent must adapt to unknown teammates at test time |

### Publication Strategy

1. **Quick result** (H5): Active task selection on CogsGuard → workshop paper (Active Inference Workshop)
2. **Full paper** (H1 + H2): Hierarchical AIF meta-learning with EFE structure selection → NeurIPS/ICLR
3. **Extension**: Neural AIF (H3) + amortized planning (H4) → scalability story

---

## PI Meeting Notes (2026-03-10) — Game-Changing Insights

### Meeting Context

Call with Subhojeet (Subhojeet), PI on the Softmax contract. Discussed our Phase 1-2 results, the gear wall, and the path forward.

### Key Takeaways

#### 1. Train Individual Roles Separately (NEW — highest priority)

**What**: Train a **miner-only agent** (all 8 agents are miners) and an **aligner-only agent** (all 8 agents are aligners) separately. Submit as a combined policy (e.g., 4 miners + 4 aligners).

**Why this changes everything**: Our "Category 1 exhausted" conclusion was premature. We never tried training homogeneous teams. Each agent only needs to learn ONE chain step, not the full economy. A miner just needs: mine → deposit. An aligner just needs: withdraw hearts → acquire gear → capture junctions.

**Confirmed by**: Noah (another researcher) already did this using PufferLib tutorials. Subhojeet confirmed it works.

#### 2. Kickstarting / Behavioral Cloning from Scripted Teacher (THE proven path)

**What**: Add a KL divergence loss between the student policy and a scripted teacher (dinky/planky):

```
L_total = L_ppo + α · KL(π_student || π_teacher)
```

- For **deterministic** teacher (dinky outputs one action): KL reduces to cross-entropy loss
- **α = 1.0** held constant for first **2.5B steps**
- **Annealed from 1.0 → 0** over steps **2.5B to 10B**
- **Pure PPO after 10B steps** with `objective_mine` variant for continued improvement
- Total training: ~10B+ steps (much longer than our 50M arena runs)

**Why this solves the gear wall**: The teacher *demonstrates* the full economy chain including gear acquisition. The student gets a direct gradient for actions it would never discover through exploration alone.

**Note**: slanky is likely scripted (PI clarified 2026-03-11). The kickstarting recipe below is a separate approach for training learned agents, not a description of how slanky was built.

#### 3. Cortex Architecture (replaces CNN+LSTM)

**What**: Metta-AI's internal hybrid RNN library with:
- **AGaLiTe (Ag)**: Attention-based hybrid memory module
- **Axon (A)**: Streaming RTU (Recurrent Transient Unit) with diagonal input weights, RTRL for gradient flow
- **sLSTM (S)**: Stabilized LSTM variant
- Pattern: **"Ag,A,S"** (AGaLiTe, Axon, sLSTM)
- Public package: https://github.com/Metta-AI/cortex — can use directly

**Why**: Addresses our documented Failure #3 (CNN is wrong inductive bias for entity tokens) and #4 (LSTM insufficient for spatial memory over 10K steps). The associative memory and RTRL solve the long-horizon credit problem architecturally.

#### 4. Training Infrastructure Improvements

- **Gradient TD**: More stable value estimation for long horizons. Replaces standard TD.
- **Reward centering**: Stability hack for large gamma values. We use γ=0.999, which is exactly where this helps.
- Both available in the meta repository.

#### 5. Meta Repository Access

Subhojeet will add user to **private meta repository** — contains:
- Cortex architecture implementation
- BC/kickstarting training pipeline
- Gradient TD and reward centering
- Internal training infrastructure

#### 6. Research Proposal Required

User committed to sending a research proposal to Subhojeet. Should outline:
- What we've learned from Category 1 experiments (gear wall, exploration problem)
- Proposed path: individual role training → kickstarting → Cortex → communication → AIF capstone
- How AIF/meta-learning connects to Subhojeet's long-term vision

#### 7. Subhojeet's Long-Term Vision (for research proposal context)

- **General continual learning agent** — not just CogsGuard-specific
- **World model** — learn environment dynamics, use for planning
- **Options framework** — temporal abstraction (mine_resource, deposit, etc. as options)
- **Successor features** — transfer across CogsGuard variants
- **Curriculum via variants.py** — progressively harder environments

Our AIF capstone (H1: hierarchical meta-learning) maps cleanly onto this:
- Hierarchical generative model ≈ world model + options
- EFE-based task selection ≈ curriculum learning
- G-coupling / ToM ≈ multi-agent coordination via communication
- Hyperprior adaptation ≈ successor features / continual learning

### PI Feedback on Research Proposal (2026-03-11)

After reviewing the research proposal, Subhojeet provided two key pieces of feedback:

1. **A1.5 (individual roles) should precede A5 (kickstarting)**: "Noah's specialized roles probably a better baseline to start with rather than kickstarting, rollouts with scripted teacher is really slow, that would affect training speed." This confirms A1.5 as the priority — kickstarting has a fundamental speed bottleneck (scripted rollouts) that makes it expensive for iteration.

2. **AIF direction approved**: "I'm generally happy with the research direction you're taking. I appreciate approaches that are grounded in theory, and active inference seems like a promising and fairly general starting point. I'd love to talk more about it during our meeting on Friday." This validates Step 5 (G-coupling capstone) as the core research contribution.

### PI Meeting Notes (2026-03-18)

1. **Wants mathematical formalization** — "write that down in terms of math: objective function, inputs, outputs." Repeated request for precise notation over prose descriptions.
2. **Terminology clarification needed** — Subhojeet sees what we described as closer to *hierarchical RL* (learning which subroutines to execute) than *meta-learning* (learning to learn). We need to be precise: the MAML outer-loop over A/B matrices across 36 variants IS meta-learning; the pymdp agent selecting task-level policies is closer to hierarchical control.
3. **Exploration is the key question** — "What is the intrinsic drive? Is it well-suited for partially observable environments?" He wants to understand how AIF epistemic value compares to successor features (their internal approach).
4. **Send AIF papers** — Requested papers on epistemic value / exploration mechanism, especially the math.
5. **Building "general agent substrate" internally** — prediction loss + world model + planning + intrinsic motivation from successor features. Wants to see if AIF offers something better or complementary.
6. **Praised repo organization** — Liked experiment tracking and roadmap structure.

**Action items**:
- [x] Write math formalization doc — see [AIF_DESIGN.md](AIF_DESIGN.md)
- [ ] Send Subhojeet key papers (R-AIF, Wei 2024, Champion 2024, Albarracin 2026)
- [x] Provide daily/weekly updates on progress — attending Tuesday + Thursday standups

### PI Meeting Notes (2026-04-22) — Teacher Mode Clarification + Cluster Access

**Context**: Sync call with Subhojeet. Discussed Track A progress (823 j/held at 50M, later converged to 8,639 at 500M), teacher modes, kickstarting strategy, cluster access.

#### Key Takeaways

1. **Teacher mode naming clarification** (critical insight):
   - `scripted.supervisor.mixed` = **cross-entropy loss** (hard action labels from scripted teacher). The teacher outputs a single action → one-hot encoding → cross-entropy loss. Appropriate when teacher is scripted (hard labels only).
   - `learned.kickstarter.mixed` = **KL divergence loss** (soft probability distributions from neural teacher). The teacher outputs a full logit distribution → KL(student || teacher). Appropriate when teacher is a learned policy (soft labels available).
   - **Subhojeet agrees naming is confusing** — suggested creating a PR to rename. The first part should describe *what you're learning from* (scripted vs learned), the second part should describe *the loss function* (supervisor=CE, kickstarter=KL).
   - **Key principle**: CE and KL are not very different — "KL divergence loss becomes cross entropy loss" when using hard probabilities. The difference is informational: KL preserves the full distribution, CE only captures the argmax.

2. **No teacher forcing recommended**:
   - `teacher_led_proportion` controls what fraction of rollout steps use teacher-forced actions
   - `mixed` mode = per-timestep sampling of teacher-forced vs student-led
   - `sliced` mode = per-trajectory sampling (entire trajectory is either teacher-forced or student-led)
   - **Subhojeet's recommendation: set teacher forcing to ZERO**. Just let the KL loss do its job. "I just do KL divergence of pros and tropics, that's it."
   - This is important for our Track A recipe: `teacher_led_proportion=0.0` (already our default)

3. **Extend the run, don't immediately switch**:
   - Subhojeet suggested looking at the loss coefficients and extending training rather than immediately switching teacher modes
   - "You should probably see the loss coefficients, the number of time stamps the teacher is..."
   - **Implication**: The 823 j/held from 50M steps did improve further — 500M converged at **8,639 j/held** (eval: 6,926).
   - Note: cinky's 8,639 is with ZERO vibe supervision (CUDA teachers can't output split-action vibes). PazBot teacher run (with vibes) tests whether distributional advantage raises the ceiling.

4. **Cluster access via SkyPilot**:
   - **SkyPilot** is the job scheduler for the metta cluster. Two modes:
     - **Sandbox**: SSH-able GPU instance (default L4). `metta sandbox create <name>` → SSH into it, run experiments interactively
     - **Launch**: Submit a job that runs in the background. Monitor via W&B. `metta launch <recipe> <args>`
   - **Auth chain**: `metta status` checks AWS, W&B, and SkyPilot login. Need all three.
   - **Windows issue**: `metta install` may not work natively on Windows. Subhojeet suggested WSL. Alternative: run `metta install` on the AWS sandbox itself.
   - **Kelsey** is handling access setup. She's going to talk to the relevant people.
   - **Observatory key doesn't matter** for cluster access — SkyPilot handles AWS directly.

5. **Standup schedule**:
   - Come to **both Tuesday and Thursday** standups
   - Team is small: Subhojeet + Richard + contractors
   - **Richard** works on training and is connected to cogames dev team (Nish etc.) — relay bugs/feature requests through him
   - Format: informal sync, present what you're working on

6. **AIF compatibility concern raised but not resolved**:
   - User mentioned "none of the things that you guys have done is really compatible with [active inference]"
   - Subhojeet focused on the PPO/kickstarting track for now
   - Track B (AIF as recipe) and Track C (VFE loss) remain future work

**Action items from this meeting**:
- [x] Update slides for Thursday standup
- [ ] Extend the 50M supervisor run to 500M+ (already done — but student-only still ~1.0j)
- [ ] Try kickstarter mode with learned teacher (recipe updated, AWS SSO unblocked — ready to launch)
- [ ] Get SkyPilot access via Kelsey
- [ ] Consider running `metta install` from WSL or AWS directly
- [ ] Create PR to rename teacher modes (Subhojeet suggestion)

### Cortex Version Discovery (2026-03-17)

**Critical finding**: The standalone GitHub repo (`github.com/Metta-AI/cortex`) and the Metta monorepo (`metta/packages/cortex/`) have **diverged**:

| Feature | Standalone GitHub | Monorepo (`metta/packages/cortex/`) |
|---------|------------------|--------------------------------------|
| Pattern string (`"Ag,A,S"`) | Removed | Works |
| Stack building | `layers` param (explicit cell configs) | `pattern` + `build_cortex_auto_stack()` |
| Internal structure | `scaffolds` | `blocks` |
| sLSTM backward | **Crashes** (autocast bug) | Works |

The standalone repo's sLSTM custom `torch.autograd.Function` backward crashes with `AttributeError: '_rnn_fwbwBackward' has no attribute '_fwd_used_autocast'` under PufferLib's autocast. Subhojeet confirmed: "There is a PR which should fix this."

**Solution**: Install cortex from monorepo: `pip install ~/projects/cortex-monorepo` (SCP'd from `metta/packages/cortex/`).

### S6: Cortex Training (FAILED — 2026-03-19)

**Config**: d_hidden=64, num_layers=2, pattern="Ag,A,S", ent_coef=0.03, 50M steps, milestones reward, 4 agents, 4 envs.

**Params**: 573K (comparable to TutorialPolicyNet's ~500K — fair comparison per Subhojeet's feedback).

**Result**: **0 junctions. FAILED.** explained_variance collapsed 0.995 → -0.002, agents dying at step 11.

**Root cause**: PufferLib 3.0.17 never zeros LSTM/Cortex state when episodes end within an `evaluate()` call. Standard LSTM tolerates stale state (forget gate decays it), but Cortex's AGaLiTe tick counter and sLSTM commitment state become corrupted across episode boundaries. Dead agents' state persists into the next agent's episode.

**Fix**: `patch_pufferl_v2.py` — zeros `lstm_h` and `lstm_c` for agents whose `done` flag is set, immediately after state is stored back in PufferLib's evaluate loop.

### S7: Cortex + Scripted Teacher Kickstarting (FAILED — 2026-03-20)

**Config**: d_hidden=64, pattern="Ag,A,S", ent_coef=0.03, **update_epochs=1** (error — should have been 3), 50M steps, milestones reward, 8 agents, 4 envs. Scripted teacher kickstarting (ks_coef=0.1, anneal_frac=0.5). Episode-reset patch applied.

**Result**: **0 junctions.** Entropy drifted to near-max (1.575), explained_variance stuck near 0. Kickstarting annealed off at 25M steps, leaving policy unanchored.

### S8: Cortex, u=3, No Kickstarting (FAILED — 2026-03-20)

**Config**: d_hidden=64, pattern="Ag,A,S", ent_coef=0.03, **update_epochs=3**, 50M steps, milestones reward, 8 agents, 4 envs. No kickstarting. Episode-reset patch applied. Clean apples-to-apples comparison with LSTM A3 best.

**Result**: **0 junctions.** Worse than S7 — policy_loss exploded to 20.8, entropy at max (1.609 = uniform random), clipfrac=0 (zero gradient signal). u=3 amplified damage from broken value function.

### S9: Cortex-LSTM Control Test (FAILED — 2026-03-24)

**Goal**: Isolate whether the issue is state packing or specific cells (per Subhojeet's suggestion).

**Config**: Cortex with `LSTMCellConfig()` × 2 layers, d_hidden=64, ent_coef=0.03, update_epochs=3, 50M steps. No kickstarting.

**Params**: 459K. **Result: 0 junctions.** Same collapse as S5-S8 — entropy→max (1.609), expl_var→0, clipfrac=0. Early metrics (expl_var=0.970 at 7.6M steps) were transient.

**Root cause discovery**: The AGaLiTe tick hypothesis was WRONG. The real issue was **architecture mismatch**:

| | Native LSTM (3.21 junctions) | CortexPolicyNet S5-S9 |
|---|---|---|
| Encoder | Linear(600→128→128) | CNN (2 Conv2d) + dual Linear→32 |
| Hidden dim | 128 | 64 |
| LSTM layers | 1, nn.LSTM | 2, Cortex scaffold |
| Params | 226K | 459K |
| Obs preprocessing | Flatten + /255 | Token grid + scatter_add |

Multiple variables changed simultaneously. PufferLib also zeros ALL recurrent state at the start of every `evaluate()` call — state never persists beyond `bptt_horizon=64` steps. The tick fix, episode-reset patch, and detect-and-restore were all irrelevant.

### S10: Cortex-LSTM Native Architecture Match (FAILED — 2026-03-24)

**Goal**: True apples-to-apples — Cortex wrapping nn.LSTM with same encoder, same hidden dim, same obs preprocessing as native LSTMPolicyNet.

**Config**: Linear encoder (600→128→128), d_hidden=128, 1 Cortex-LSTM layer, ent_coef=0.03, update_epochs=3, 50M steps. No kickstarting. `post_norm=True` (Cortex default).

**Params**: 226,566 (vs native 226,310). hidden_size=128 (same as native).

**Result: 0 junctions. FAILED.** Entropy stuck at exactly 1.609 (uniform random) for entire 40M+ steps. Zero learning — clipfrac=0, approx_kl=0, importance=1.0. Policy never changed from initialization.

**Root cause: `post_norm=True` kills LSTM gradients.** Cortex's `build_cortex_auto_stack(post_norm=True)` applies LayerNorm after the LSTM, which crushes gradient signal by **145,000x**:

| | `post_norm=True` | `post_norm=False` |
|---|---|---|
| weight_hh grad | 0.0000008 | **0.6937** |
| weight_ih grad | 0.0000015 | **0.1937** |
| grad to input | 0.0000004 | **0.0509** |

The LSTM's recurrent weights (`weight_hh`) receive zero gradient → never learns temporal dependencies → network degenerates to a feedforward MLP → uniform random policy.

**Additional finding**: Gradient monitoring in `train_cortex.py` was broken — `gradient_norms()` was called after `trainer.train()` which includes `optimizer.zero_grad()`, so it always reported 0.0. This masked the root cause.

### S11: Cortex-LSTM with post_norm=False (FAILED — 2026-03-24)

**Config**: Identical to S10 except `post_norm=False`. Killed early — entropy drifting toward max (1.575).

**Root cause: Resets broadcast to all timesteps.** `resets.unsqueeze(1).expand(-1, bptt_horizon)` broadcast the episode-reset flag to every timestep in the BPTT window, resetting LSTM hidden state at every step. LSTM had no temporal memory — functionally feedforward.

**Diagnostic tests** (8 tests, 6 pass / 2 fail):
- Test D (temporal sensitivity): **FAIL** — perturbation at t=0 had zero effect on t=1+
- Test G (state across calls): **FAIL** — state stored but not read back
- `weight_hh` gradient: 0.0 (recurrence completely dead)

**Scaffold finding**: With E=1 (single expert), the scaffold is transparent — no residual, no norm, no mixing. Cortex LSTM is mathematically identical to native `nn.LSTM` (Test B: zero output difference). The resets handling was the sole remaining issue.

### S12: Cortex-LSTM with resets fix (FAILED — 2026-03-24)

**Config**: Both fixes applied (post_norm=False + resets t=0 only). Custom `train_cortex.py`.

**Result**: Started learning (entropy=1.48, expl_var=0.57 at 2.6M steps) but collapsed to uniform random by 50M steps. Final: 0.333 junctions, entropy=1.609, expl_var=-0.612.

**Root cause**: Custom training loop. Despite correct gradient flow (weight_hh=84.56), `train_cortex.py` used different hyperparameters than `cogames train`: bptt_horizon=64 (vs 128), update_epochs=3 (vs 1), ent_coef=0.03 (vs 0.05), 1 worker (vs 4).

### S13: Cortex-LSTM via `cogames train` (SUCCESS — 2026-03-24)

**Config**: Same CortexPolicyNet as S12, but trained via native `cogames train` pipeline:
```bash
PYTHONPATH=scripts/policy cogames train -m cogsguard_arena.basic -p class=cortex_policy.CortexPolicy --cogs 8 --steps 50000000
```

**Result: Peak 3.750 junctions — exceeds native LSTM A3 best (3.214) by 17%.** expl_var=0.985, entropy=1.601. Training completed in 24 min (vs 1.5h with custom script). Junction instability (3.75 peak → 0.07 final) is characteristic of arena coordination variance.

**Key finding**: The custom `train_cortex.py` was the final confound. Four bugs identified and fixed across S5-S13:
1. Architecture mismatch (S5-S9): CNN encoder, d=64, 2 layers
2. `post_norm=True` (S10): 145,000x gradient kill on weight_hh
3. Resets broadcast (S11): LSTM reset at every timestep
4. Training loop (S12): bptt=64/u=3/ent=0.03 vs native bptt=128/u=1/ent=0.05

### Cortex Status

**Cortex-LSTM WORKS** when using `cogames train` (S13: 3.75 peak junctions, 17% above native LSTM). All future experiments must use the native pipeline — custom training scripts introduce fatal confounds.

**Training pipeline audit**: All pre-Cortex experiments (Phase 2, A3 sweep, A1.5, machina_1) used `cogames train` and remain valid. Only S5-S12 used the custom `train_cortex.py` and are confounded. Key invalidated conclusions: "u=1 → 0 junctions" (wrong — cogames train uses u=1 successfully), "Ag,A,S doesn't work" (untested — 5 confounds stacked), "kickstarting hurts Cortex" (invalid — tested with all bugs active).

**Cortex cell experiments (all via `cogames train`)**:
- **S14: Axon** — DONE. Peak 2.25j (works but underperforms LSTM — linear SSM has limited capacity alone)
- **S15: Ag,A,S (E=3)** — DONE. Peak 2.56j. Dead router: Wq/Wk=0, mixer near-dead, 97% residual. Works but underperforms LSTM despite 5x params.
- **S16: Ag,A,S sequential (E=1x3)** — DONE. Peak 2.25j (epoch 56). Sequential layers did NOT fix underperformance. Real issue: overparameterization + premature convergence. Entropy collapsed to 1.436 (89% of max) vs LSTM's 1.601 (99.4%).

**Diagnosis**: The problem is NOT architecture-specific (router, tick corruption, etc.) but a well-documented RL scaling pathology: larger networks converge prematurely in RL (unlike supervised learning). Causes: primacy bias, plasticity loss, dormant neurons, representation collapse. LSTM's 226K params are better-suited to the 5-action grid world than Cortex's 1M+ params.

**Hyperparameter sweep (S17-S22)** — COMPLETE (2026-03-25):
- **S17**: LSTM control → **3.333j** (reproduces baseline)
- **S18**: Ag,A,S seq, ent=0.08 → 2.500j
- **S19**: Ag,A,S seq, ent=0.08+wd=1e-4 → 2.667j
- **S20**: Ag,A,S seq, ent=0.12 → **2.778j** (best Cortex, +23% vs S16)
- **S21**: LSTM, ent=0.08 → 2.375j (higher entropy HURTS LSTM)
- **S22**: Ag,A,S seq, ent=0.08+u=3 → 2.667j

**Sweep R2 (d_hidden=64)** — COMPLETE (2026-03-25):
- S23 Ag,A,S d=64 ent=0.12 → 2.500j, S24 defaults → 2.500j
- S25 Axon d=64 ent=0.12 → 2.263j, S26 defaults → 2.500j
- S27 LSTM d=64 → 2.667j, S28 Ag,A,S d=64 ent+wd → 2.600j

**Conclusion (0.18)**: Overparameterization hypothesis falsified — d=64 underperforms d=128 across the board. LSTM d=128 (226K params) is the sweet spot. The problem is architectural fit, not param count: LSTM's forget gate is well-matched to this 5-action grid world at 50M steps. Cortex advanced cells don't provide useful inductive bias here. 16 experiments total (S13-S28).

**Cortex v0.19 sweep** — COMPLETE (2026-03-28): Retested all cell types on cogames 0.19 (changed hyperparams: vf_coef=2.0, ent_coef=0.01, bptt=64). Results:
- **sLSTM: 5.0j** (dominant winner, +67% over LSTM)
- LSTM: 3.0j
- mLSTM/AGaLiTe/LSTM2: 2.0j
- XL/Conv1d: 1.5j

**Tier 1 PPO fixes** — COMPLETE (Rounds 7-12): Discovered universal advantage collapse from vf_coef=2.0. Implemented: PFO (L2 regularization), separate actor/critic LR (critic 0.2x), asymmetric clipping, ReDo (dormant neuron reset). Best: I3v2 (no_clips+aligner) = **4.0j peak**. Dual-gamma (L1) best mean = 2.05j. Target net (L4b) best peak = 4.5j.

**Cortex final verdict**: sLSTM d=128 is the champion on 0.19. Submitted as `mahault.cortex_slstm_v2:v1`.

### Literature Grounding

**Each Cortex component is individually validated at top venues:**
- **AGaLiTe**: TMLR 2024 (Pramanik et al.) — outperforms GTrXL by 37%+ on Memory Maze, 40% less compute. Tested on Craftax (similar to MettaGrid).
- **Axon/RTUs**: NeurIPS 2024 (Elelimy et al.) — efficient RTRL, O(n) per step, outperforms GRUs and Transformers on POMDP tasks.
- **sLSTM/xLSTM**: NeurIPS 2024 (Beck et al., Schmied et al. LRAM) — validated across 432 tasks in 6 domains.
- **RTRL in RL**: ICLR 2024 (Irie et al.) — 8x data efficiency on DMLab memory tasks.

**The Ag,A,S combination is novel:**
- No published work combines linear transformers + RTRL + sLSTM in RL, let alone MARL.
- This is the research gap and opportunity — each component is proven, the stack is untested.

**Key actionable findings:**
- Per-layer gradient monitoring recommended for heterogeneous stacks (RLBenchNet 2025).
- RTRRL (AAAI 2025, Lemmel & Grosu) suggests RTRL+TD may outperform PPO — relevant to Axon integration.
- Episode boundary handling is a known challenge for non-LSTM recurrences (S5 paper, Lu et al. NeurIPS 2023) — directly explains our S5-S8 AGaLiTe tick-reset failures.
- Focus on learning efficiency over kickstarting — S7 kickstarting failure was confounded by custom training script + bugs; kickstarting on Cortex remains untested via native pipeline.

**Bridge to AIF:**
- DAIF (Yeganeh et al., 2025) and MTRSSM papers show learned recurrent world models can combine with EFE-based planning.
- Directly relevant to AIF capstone (S7a/H1): Cortex as the recurrent backbone for a neural AIF agent.

**References**: Full literature review at [LITERATURE.md](LITERATURE.md), technical analysis at [archive/CORTEX_PUFFERLIB_RESEARCH.md](archive/CORTEX_PUFFERLIB_RESEARCH.md).

### AIF Agent Live Eval (2026-03-17)

**Command**: `cogames eval -m cogsguard_arena.basic -p class=aif_meta_cogames.aif_agent.cogames_policy.AIFPolicy -c 4 -e 3`

**Results**: 6 hearts/agent, 0.75 aligner gear, 0 junctions, reward 1.0.

**Architecture (Phase 3, superseded)**: Hybrid pymdp (18-state POMDP) + rule-based navigator. 26/26 tests. 6 hearts, 0.75 gear, 0 junctions.

**Design oversight identified**: 5 primitive movement actions produced action-independent B matrices → identical EFE for all actions → uniform policy (random selection). The navigator was doing all the work; pymdp was effectively bypassed.

**Phase 3b fix (2026-03-19)**: Replaced 5 movement actions with **13 task-level policies** as the POMDP action space. Expanded state space to **216 = phase(6) x hand(3) x target_mode(3) x role(4)**. Added 3 new observation modalities (contest, social, role_signal) for 6 total. Each task policy now has distinct B matrix transitions → action-dependent B → meaningful EFE → pymdp drives policy selection. 53/53 tests pass.

**Next**: Live eval with 216-state model, G-coupling (multi-agent EFE shift), ToM inference.

### AIF Batched Eval v1 (2026-03-24)

**Command**: `cogames eval -m cogsguard_arena.basic -p class=aif_meta_cogames.aif_agent.cogames_policy.AIFPolicy -c 8 -e 3`

**Architecture**: Restructured from 8 sequential Agent(batch_size=1) to 1 Agent(batch_size=8) with per-role C/D vectors (even=miner, odd=aligner). JIT-compiled via eqx.filter_jit. Agent 0 triggers batched inference, agents 1-7 use cached results.

**Results**: 18ms/step (was 1.1s sequential, 112x speedup). 1 timeout (JIT compile). 0 junctions, 2459 noops, max_steps_without_motion=2973. Same noop-dominated behavior as before — C preferences rewarded "being at" destinations rather than penalizing idleness.

### AIF Tuned Eval v2 (2026-03-25)

**Command**: same as v1

**Changes**: Sharpened A matrices (diagonals 0.6-0.7 → 0.85+), penalized NONE/EMPTY in C preferences (miner: NONE=-1.0, EMPTY=-1.0; aligner: NONE=-0.5, EMPTY=-0.5), gamma 16→8.

**Results**:

| Metric | v1 (before) | v2 (after) | Change |
|--------|-------------|------------|--------|
| action.move.success | ~500 | 1077 | +2x |
| action.noop | 2459 | 1614 | -34% |
| max_steps_without_motion | 2973 | 443 | 6.7x better |
| Resources mined | 0 | carbon=2, oxygen=2, germanium=2 | New |
| Hub withdrawals | 0 | carbon=3, oxygen=3, germanium=3, silicon=3 | New |
| Junctions aligned | 0 | 0 | Same |
| Reward | 1.00 | 1.00 | Same |

Agents now actively navigate to extractors, mine resources, and deposit at hubs. The craft→gear→junction chain is not yet completing. C-preference tuning was the single biggest behavioral improvement.

**Also tested**: policy_len=3 (2197 policies, ~330ms/step) and use_param_info_gain=True (~330ms/step) both exceed the 250ms eval limit. Online B-learning infrastructure is in place but disabled for eval due to param_info_gain overhead.

**Superseded by**: v9.7-v9.9 deep AIF (288-state, two nested POMDPs) + parameter learning pipeline (B-I through B-VI). See `aif-meta-cogames` repo for current implementation.

---

## Recommended Research Plan (Revised — Post-PI Meeting)

### What Changed

Two waves of PI meetings reshaped the approach:

**Wave 1 (March)**: Introduced individual role training (A1.5), kickstarting (A5), Cortex architecture (B2'), gradient TD.

**Wave 2 (April 16 — Pipeline Migration)**: Fundamental shift from external contractor to internal contributor.

| April 16 Insight | Impact | Replaces |
|---|---|---|
| Internal recipe pipeline | ALL training moves inside metta recipes | External `patch_and_train.py`, custom sweep scripts |
| AIF as a recipe | Standalone pymdp agent becomes a metta recipe | Ad-hoc tournament bundle |
| VFE as a loss function | AIF principles integrated into neural PPO training | Separate AIF vs PPO tracks |
| Cognitive substrate convergence | SF ≈ epistemic value, multi-timescale ≈ hierarchical GM | "AIF vs PPO" narrative → "AIF enriching substrate" |
| Cortex Fabric | Message passing between RNN cells ≈ belief propagation | IC3Net communication layer |
| Cluster access (Nishad) | Train at metta scale (billions of steps) | Our 4xL4 AWS box for PPO |

### What Gets Deprioritized

- **IC3Net / TarMAC (E1-E3)** — Cortex Fabric provides message passing natively. G-coupling comparison shifts to Fabric-AIF vs standalone-AIF.
- **Custom sweep scripts** (`round24_vibes.sh`, `patch_and_train.py`) — replaced by recipes
- **Extended AWS PPO experiments** — training moves to metta cluster
- **R24 Phase 2 as external experiment** — learnable vibes get implemented inside a recipe instead

### What Stays Relevant

- **R24 Phase 1** — must validate vibes produce junctions (running now, last external experiment)
- **AIF standalone agent** (`aif-r2-jit-v3:v1`) — tournament reference, proves option-selection works
- **All AIF parameter learning** (B-I through B-VI, iterative pipeline) — informs recipe design
- **Meta-learning (S7b)** — paper track with Luca/Alejandro, independent of pipeline migration
- **Phase 2a/2b sweep results** — baseline comparison data

### Three-Track Metta Pipeline Migration

All future work moves inside the metta internal pipeline. Three parallel tracks:

#### Track A: PPO via Metta Recipes

The canonical recipe **already exists**: [`recipes/experiment/cogsguard.py`](https://github.com/Metta-AI/metta/blob/main/recipes/experiment/cogsguard.py) (1090 lines). It already handles:
- Transport encoding with split vibe actor (`_wire_vibe_actor_loss()` — 50/50 loss split)
- Kickstarting with teacher scheduler + annealing (`TeacherConfig` + `LossRunGate`)
- Role-specific training (`miner()`, `aligner()`, `scout()`, `scrambler()` entrypoints)
- Tuned hyperparams from sweep (lr=0.00738, wd=0.3, gamma=0.999 — same as our `SWEEP_PRESET=metta_optimal`)
- Default policy: `DefaultPolicyConfig(actor_hidden=128, critic_hidden=256, feature_extractor=BoxCNNFeatureExtractorConfig)`
- Teacher: `metta://policy/dinky_fido:v3`

Our Track A is: learn the recipe, configure it, run it on the cluster. Not build from scratch.

| Step | What | Hours | Status |
|------|------|-------|--------|
| A.1 | Get cluster access (Nishad) | 1-2 | IN PROGRESS — have AWS 4xL4, need metta cluster |
| A.2 | Study `cogsguard.py` recipe + run existing `train()` on cluster | 3-4 | ✅ DONE — deep analysis of entire loss/policy/training system |
| A.3 | Customize: adaptive entropy + recipe fork + PR | 2-4 | ✅ DONE — `cogsguard_aif_team.py` + `adaptive_entropy.py`, PR #11757 |
| A.4 | Train at scale (cinky 8,639 j/held converged, PazBot vibe teacher active) | 8-12 | IN PROGRESS — 500M cinky done (8,639), PazBot-v47 at epoch 29 (1,218 j/held, +72/epoch) |

**Key metta repo references** (verified from local clone 2026-04-17):
- Loss configs: [`metta/rl/loss/`](https://github.com/Metta-AI/metta/tree/main/metta/rl/loss) — 24 files: `loss.py` (base), `losses.py` (container), `ppo_actor.py`, `ppo_critic.py` (GTD-lambda default), `kickstarter.py`, `diff_horde.py` (multi-cumulant GVF), `eer_kickstarter.py`, `eer_cloner.py`, `action_supervised.py`, `dynamics.py`, `grpo.py`, `cmpo.py`, `contrastive.py`, `future_attribute_prediction.py`, `stable_latent.py`, `future_latent_ema.py`, `vit_reconstruction.py`, `quantile_ppo_critic.py`, `sl_checkpointed_kickstarter.py`, `logit_kickstarter.py`, `teacher_*.py`, `ema.py`
- **NOTE**: `cognitive_substrate/` directory DOES NOT EXIST yet — Subhojeet's roadmap only. No `world_model.py` standalone. No `muesli.py` standalone.
- Recipe: [`recipes/experiment/cogsguard.py`](https://github.com/Metta-AI/metta/blob/main/recipes/experiment/cogsguard.py) + 4 variants (`_fap.py`, `_coggerbro.py`, `_marlbro.py`, `coggernaut.py`)
- Policies: [`agent/src/metta/agent/policies/`](https://github.com/Metta-AI/metta/tree/main/agent/src/metta/agent/policies) — 20 files: `default.py`, `cortex.py`, `fast.py`, `puffer.py`, `agalite.py`, `fast_dynamics.py`, `drama_policy.py`, `hrm.py`, `mamba_sliding.py`, `memory_free.py`, `trxl.py`, `vit_*.py` (6 variants)
- **NOTE**: `cognitive_substrate.py` and `fabric.py` policies DO NOT EXIST yet
- Components: [`agent/src/metta/agent/components/`](https://github.com/Metta-AI/metta/tree/main/agent/src/metta/agent/components) — 21 files: `cortex.py` (CortexTD), `actor.py`, `obs_shim.py`, `obs_tokenizers.py`, `obs_enc.py`, `feature_extractor.py`, `misc.py` (MLP), `cnn_encoder.py`, `shared_critic.py`, `swin_encoder.py`, `noise.py`, etc.
- Training: `metta/rl/trainer.py` → `metta/rl/training/core.py` → `trajectory_isolation.py` → `scheduler.py` → `teacher.py`
- Fork pattern: Import from base recipe like `cogsguard_fap.py` does: `from recipes.experiment.cogsguard import train as _cg_train`

Replaces: `patch_and_train.py`, `round24_vibes.sh`, all custom sweep scripts.

**Our unique contribution (IMPLEMENTED + PR'd)**: Adaptive entropy controller (`metta/rl/loss/adaptive_entropy.py`). Proven critical at 1B+ steps — entropy collapse prevented in R21/R22. Metta's default `ent_coef=0.0257` collapses at ~500M steps. PR #11757 submitted with checkpoint persistence + DDP sync fixes.

#### Track B: AIF as a Metta Recipe

Port the standalone pymdp agent (288-state POMDP, EFE option selection, 10.43 j/agent) into recipe format.

| Step | What | Hours | Status |
|------|------|-------|--------|
| B.1 | Understand recipe env/eval interface | 2-3 | TODO (shared with A.2) |
| B.2 | Create AIF recipe: pymdp agent + scripted executors in recipe format | 4-6 | TODO |
| B.3 | Validate recipe reproduces standalone results (10+ j/agent) | 2-3 | TODO |
| B.4 | AIF on CLIPs variant (PI request) | 3-4 | TODO |

The standalone `aif-r2-jit-v3:v1` stays as tournament reference. Recipe version gets their logging, eval, and cluster infrastructure.

#### Track C: VFE as a Loss Function (Research Frontier)

Implement AIF principles as a LossConfig that augments or replaces PPO loss. The cognitive substrate bridge.

**CRITICAL FINDING (2026-04-17 deep repo analysis)**: The cognitive substrate losses DO NOT EXIST yet. Subhojeet described them as his research roadmap, not implemented code.

Files that DO NOT exist in the repo (verified from local clone):
- ~~`metta/rl/loss/cognitive_substrate/`~~ — entire directory absent
- ~~`metta/rl/loss/world_model.py`~~ — no standalone file (world model code is inside `cmpo.py`)
- ~~`metta/rl/loss/muesli.py`~~ — no standalone file (Muesli logic is inside `cmpo.py`)
- `metta/rl/loss/rnd.py` — EXISTS (Random Network Distillation, used as DDP sync pattern reference)
- ~~`agent/src/metta/agent/policies/cognitive_substrate.py`~~ — does not exist
- ~~`agent/src/metta/agent/policies/fabric.py`~~ — does not exist

What DOES exist that's relevant:
- `metta/rl/loss/diff_horde.py` — multi-cumulant GVF learning via GTD(lambda). **Best pattern to follow for VFE loss** (same two-head architecture: psi for predictions, h for auxiliary gradient correction)
- `metta/rl/loss/cmpo.py` — contains CMPO + latent model + world model prediction code (combined, not separate)
- `metta/rl/loss/dynamics.py` — dynamics prediction loss
- `metta/rl/loss/loss.py` — base `LossConfig` (factory) + `Loss` (dataclass). Lifecycle: `on_epoch_start → rollout_preprocess → rollout_postprocess → run_train → on_mb_end`

**This means Track C is GREENFIELD**: We're not building alongside existing cognitive substrate losses — we're creating the first formal VFE loss implementation. This is our biggest opportunity and directly answers Subhojeet's ask.

**Concrete integration points (from formal specs):**
- **L_wm augmentation**: The WM route's prediction loss `λ_y ||ŷ-y||² + λ_r ℓ_r(r̂,r)` is a special case of VFE under a Gaussian generative model. VFE loss generalizes this by adding the KL term: `L_vfe = E[-ln p(o|s)] + D_KL[q(s) || p(s)]`
- **SF → epistemic value**: SF intrinsic reward `κ·||ψ_{t+Δ} - ψ_t||²` is an L2 approximation of expected information gain. AIF's `D_KL[q(s|o,π) || q(s|π)]` provides the theoretically grounded version
- **β_comm → EFE-derived**: Instead of hand-tuning communication cost, derive it from EFE: communicate when `G(π_vibe) < G(π_silent)` — communication reduces expected free energy
- **Fabric = factor graph**: Each fabric cell (private state S, public interface Z, masked local attention) maps to a factor graph node (marginal belief, message, local message passing). The fabric IS belief propagation — AIF gives it a formal interpretation

| Step | What | Hours | Status |
|------|------|-------|--------|
| C.1 | Read formal specs + `diff_horde.py` pattern (cognitive_substrate/ doesn't exist yet) | 2-3 | ✅ DONE |
| C.2 | Read papers: Muesli (Hessel), SF literature, multi-timescale RNN | 2-3 | TODO |
| C.3 | Design VFE loss: new `metta/rl/loss/vfe.py` following DiffHorde pattern | 3-4 | TODO |
| C.4 | Epistemic value loss: replace `κ·||ψ-ψ'||²` with `D_KL[q(s|o,π) \|\| q(s|π)]` | 3-4 | TODO |
| C.5 | Explore Cortex Fabric as AIF substrate (blocked: `fabric.py` doesn't exist yet) | 4-6 | BLOCKED |
| C.6 | Compare: PPO-only vs AIF-recipe vs VFE-augmented PPO | 3-4 | TODO |

The deepest version of Track C: the fabric IS an AIF agent — its message passing IS belief propagation, its multi-timescale IS a hierarchical generative model, its SF IS epistemic value. We're not adding AIF on top — we're revealing that the substrate already implements AIF, and providing the formal framework to optimize it as such.

#### Standalone Tracks (Unchanged)

| Track | What | Status |
|-------|------|--------|
| **S7a** | AIF standalone agent (tournament submissions) | 10.43 j/agent, `aif-r2-jit-v3:v1` |
| **S7b** | Meta-learning over world models (paper with Luca/Alejandro) | POMDP done (288-state), Luca leading MAML |

### Research Narrative (Revised)

The narrative shifts from "AIF vs PPO" to "AIF enriching the cognitive substrate":

1. **Track A (PPO recipe)** = "We understand the benchmark" (engineering baseline)
   - Proper training at metta scale with their components
   - Transport encoding finally enables economy chain
   - Expected: first real PPO junction scores

2. **Track B (AIF recipe)** = "Principled option selection outperforms heuristic controllers" (empirical contribution)
   - Our 10.43 j/agent already beats scripted dinky
   - Recipe format enables direct comparison with PPO and cognitive substrate
   - Proves EFE-based exploration solves the navigation/coordination bottleneck

3. **Track C (VFE loss)** = "AIF provides what the cognitive substrate is missing" (theoretical contribution)
   - SF tells you "something surprising is there" — AIF tells you *why* and *what to do about it*
   - VFE gives a principled derivation of the prediction loss (reactive memory layer)
   - Epistemic value formalizes what SF approximates heuristically
   - Hierarchical generative model gives semantic content to multi-timescale RNN layers
   - Cortex Fabric message passing ≈ AIF belief propagation between agents

### Approach Details

#### B2': Cortex Architecture (REPLACES B2)

**Effort**: 4-6 hours (systematic exploration) | **Expected improvement**: +2-5 points over CNN+LSTM

Metta-AI's hybrid RNN: 9 cell types available. Using `scripts/sweep/run_sweep_v19.sh` for parallel 4-GPU exploration.

**Public package**: `pip install cortexcore` (imports as `cortex`). Source: https://github.com/Metta-AI/cortex

**Architecture details** (from code exploration):
- **Input**: `[B, T, d_hidden]` — unified signature across all layers
- **Pattern system**: `"Ag,A,S"` parsed by greedy token regex → builds ColumnBlock with 3 expert blocks
- **Integration in metta**: ObsShim → ObsAttrEmbedFourier → ObsPerceiverLatent → CortexTD → MLP heads
- **For our setup**: Need adapter between CNN token-to-grid output and Cortex input (or replace CNN entirely with Cortex's perceiver pathway)
- **Config example**: `build_cortex_auto_config(d_hidden=64, num_layers=2, pattern="Ag,A,S")`
- **State management**: TensorDict-based, handles episode resets automatically via `resets` mask

**Systematic v0.19 Exploration (2026-03-28)**:

Previous experiments (S13-S28) on 0.18 were incomplete — 5 cell types never tested, hyperparams not re-tuned for 0.19. cogames 0.19 changed ent_coef (0.05→0.01), bptt_horizon (128→64), gamma (0.999→0.995), and more.

Available cell types:

| Token | Cell | Status | Notes |
|-------|------|--------|-------|
| L | LSTM | Tested (3.75j on 0.18) | Best so far |
| A | Axon (RTRL) | Tested (2.25j) | Linear SSM |
| Ag | AGaLiTe | Only in combo | Never tested solo |
| S | sLSTM | Only in combo | Never tested solo |
| M | mLSTM | **Never tested** | Multiplicative LSTM |
| X | XL | **Never tested** | Extended recurrent |
| C | CausalConv1d | **Never tested** | No true recurrence |
| S^ | sLSTM axonified | **Never tested** | sLSTM + RTRL |
| M^ | mLSTM axonified | **Never tested** | mLSTM + RTRL |

5-phase plan: (A) baseline calibration with 0.18 hp restoration, (B) single-cell sweep, (C) pairwise combinations, (D) hyperparam optimization, (E) scaling + kickstarting. ~4-5 hours total on 4x L4.

See EXPERIMENT_LOG.md "Cortex v0.19 Systematic Exploration" for full results.

#### Cortex Fabric Integration (Replaces IC3Net)

**Effort**: 4-6 hours (Track C.3) | **Expected improvement**: principled multi-agent communication

IC3Net/TarMAC are superseded by Cortex Fabric (Emmett's project):
- Lattice of RNN cells connected via message passing (brain-like topology)
- Each cell has latent state, communicates with neighbors
- Scales better than transformers (linear vs quadratic)
- Structurally similar to AIF belief propagation between agents

**Integration path**: Implement G-coupling as message content within Fabric connections. Each agent's cortex node communicates beliefs (posterior marginals) via fabric message passing. This is more natural than bolting IC3Net onto an existing policy — it's native to the architecture.

#### AIF Tracks Summary

| Track | Status | Next |
|-------|--------|------|
| **S7a** (standalone agent) | 10.43 j/agent, tournament bundle validated | Stays as reference; port to recipe (Track B) |
| **S7b** (meta-learning) | 288-state POMDP done, Luca leading MAML | Paper track, independent of pipeline migration |
| **Track B** (AIF recipe) | Not started | Port S7a into metta recipe format |
| **Track C** (VFE loss) | Not started | Research frontier — AIF × cognitive substrate |

**Full design document**: See [AIF_DESIGN.md](AIF_DESIGN.md) for complete architecture (288-state POMDP, VFE/EFE math, G-coupling, ToM, 5 approaches A-E, implementation path, and references).

### Revised Execution Timeline

**Phase I — External experiments (COMPLETE)**

| Step | What | Hours | Status | Notes |
|------|------|-------|--------|-------|
| **S0** | Complete Phase 2a/2b sweeps | 3 | ✅ Done | 18 A3 experiments, 3 machina_1 experiments |
| **S1** | A1.5: Individual role training | 3.4 | ✅ Done | Aligner 12.1 junctions, scrambler 15.9 hearts |
| **S2** | Get meta repo access, study Cortex + kickstarting | 4 | ✅ Done | metta repo access granted, cortex explored |
| **S3** | A5: Kickstarting (scripted RoleTeacher on machina_1) | 8 | ✅ Done | Path B: first economy chain, gear acquisition working |
| **S3b** | Scout reward debugging + clean PPO | 4 | ✅ Done | v8 works (6.5x random), scout deprioritized per PI |
| **S4** | Submit kickstarted policies to leaderboard | 1 | ✅ Done | 3 kickstarted + 1 flat PPO submitted |
| **S4b** | Meta-learning data collection + POMDP module | 4 | ✅ Done | 3,600 episodes (v3), discrete POMDP in aif-meta-cogames |
| **S5** | B2': Train with Cortex architecture | 4-6 | ✅ Done | sLSTM = 5.0j peak (0.19 winner). 50+ experiments. See EXPERIMENT_LOG.md |
| **S5b** | R17-R22: Metta pipeline + entropy + kickstarting | 12 | ✅ Done | Adopted metta hparams, KL KS, entropy collapse prevention. All 0 junctions due to vibe bug. |
| **S5c** | R23: Fix teacher + encoder + tok.location | 4 | ✅ Done | 3 bugs fixed. Still 0 junctions → discovered TRUE root cause. |
| **S5d** | R24: Enable vibe actions (TRUE root cause fix) | 6 | ✅ **Done** | Phase 1: aligned.junction=1.5 at 50M steps. First real PPO junctions ever. |
| **S7a** | F1: AIF standalone agent | 12 | **Complete** | 10.43j mean. Tournament bundle `aif-r2-jit-v3:v1`. Phase 3d upgrades. |
| **S7b** | H1: Meta-learning over world models | 4-6 | **POMDP done** | Paper with Luca/Alejandro. Luca leading MAML. |
| | **Subtotal Phase I** | ~52 done | | |

**Phase II — Metta pipeline migration (NEW — starts after R24 Phase 1)**

| Step | Track | What | Hours | Status | Notes |
|------|-------|------|-------|--------|-------|
| **M1** | — | Metta cluster onboarding (Nishad) | 1-2 | IN PROGRESS | Have AWS 4xL4. Need metta cluster for scale. |
| **M2** | — | Study recipe structure (TrainTool, LossConfig, component list) | 3-4 | ✅ DONE | Deep analysis: 24 loss files, 20 policies, 21 components, 6-layer training pipeline, 5 recipe variants |
| **M3** | A | PPO recipe: adaptive entropy + kickstarter + PR | 4-6 | ✅ DONE | `cogsguard_aif_team.py` + `adaptive_entropy.py`. PR #11757 (review: P1 checkpoint + P2 DDP sync — both fixed). |
| **M4** | A | Train PPO at scale (cinky 8,639 converged, PazBot active) | 8-12 | IN PROGRESS | 500M cinky = **8,639 j/held** (eval: 6,926). PazBot-v47 vibe teacher at epoch 29 = **1,218 j/held** (+72/epoch). Testing vibe ceiling hypothesis. |
| **M5** | B | AIF recipe: port pymdp agent into recipe format | 4-6 | TODO | 288-state POMDP + scripted executors |
| **M6** | B | Validate AIF recipe reproduces standalone results | 2-3 | TODO | Target: 10+ j/agent |
| **M7** | B | AIF on CLIPs variant (PI request) | 3-4 | TODO | May need DEFEND/EVADE options |
| **M8** | C | Read cognitive substrate papers (Muesli, SF, multi-timescale) | 2-3 | TODO | Background for VFE loss design |
| **M9** | C | Design + implement VFE loss within LossConfig | 4-6 | TODO | `L = L_ppo + α·L_vfe` |
| **M10** | C | Cortex Fabric + AIF belief propagation exploration | 4-6 | TODO | G-coupling via fabric message passing |
| **M11** | — | Compare: PPO-only vs AIF-recipe vs VFE-augmented PPO | 3-4 | TODO | Core comparison for report |
| **M12** | — | Research report + presentation | 5-8 | TODO | |
| **P** | — | Monday standup presentation | 2-3 | TODO | First impression with internal team |
| | | **Subtotal Phase II** | ~42-55 | | |
| | | **Grand total** | ~94-107 | | Contract: 80 hrs |

**Note**: Phase II hours exceed contract. Prioritize M1-M6 + P (core deliverables, ~25 hrs). M7-M10 are stretch goals. M11-M12 are final report.

### What Each Track Teaches Us

| If this works... | It tells us... | Next step... |
|-----------------|----------------|--------------|
| R24 Phase 1 (fixed vibes) | Vibes were the TRUE root cause | Validates all 3 tracks |
| Track A (PPO recipe) | Proper PPO at metta scale produces real junctions | Baseline for B and C comparison |
| Track B (AIF recipe) | Principled option selection works in their infrastructure | Direct comparison with PPO and cognitive substrate |
| Track C (VFE loss) | AIF principles can augment neural RL training | Strongest research contribution — the bridge story |
| Cortex Fabric + AIF | Belief propagation works via message passing | Natural substrate for G-coupling at scale |

---

## Phase 5: Evaluation & Report — PENDING

**Status**: Pending. Blocked on recipe migration results (Track A/B/C). Leaderboard submissions made (flat PPO + 3 kickstarted roles + AIF `aif-r2-jit-v3:v1`).

- [x] Submit policies to leaderboard (flat PPO, kickstarted aligner/miner/scrambler, AIF)
- [ ] Compare: PPO-only recipe vs AIF recipe vs VFE-augmented PPO (M11)
- [ ] Document: three-track architecture, recipe implementation, cognitive substrate bridge
- [ ] Prepare final presentation for Softmax team (M12)
- [ ] Twice-weekly standup presentations (ongoing from M→P9)

---

For the full AIF architecture map (social-layer -> CogsGuard component mapping), comparison framework (PPO vs Learned Comm vs AIF), and previous research plan history, see [AIF_DESIGN.md](AIF_DESIGN.md).

---

## Meta-Learning × AIF: Implementation Priority (UPDATED 2026-04-16)

| Priority | Approach | Status | Effort | Prerequisite |
|----------|----------|--------|--------|-------------|
| 1st | **Track B: AIF recipe** | Port standalone to metta recipe | 6-9 hrs | M1/M2 (onboarding) |
| 2nd | **Track C: VFE loss (= H3)** | Design VFE as LossConfig | 4-6 hrs | M2 (recipe structure) |
| 3rd | **H1: Hierarchical AIF** | POMDP module complete. Luca leading MAML. | 4-6 hrs | Paper track (independent) |
| 4th | **Cortex Fabric + AIF** | G-coupling via message passing | 4-6 hrs | Track C + Fabric access |
| 5th | **H5: Active task selection** | Not started | 8-10 hrs | Working AIF recipe |

**Note**: H3 (Neural AIF / VFE loss) is now Track C — promoted from 5th to 2nd priority because Subhojeet explicitly asked for it and it bridges with the cognitive substrate.

### AIF Parameter Learning Pipeline (UPDATED 2026-04-01)

**Current state**: Full differentiable parameter learning pipeline implemented in `aif-meta-cogames` repo. 6 learning approaches (B-I through B-VI), 217 tests passing. Best live eval: B5 = 2.20 j/agent (+47% over hand-tuned).

**Completed:**
- ✅ A matrix learning — VFE gradient descent, multi-agent averaging (B-I)
- ✅ B matrix learning — Transition prediction loss, factored B contraction (B-II)
- ✅ C vector learning — Inverse EFE behavioral cloning, per-role C (Shin et al. 2022) (B-III)
- ✅ Joint A+B+C — Two-timescale optimization, separate Adam optimizers (B-IV)
- ✅ De novo learning — Dirichlet accumulation + BMR (Friston 2025) (B-V)
- ✅ Differentiable BMR — Gradient-norm pruning + model comparison (B-VI)
- ✅ Online A-learning — Dirichlet updates during live play (B7)
- ✅ A matrix sharpening, C preference tuning, gamma=8.0, policy_len=2

**Pending — AWS eval of new approaches:**

| Priority | Method | Script | Status |
|----------|--------|--------|--------|
| 1st | **Joint A+B+C** | `learn_parameters.py learn-full` | Implemented, needs trajectory + eval |
| 2nd | **De novo learning** | `denovo_learn.py learn` | Implemented, needs trajectory + eval |
| 3rd | **Differentiable BMR** | `differentiable_bmr.py prune` | Implemented, needs trajectory + eval |
| 4th | **Model comparison** | `differentiable_bmr.py compare` | Compare all approaches head-to-head |
| 5th | **MAML meta-learning (H1)** | Luca leading | Research paper — variant-agnostic world model |

#### Implementation Details

All learning scripts are in the `aif-meta-cogames` repo under `scripts/`:
- `learn_parameters.py` — A+B VFE gradient, C inverse EFE, joint A+B+C (`learn`, `learn-c`, `learn-full` subcommands)
- `denovo_learn.py` — Dirichlet accumulation + BMR (`learn` subcommand)
- `differentiable_bmr.py` — Gradient-norm pruning, de novo init refinement, model comparison (`prune`, `refine`, `compare` subcommands)

Key technical choices:
- **B uses option-level actions** (5 macro-options) not task-level (13) — matches trajectory data
- **B_role is frozen** (identity matrix — roles never change)
- **C learning uses inverse EFE** (Shin et al. 2022): `Loss = -ln q_pi(observed_option)` where `q_pi = softmax(gamma * neg_G + ln E)`
- **Per-role C**: miner, aligner, scout C vectors learned independently
- **Two-timescale**: A/B at base LR, C at 0.1x LR (scale sensitivity through softmax)

### Open Research Questions (from Luca/Alejandro discussion, 2026-03-17)

- **Luca's focus**: MAML/in-context learning over A/B matrices — confirmed data v3 looks good
- **Alejandro**: volunteered to help with Phase 1 POMDP (now complete)
- **Venue targeting**: Active Inference Workshop (conceptual clarity) vs NeurIPS (empirical + architectural novelty)
- **Synergy with Luca's projects**: Dreamer self/other distinction, LSA layer-wise energy minimisation, test-time OOD adaptation
- **Task family richness**: 36 CogsGuard variants (30 arena + 6 machina_1) with 3,600 episodes of trajectory data ready

### PI Meeting Notes (2026-04-01) — AIF Options & Training Insights

#### Meeting Context

Call with Subhojeet. Presented AIF option-selection results (2.20 j/agent), deep AIF architecture (288-state, two nested POMDPs, 5 macro-options), parameter learning pipeline, R13 sweep results, and leaderboard submission status.

#### R13 Results Presented

All 4 bug-fixed experiments (M1-M4) produced ~1.5-2.0 mean junctions at 50M steps — matching H4 baseline. PPO improvement approaches exhausted at this training budget.

#### Key Takeaways

**0. Submissions ALL failed — version 0.22 required**

Our 4 leaderboard submissions all failed. Season beta-cvc requires cogames compat 0.22, but we're on 0.19.2. Plus missing dependency in ship bundle. **BLOCKING — nothing else matters if we can't submit.**

**Action**: Upgrade to `pip install cogames==0.22.2`, re-test all training scripts, fix ship bundle.

**0b. 50M steps is "quite small" — they train for billions**

Subhojeet's internal kickstarting schedule: 8 agents, 4 miner teachers + 4 aligner teachers, KL=1.0 constant for first 4B steps, anneal 1.0→0 over 4B-8B steps, pure PPO after 8B steps. Agents reach ~60% teacher replication before transition. Our 50M runs are 100-200x shorter.

**Action**: Extended training (500M→1B steps) on machina_1 with best config. ~5 hours per run on L4.

**1. Map size is a major bottleneck for all approaches**

"Because the map is so large, it takes them a lot of time to really go to different parts of the map... not enough with pure PPO for it to navigate that a bit."

**Action**: Try shrinking the map to validate both RL and AIF agents work, then scale up. If a smaller map yields dramatically better results → bottleneck is navigation/exploration, not planning. This applies to both PPO (Cortex) and AIF experiments.

**2. 100M steps is too short — Softmax uses billions**

Their internal kickstarting schedule: KL=1.0 for first 4B steps, anneal 4B-8B steps, pure PPO after 10B steps. At anneal end, agents replicate ~60% of scripted teacher behavior. Then PPO improves further but eventually saturates ("exploration is still a bottleneck even with good initialized policy").

**Implication for us**: Our 50M step runs are 100-200x shorter than their internal training. The 4.0j ceiling may partly be a compute budget issue, not an architectural one.

**3. Option discovery vs option selection (AIF-specific)**

PI explicitly distinguished these: "There is an option discovery problem, and then there is the option selection problem. Right now, you're fixing on the set of options and focusing on the option selection problem. But how did you decide the set of options?"

Our 5 macro-options come from dinky's scripted behaviors. Future work: discover options from data (spectral clustering on action sequences, or learn sub-policies).

**4. Options are scripted, not learned**

"The individual options such as scripted policies, they are not really learned." The AIF agent uses scripted option executors (OptionExecutor state machines). Learning the low-level policies within each option could improve performance.

**5. Test AIF on CLIPs variant**

"Apply the same framework in the CLIPs variant as well. We have successful policies in the leaderboard. Find the candidate options and learn the active inference approach over that and maybe try to get better."

**Action**: After validating on no_clips, test AIF option selection on CLIPs where coordination under enemy pressure matters more. May need DEFEND/EVADE macro-options.

**6. Positive on AIF for exploration**

"This approach definitely has a lot more chance because it directly attacks the exploration problem that we have been facing. And this is a good validation that if we have a learned policy over [options] then we are actually seeing new results. Maybe that is better than using a scripted agent which is just using some heuristic to define the meta-level controller."

**7. New RL algorithms in works internally**

Softmax has "moved on from doing pure PPO to having completely new RL algorithms... improved exploration with intrinsic rewards... new neural networks." Details forthcoming. Potential collaboration/comparison opportunity.

**8. Submission debugging**

Policies uploaded to platform but failing — missing dependency in ship bundle. Need to verify `cogames ship` includes all AIF code files.

**9. Game may be evolving**

"I think the game is broken, to be honest... people are working on fixing the game favorably also." Results and benchmarks may shift as game mechanics are updated.

#### Available Maps for Validation

| Map | Size | Agents | Full mechanics? | Notes |
|-----|------|--------|-----------------|-------|
| `easy_hearts_training` | 13×13 | 1–4 | Partial | Hearts + energy only, no clips |
| `tutorial` / `tutorial.aligner` | 35×35 | 1–4 | Yes (minus clips) | Best for fast AIF validation |
| `arena` | 50×50 | 1–20 | Yes | Current main map |
| `machina_1` | 88×88 | 10 | Yes | Tournament standard |

Custom sizes: `cogames make-mission --width W --height H`. Variant `-v small_50` shrinks machina_1 to 50×50.

### PI Meeting Notes (2026-04-16) — Internal Pipeline Onboarding & Cognitive Substrate

#### Meeting Context

Call with Subhojeet. Discussed PPO struggles (0 junctions, teacher not scoring), AIF progress (288-state POMDP, 74% VFE reduction, peak 29j), leaderboard submission status (`aif-r2-jit-v3:v1`). Reviewed replay viewer. Major shift: being brought inside the internal team infrastructure.

#### Key Takeaways

**1. Added to internal training standups**

Starting next week, presenting experiments and results at internal training standups. Happens twice a week. Purpose: remote team sync, knowledge sharing, not just successes. First presentation could be Monday.

**2. Onboarding to metta internal training pipeline**

Subhojeet wants us to use their internal tools instead of external monkey-patching. Nishad handles cluster access/onboarding.

- **Recipes**: Single-file declarations (e.g., `cogsguard.py`) defining env config, algorithm, loss functions, training setup
  - `train()` function returns a `TrainTool` (algorithm + env config)
  - Built-in teacher training support (pass scripted teacher as argument)
  - Built-in reward variant configuration
- **Policy definition**: Component list config structure
  - `ObsStreamTokensConfig` → `FeatureExtractorConfig` → Cortex layers → output heads
  - Follows metta-style list-of-config pattern
- **Loss configs**: Inherit base class, override `get_experience_batch`, implement custom losses
- **Goal**: Create own recipe — potentially an AIF loss function integrated into their pipeline
  - "Can you create a loss function which implements active inference?"
  - Implement VFE as a loss within their recipe framework

**3. General Agent Substrate (formal spec: `General Cognitive Substrate_v0.pdf`)**

Cooperative multi-agent recurrent substrate. Each agent is a multiscale recurrent cortex with K internal "thinking steps" per environment step. Two-part architecture:

**Architecture:**
- **Shared lower cortex** (layers 1..L_s): Common representation, shared across all objectives
- **Route-specialized upper cortex** (layers L_s+1..L): Three routes R = {RL, WM, SF}
  - **RL route**: task action + vibe action + value (dual policy heads with separate entropy regularization)
  - **WM route**: world model — predicts next latent state, reward, and next vibe observation
  - **SF route**: successor features φ + ψ, trained via GTD-style update

**Multi-timescale (key mechanism):**
- Each layer ℓ has update period p_ℓ with p_1 ≤ p_2 ≤ ... ≤ p_L
- Lower layers process longer inner sequences (fast reactivity), upper layers shorter (slow planning)
- `Repeat_U(obs)` for bottom layer, `Stride_s(Y)` for higher layers — no explicit copy equations
- Batched training: pack inner thinking into sequence axis → B × (T·U_ℓ) × d_ℓ

**Communication:**
- Agents emit vibe actions v_t → env transforms to vibe observations o_{t+1,vibe} for other agents
- Communication budget: `r_tot = r_ext + r_int - β_comm · ||v_t||²`
- β_comm > 0 forces communication to justify itself by improving reward

**Exploration:**
- Intrinsic reward from SF prediction error: `r_int = κ · ||ψ_{t+Δ} - ψ_t||²`
- Total loss: `L = L_RL + λ_wm · L_wm + λ_sfr · L_sf-r` (+ optional route-consistency L_cons)

**Losses (maps to metta/rl/loss/):**
- `L_RL`: PPO actor-critic with separate α_a (task entropy) and α_v (vibe entropy) regularization
- `L_wm`: `λ_y ||ŷ - y||² + λ_r ℓ_r(r̂, r) + λ_v ||ô_vibe - o_vibe||²`
- `L_sf-r`: `Σ ||r̂_sf - r||²` (SF reward prediction)
- SF TD residual: `δ_sf = φ_t + γ·ψ_{t+1} - ψ_t` (GTD-style, separate from scalar loss)

**4. Cortex Fabric (formal spec: `Cortex Fabric_v0.pdf`)**

Layerless digital cortical tissue — the more radical variant that replaces the layered stack entirely.

**Key design:**
- No layers. Computation unfolds through K inner thinking steps over a spatial fabric
- Dynamic cells (V_dyn) + static input ports (V_in) + static output ports (V_out) on a D-dimensional toroidal lattice
- Each cell has private recurrent state S + public interface Z (smaller learned projection P_i)
- Input ports clamp encoded observations; output ports read from tissue regions (no separate head stack)
- Output ports for: task action, vibe action, value, world model, successor features — placed at different tissue regions

**Message passing:**
- Masked local attention: each cell attends only to patch neighborhood N_patch(i) + explicit wiring N_wire(i)
- Attention: `α = softmax(q_c^T K / √d_k + M)` where M is -∞ for disallowed senders
- Fabric message: `X^(k) = Σ α · V^(k-1)` — only input consumed by dynamic cells
- Cost scales linearly with active edges, not quadratically with cells

**Multi-speed regions:**
- Cell-dependent clocks: period p_i, gate `g_{i,k} = 1[p_i | k]`
- Cells with different periods evolve at different effective speeds within the same fabric
- No layer boundary required for timescale separation

**Execution:**
- Sequential over thinking steps k, parallel over (batch × rollout × cells) at each k
- B and T are batch axes, NOT communication axes — no cross-batch mixing

**Fabric vs Stacked (key distinction):**
- Stacked: inner sequence packed into B × T' × H layer call (standard RNN kernel)
- Fabric: explicit loop over k, but each step is a large batched operation over B × T × |V|

**5. Pointed questions about our PPO architecture**

Subhojeet walked through our option-level PPO to understand the ML challenge:
- Our action space: option-level (mine_cycle, craft_cycle, capture_cycle)
- Subroutines: scripted low-level policies from dinky (pathfinding to extractor, execute mine, check inventory)
- His key question: "What is the ML challenge here? What extra information does dinky have?"
- Our answer: dinky has a hand-designed world model baked in (inventory thresholds, resource locations, conditional logic)
- His conclusion: **exploration + world model** is the core challenge — which both cognitive substrate and AIF address

**6. Policy replay viewer**

- Observatory has match replay viewer (download + fast-forward)
- Policy URL from observatory can be used as teacher for kickstarting
- Some UI bugs in filtering by policy

#### Action Items

- [ ] **Get onboarded to metta cluster** (contact Nishad for access) → enables Track A + B + C
- [x] **Read recipe + loss + policy code** — ✅ DONE (2026-04-17). Deep analysis from local clone at `C:\Users\mahau\OneDrive\Desktop\projects\metta\`:
  - `recipes/experiment/cogsguard.py` (1108 lines, 32 functions) + 4 variants (`_fap`, `_coggerbro`, `_marlbro`, `coggernaut`)
  - `metta/rl/loss/` — 24 loss files. Key: `loss.py` (base), `ppo_actor.py`, `ppo_critic.py` (GTD-lambda), `kickstarter.py`, `diff_horde.py` (GVF). **No `cognitive_substrate/` directory.**
  - `agent/src/metta/agent/policies/` — 20 policies, 21 components. Key: `default.py` (BoxCNN+CortexTD), `cortex.py` (CortexStack wrapper). **No `fabric.py` or `cognitive_substrate.py`.**
  - Training pipeline: recipe → TrainTool → Trainer → CoreTrainingLoop → TrajectoryIsolation → LossScheduler (6 layers)
  - Teacher: 8 modes = {scripted,learned} × {supervisor,kickstarter,eer_kickstarter,eer_cloner} × {mixed,sliced}
- [ ] **Run existing `cogsguard.py` recipe** on cluster as-is → Track A baseline (blocked on P10)
- [ ] **Create AIF recipe**: Port pymdp agent as custom Policy subclass → Track B (M5)
- [ ] **Design VFE loss**: New `LossConfig` subclass following DiffHorde pattern (greenfield — `cognitive_substrate/` doesn't exist) → Track C (M9)
- [ ] **Present at Monday standup**: R24 root cause, AIF results, three-track recipe plan → P9
- [x] **Read loss + policy code** — ✅ DONE (2026-04-17). `cognitive_substrate/` losses and `fabric.py`/`cognitive_substrate.py` policies DO NOT EXIST yet. Read formal specs (`General Cognitive Substrate_v0.pdf`, `Cortex Fabric_v0.pdf`) and all existing loss/policy code instead. Key pattern: follow `DiffHordeLoss` for VFE implementation.
- [ ] **Explore Cortex Fabric as AIF substrate** — BLOCKED: `fabric.py` doesn't exist yet. Formal spec mapping (Z=messages, S=beliefs, masked attention=BP) documented but can't implement until Emmett's code lands → M10/C.5

#### Implications for Our Work

1. **Three-track pipeline migration**: Not just AIF-as-loss — ALL training (PPO and AIF) moves into metta recipes. Track A (PPO recipe) gives us proper training at scale. Track B (AIF recipe) ports our best agent into their infrastructure. Track C (VFE loss) is the research frontier.

2. **Cognitive substrate ↔ AIF formal mapping** (from spec documents):

| Substrate Component | AIF Equivalent | Integration Point |
|---------------------|----------------|-------------------|
| Shared lower cortex (layers 1..L_s) | Generative model (observation encoding) | A matrix likelihood mapping |
| WM route (predicts next state + reward) | Generative model (B matrix transitions) | VFE loss augments L_wm |
| SF intrinsic reward `κ·\|ψ_{t+Δ} - ψ_t\|²` | Epistemic value (EFE ambiguity term) | AIF provides formal derivation |
| Multi-timescale periods p_ℓ | Hierarchical generative model levels | AIF gives semantic content to each timescale |
| Vibe actions → vibe observations | G-coupling (belief communication) | EFE-based comm replaces β_comm heuristic |
| Route-consistency L_cons | Free energy between models | VFE naturally regularizes drift |
| Dual entropy (α_a task, α_v vibe) | Separate precision for action vs comm | Precision = inverse expected free energy |

The formal specs reveal deeper connections than the meeting suggested:
- **β_comm (communication budget)** is a heuristic — AIF's EFE naturally derives when communication reduces expected free energy, replacing the hand-tuned penalty
- **SF TD residual** `δ_sf = φ + γψ_{t+1} - ψ_t` parallels AIF's **expected information gain** `D_KL[q(s|π) || q(s)]` — both measure "how much does acting change my beliefs about the future"
- **The fabric's message passing** (masked local attention with public interface Z, private state S) is structurally identical to **belief propagation** in factor graphs — Z ≈ messages, S ≈ marginal beliefs

3. **Cortex Fabric ≈ AIF factor graph**: The fabric formalism (toroidal lattice, local masked attention, public/private split) maps directly onto factor graph belief propagation. Each dynamic cell is a factor node with private beliefs (S) and public messages (Z). This is the most natural substrate for implementing AIF — not as a separate loss, but as the *interpretation* of what the fabric is already doing.

4. **Scale unlocked**: Metta cluster access means training at billions of steps (their internal schedule is 4-8B). Our 4xL4 AWS box becomes a dev/debug environment, not the training platform.

---

#### Actionable Items (Priority Order — Updated 2026-04-16)

**Done (Phase I):**
- [x] **P1: Upgrade cogames to 0.22** — ✅ Done (0.22.2)
- [x] **P2: Fix submission bundle** — ✅ Done (AIF `aif-r2-jit-v3:v1` validated in Docker)
- [x] **P3: Train on machina_1** — ✅ Done (R17-R22, sLSTM on machina_1)
- [x] **P4: Extended training** — ✅ Done (R20-R22, 500M-2B steps)
- [x] **P5: Fix teacher (R23)** — ✅ Fixed 3 bugs: scripted_teacher.py IDs, dead encoder, tok.location
- [x] **P6: Fix vibe actions (R24)** — ✅ TRUE ROOT CAUSE found and fixed. Transport encoding implemented.
- [x] **P7: Deploy R24 on AWS** — ✅ Phase 1 complete (V0_fixed_vibes, 50M steps, 1h12m)
- [x] **P8: Check R24 Phase 1 results** — ✅ **aligned.junction = 1.5** — vibes confirmed as TRUE root cause

**Immediate (this week):**
- [ ] **P9: Monday standup presentation** — R24 root cause, AIF results, recipe migration plan
- [ ] **P10: Metta cluster onboarding** — Contact Nishad, get cluster access

**Track A (PPO recipe):**
- [x] **P11: Study recipe structure** — ✅ DONE (2026-04-17). Deep analysis of entire repo: loss system (24 files), policy system (20 policies, 21 components), training pipeline (6-layer stack), all 5 cogsguard recipe variants. Fork pattern identified: import `_cg_train` from base recipe, override params post-construction (same as `cogsguard_fap.py`).
- [ ] **P12: Create PPO recipe** — `recipes/experiment/cogsguard_aif_team.py`: fork base recipe, override `ent_coef=0.08`, `weight_decay=0.1`, add `AdaptiveEntropyLoss` (custom `LossConfig` subclass). **IN PROGRESS**.
- [ ] **P13: Train PPO at metta scale** — 1B+ steps on cluster. Blocked on P10 (cluster access).

**Track B (AIF recipe):**
- [ ] **P14: Create AIF recipe** — `agent/src/metta/agent/policies/aif_policy.py`: wrap `BatchedAIFEngine` as custom `Policy` subclass (Pattern B). Main challenge: obs adapter (`aif_discretizer.py`) for metta's `(N_tokens, 3)` obs format. Recipe at `recipes/experiment/cogsguard_aif.py`.
- [ ] **P15: Validate AIF recipe** — Reproduce 10+ j/agent in metta infrastructure
- [ ] **P16: AIF on CLIPs variant** — Test option-selection under adversarial pressure

**Track C (VFE loss — research frontier):**
- [ ] **P17: Read cognitive substrate papers** — Muesli, Smith-Hubert, Hierarchical Reasoning Models. NOTE: cognitive_substrate/ code doesn't exist yet — only formal specs.
- [ ] **P18: Design VFE loss** — `metta/rl/loss/vfe.py`: follow `DiffHordeLoss` pattern (GTD-style two-head, `register_state_attr` for EMA baselines, `run_rollout_postprocess` + `run_train`). VFE = KL[q(s|o) || p(s)] - ln p(o|s). Auxiliary loss added to PPO via `trainer_cfg.losses.add_loss("vfe", VFELossConfig(...))`.
- [ ] **P19: Cortex Fabric + AIF** — Blocked: `fabric.py` policy doesn't exist yet. Explore belief propagation concept once Emmett's implementation lands.

**Final:**
- [ ] **P20: Compare PPO-only vs AIF-recipe vs VFE-augmented** — Core result for report
- [ ] **P21: Research report + final presentation**

---

### R23: Fix PPO Training Pipeline (2026-04-13, COMPLETE)

**Context**: R17-R22 produced 0 junctions despite high reward signals. Investigation revealed 3 compounding bugs.

**Bugs found and fixed:**

1. **scripted_teacher.py had 0.18 IDs in 0.22.2 env**: TAG_FEAT, TAG_*, INV_* constants were all wrong for the new version. 100% noop actions → poisoned KL kickstarting. Fixed by updating all constants for 0.22.2.

2. **Dead encoder**: ReLU death spiral from poisoned teacher + ent_coef + wd=0.3. Fixed by changing `ReLU → LeakyReLU(0.01)` in all 3 encoders in `cortex_policy.py`.

3. **tok.location bug**: Blocked `cogsguard_targeted` and other scripted agents from resolving entities. Fixed via `apply_tok_location_fix.sh` patching utils.py + cogsguard/policy.py.

**Result**: Teacher confirmed working (0% noop), encoder healthy, but **still 0 junctions**. This led to R24's discovery.

### R24: Enable Vibe Actions — TRUE Root Cause (2026-04-16, IMPLEMENTED)

**The real reason ALL R1-R23 scored 0 junctions:**

Policy outputs `Discrete(5)` = movement only `{noop, N, S, W, E}`. In `MettaGridPufferEnv.step()`, when no supervisor is set up, `vibe_actions.fill(0)` → default vibe. **Default-vibe agents CANNOT mine, craft, or align** — they can only move. The 8.0j peak (T3/R20) was a reward signal artifact, not actual junction alignment.

**Transport encoding** (built into cogames, verified on AWS):

```
action < 5  → primary only, vibe_actions.fill(0) (NO vibe change)
action >= 5 → offset = action - 5; primary = offset // 7; vibe = offset % 7
transport = 5 + primary * 7 + vibe_idx
```

Vibes (machina_1/arena/tutorial/four_score): `[default, heart, gear, scrambler, aligner, miner, scout]` (7 vibes). `Discrete(40)` total.

**Implementation (2 phases):**

**Phase 1 — Fixed-vibe injection** (policy stays Discrete(5)):
- `VIBE_ROLES` env var assigns fixed vibe per agent slot
- Monkey-patch in `patch_and_train.py` converts primary actions to transport
- Default: `miner,aligner,miner,aligner,...` (50/50 split)
- Validates vibes produce junctions before expanding action space

**Phase 2 — Learnable vibes** (policy outputs Discrete(40)):
- `VIBE_ACTIONS=1` env var expands action head in `cortex_policy.py`
- Env natively decodes transport actions (no monkey-patch)
- Teacher produces transport-encoded actions for KL kickstarting
- `scripted_teacher.py` updated with `_encode_transport()` and `teacher_logits()`

**Files modified:**
- `scripts/sweep/patch_and_train.py` — Sections 0a (fixed vibe), 0b (learnable vibe), max_entropy fix
- `scripts/policy/cortex_policy.py` — VIBE_ACTIONS=1 action head (both CortexPolicyNet + SeparateACPolicyNet)
- `scripts/policy/scripted_teacher.py` — Transport encoding, miner/aligner transport mode, teacher_logits()
- `scripts/sweep/round24_vibes.sh` — NEW, Phase 1 + Phase 2 experiment launcher

**Experiment plan** (round24_vibes.sh):

| Phase | GPU | ID | Config | Steps |
|-------|-----|----|--------|-------|
| 1 | 0 | V0 | Fixed vibes (50/50 miner/aligner), ent=0.12 | 50M |
| 2 | 0 | V1 | Learnable vibes + KS, ent=0.08 | 500M |
| 2 | 1 | V2 | Learnable vibes, no KS, ent=0.08 | 500M |
| 2 | 2 | V3 | Fixed vibes 50/50, ent=0.08 | 500M |
| 2 | 3 | V4 | Learnable vibes + KS, ent=0.12 | 500M |

**Success criterion**: `junction.aligned > 0` in Phase 1 (proves vibes are the fix). Phase 2 tests whether learned role selection outperforms fixed assignment.

**Phase 1 result (2026-04-17 00:07 UTC):**

| Metric | Value |
|--------|-------|
| `game/cogs/aligned.junction` | **1.500** |
| `game/cogs/heart.withdrawn` | 4.667 |
| `game/cogs/silicon.deposited` | 9.500 |
| `game/cogs/carbon.withdrawn` | 1.500 |
| `entropy` | 1.471 (healthy) |
| `explained_variance` | 0.946 |
| Steps | 50.3M (93 epochs, 1h12m) |
| SPS | 104.1K |

**First PPO junctions in 24 rounds.** Full economy chain confirmed: mine → deposit → withdraw hearts → align junctions. Only 50M steps — longer training on metta cluster (Track A) expected to improve significantly.

**Status**: Phase 1 COMPLETE. Phase 2 (learnable Discrete(40)) deprioritized in favor of recipe migration (Track A).

---

### IIBT: Interactive Inference Behavior Trees (Future Direction)

**Paper**: Wang et al., "Bridging Probabilistic Inference and Behavior Trees" (Drones 2026). Embeds AIF (VFE+EFE) inside BT nodes with cross-agent B matrix blocks and logic-to-preference shaping. 76.2% BT complexity reduction. Highly relevant for future work after current two-POMDP hierarchy is validated. See [AIF_DESIGN.md](AIF_DESIGN.md) for detailed architecture.
