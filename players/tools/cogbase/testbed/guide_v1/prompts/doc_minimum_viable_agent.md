## Document: MINIMUM_VIABLE_AGENT.md

### Purpose

Provide the shortest path from zero to a running agent that connects, receives
observations, takes actions, and completes at least one game episode. Not a
good agent — just a working one. This is the "hello world" for agent development
in this game.

### Scope (this document OWNS)

- MVP agent specification (minimum behavior to complete an episode)
- Step-by-step implementation path (what to build first, second, third)
- Baseline action strategy (random, fixed, or simplest-possible policy)
- Verification checklist (how to confirm the agent is working)
- Common first-time pitfalls and how to avoid them

### Scope (this document does NOT cover)

- Good play or strategy (STRATEGY_AND_POLICY_GUIDE)
- Full interface details (INTERFACE_CONTRACT — reference it, don't repeat)
- Training setup (TRAINING_AND_EVALUATION)
- Error handling beyond basic connection (ERROR_RECOVERY_AND_ROBUSTNESS)

### Guidance

- This document should enable someone to get a working agent in the shortest
  time possible — optimize for speed to first episode completion
- Reference other docs by name but don't duplicate their content ("see
  INTERFACE_CONTRACT for the full observation schema")
- Include a concrete action strategy that's trivially implementable (random
  valid actions, always-idle, or the simplest heuristic)
- Express the implementation path in Cyborg framework terms: minimal percept,
  minimal belief, one default mode, one useful mode if needed, action resolver,
  and a synchronous rule strategy that emits validated mode directives
- Provide a verification sequence: "run X, observe Y, then you know it works"
- List the top 3-5 things that trip up first-time implementers
- If there are setup requirements (dependencies, configuration, environment
  variables), list them explicitly
- The agent doesn't need to be good. It needs to run, connect, take actions,
  and finish a game without crashing.

### Dependencies

Read first: CONNECTION_AND_EPISODE_LIFECYCLE.md (for the connection sequence)
