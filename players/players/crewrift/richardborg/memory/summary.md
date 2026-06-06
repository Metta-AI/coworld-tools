Richardborg meeting memory

Goal: make the meeting LLM talk from concrete observations instead of generic suspicion.

During play, the deterministic runtime records what this agent actually saw:
players together, players near bodies, players at vents, players at tasks, and
direct confirmed imposter transitions. At meeting time those observations are
converted into short canonical lines and passed to the LLM as memory.

The LLM should use these lines to explain or question, then vote only when the
target is legal and the evidence is strong enough.
