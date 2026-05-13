## Document: MEMORY_AND_HIDDEN_INFORMATION.md

### Purpose

Document what the agent cannot see, what it needs to remember, and what it must
infer. This is the partial observability reference — essential for any agent
that needs to track beliefs or maintain state across time steps.

### Scope (this document OWNS)

- Hidden information catalog (what is hidden, from whom, and when)
- Information asymmetry between players
- What must be remembered across time steps (not visible in current observation)
- Belief tracking requirements (what the agent should model/infer)
- Information revelation events (when hidden info becomes visible)
- Deception and signaling (if the game involves bluffing or communication)
- Recurrence/memory architecture requirements (what an agent's memory needs
  to store)

### Scope (this document does NOT cover)

- Raw observation structure (OBSERVATION_DECODING)
- State graph (STATE_AND_VIEW_MODEL — that doc shows all states; this doc
  focuses on what's HIDDEN from the agent's perspective)
- Game rules about hidden mechanics (RULES_AND_MECHANICS)
- How to exploit hidden info strategically (STRATEGY_AND_POLICY_GUIDE)

### Guidance

- Be exhaustive about what's hidden: go through every piece of game state and
  classify it as observable, partially observable, or hidden
- For hidden info: when is it generated, can it be inferred, and when (if ever)
  is it revealed?
- Document the information structure from each player's perspective (especially
  if roles differ)
- Specify what an agent should track in memory across time steps — be concrete
  about data structures
- Note which inferences are tractable vs. combinatorially explosive
- If the game has communication/signaling channels, document what can be
  transmitted and its reliability
- Frame recommendations in terms of memory requirements: "an agent needs to
  remember X to play well because Y"

### Dependencies

Read first: STATE_AND_VIEW_MODEL.md (for the complete state/view model)
