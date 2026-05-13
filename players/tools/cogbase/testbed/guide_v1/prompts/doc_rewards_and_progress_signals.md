## Document: REWARDS_AND_PROGRESS_SIGNALS.md

### Purpose

Document all reward signals, progress indicators, and evaluation metrics
available to the agent. What feedback does the environment provide, when, and
how can it be used to drive learning?

### Scope (this document OWNS)

- Reward signals (what rewards exist, their values, when they fire)
- Reward sparsity (how often rewards occur, gaps between signals)
- Progress indicators (non-reward signals that indicate the agent is doing well)
- Reward shaping candidates (intermediate signals useful for training)
- Evaluation metrics (how to measure agent performance holistically)
- Score/ranking systems (if the game has scoring)
- Multi-objective considerations (if there are competing rewards)

### Scope (this document does NOT cover)

- How rewards are encoded in observations (INTERFACE_CONTRACT)
- Game rules that determine win/loss (RULES_AND_MECHANICS)
- Training loop setup (TRAINING_AND_EVALUATION)
- Strategic implications (STRATEGY_AND_POLICY_GUIDE)

### Guidance

- List every reward signal in the source: value, trigger condition, frequency
- Characterize reward sparsity honestly — if rewards only come at game end, say so
- Identify potential shaping rewards: intermediate signals that correlate with
  eventual success (even if not explicit reward signals in the code)
- Document the reward timeline: when do different signals arrive relative to
  agent actions?
- If rewards differ by role/team, document each perspective
- Suggest useful evaluation metrics beyond raw win rate (e.g., survival time,
  task completion, cooperation metrics)
- Note any reward hacking risks (ways an agent could maximize reward without
  actually playing well)

### Dependencies

Read first: STATE_AND_VIEW_MODEL.md (for game states where rewards trigger)
