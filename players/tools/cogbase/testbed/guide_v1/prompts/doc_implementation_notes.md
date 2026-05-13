## Document: IMPLEMENTATION_NOTES.md

### Purpose

Document the game's source code internals: architecture, key files, data flow,
and implementation details useful for debugging or validating agent behavior.
This is explicitly non-contractual — agents should not depend on implementation
details for correctness, but developers will use this for debugging.

### Scope (this document OWNS)

- Source architecture overview (directory structure, module responsibilities)
- Key files and their roles (the 10-20 most important source files)
- Data flow (how game state flows through the codebase)
- Server/client architecture (if applicable)
- Configuration system (what's configurable, where, defaults)
- Extension points (where the code is designed to be modified)
- Known technical debt or quirks
- Build/run instructions (how to build and run the game from source)

### Scope (this document does NOT cover)

- Anything an agent should depend on for correctness (all other docs)
- Game rules (RULES_AND_MECHANICS)
- Interface contract (INTERFACE_CONTRACT)
- Strategy (STRATEGY_AND_POLICY_GUIDE)

### Guidance

- This is a map of the source code for a developer who needs to debug or
  modify the game
- Start with the directory structure and module breakdown
- Identify the key files: where is game logic? Where is networking? Where are
  observations constructed?
- Trace a single game tick through the code: input → processing → output
- Document the config system: what knobs exist and what they do
- Note any anti-patterns, tech debt, or "here be dragons" areas
- This document supports all other documents but is not required reading for
  any of them
- Include build/run commands for development setup

### Dependencies

Read first: All prior documents (for context on what the source is implementing)
