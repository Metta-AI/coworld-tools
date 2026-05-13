## Document: TRAINING_AND_EVALUATION.md

### Purpose

Document everything needed to set up training loops, run evaluations, and
benchmark agent performance. How to run many games in parallel, how to get
deterministic replays, and how to measure progress.

### Scope (this document OWNS)

- Parallelism support (can you run multiple game instances? how?)
- Headless mode (running without rendering/UI)
- Determinism and seeding (can you replay games exactly?)
- Replay/logging infrastructure (recording games for analysis)
- Evaluation metrics and benchmarks (how to measure agent quality)
- Speed/throughput characteristics (games per second, steps per second)
- Configuration for training (batch sizes, environment parameters)
- Self-play setup (if applicable)

### Scope (this document does NOT cover)

- Reward design or shaping (REWARDS_AND_PROGRESS_SIGNALS)
- What observations/actions look like (INTERFACE_CONTRACT)
- Agent architecture recommendations (STRATEGY_AND_POLICY_GUIDE)
- Connection protocol (CONNECTION_AND_EPISODE_LIFECYCLE)

### Guidance

- Focus on practical "how to run" information: commands, configs, environment
  variables
- Document the performance envelope: how many parallel games can run on one
  machine? What's the bottleneck?
- If determinism requires specific settings, document them precisely
- Note any differences between training mode and normal play mode
- Cover logging: what gets logged, where, in what format
- Document any existing evaluation scripts or benchmarks in the source
- If there's infrastructure for opponent pools or leagues, document it

### Dependencies

Read first: INTERFACE_CONTRACT.md (for timing and protocol context)
