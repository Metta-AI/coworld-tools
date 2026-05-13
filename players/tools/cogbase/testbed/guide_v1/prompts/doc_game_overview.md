## Document: GAME_OVERVIEW.md

### Purpose

Provide a complete orientation to the game for someone who has never seen it.
After reading this document, the reader should understand what kind of game this
is, what entities exist, what the core loop looks like, and have a working
vocabulary for discussing it.

### Scope (this document OWNS)

- Game classification (genre, player count, real-time vs turn-based, cooperative vs competitive)
- Core game loop (high-level phases of play)
- Entity catalog (players, NPCs, objects, environments — what exists in the game world)
- Vocabulary and terminology (game-specific terms and their definitions)
- Win/loss conditions (stated briefly — detailed rules belong elsewhere)
- Player roles (if the game has asymmetric roles)

### Scope (this document does NOT cover)

- Formal interface contract (INTERFACE_CONTRACT)
- Detailed rules and mechanics (RULES_AND_MECHANICS)
- How to connect or start a game (CONNECTION_AND_EPISODE_LIFECYCLE)
- Implementation details or source architecture (IMPLEMENTATION_NOTES)

### Guidance

- Start with a 2-3 sentence summary that would orient any developer instantly
- Classify the game along useful dimensions (synchronous/async, perfect/imperfect
  information, deterministic/stochastic, etc.)
- List every entity type you can find in the source with a one-line description
- Define a vocabulary section for game-specific terms — these terms will be used
  across all other documents in the suite
- Keep it factual and grounded in source code, not marketing copy
