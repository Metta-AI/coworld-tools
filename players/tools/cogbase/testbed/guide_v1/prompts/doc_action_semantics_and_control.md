## Document: ACTION_SEMANTICS_AND_CONTROL.md

### Purpose

Define what each action actually does when executed: its effects on game state,
timing characteristics, legality conditions, and failure modes. This is the
motor control reference — the agent knows WHAT it can send from the interface
contract; this doc explains what HAPPENS when it does.

### Scope (this document OWNS)

- Action catalog (every action with its effect)
- Action preconditions (what must be true for an action to be legal/effective)
- Action effects (what changes in game state when an action executes)
- Action timing (how long actions take, cooldowns, animation locks)
- Action failure modes (what happens when you send an illegal or impossible action)
- Action combinations and sequences (combos, multi-step actions)
- No-op / idle behavior (what happens when the agent sends nothing)

### Scope (this document does NOT cover)

- Action schema/encoding (INTERFACE_CONTRACT — that doc defines WHAT you send;
  this doc explains what it DOES)
- Strategic action selection (STRATEGY_AND_POLICY_GUIDE)
- Game rules that determine legality (RULES_AND_MECHANICS — that doc defines
  the rules; this doc explains the action-level consequences)

### Guidance

- Catalog every action the agent can take, organized by category
- Derive the action catalog from the live player action parser or message
  handler, not from UI labels, keyboard controls, enum names used only inside
  rendering code, or nearby examples.
- Treat raw button labels (`A`, `B`, `ButtonB`) as transport/control constants
  unless the source proves the player can send that exact action id. If `B`
  lowers to another semantic action such as `vent`, document the semantic action
  and the wire encoding separately.
- For each action: preconditions, effects, timing, failure behavior
- Use a consistent format (table or structured list per action)
- Document action priority/conflict resolution (what if two agents act
  simultaneously?)
- Note actions that have delayed or non-obvious effects
- Document the difference between "action rejected" and "action accepted
  but failed" (if that distinction exists)
- Include any action modifiers (e.g., holding vs tapping, direction, target)

### Dependencies

Read first:
- INTERFACE_CONTRACT.md (for action schema)
- STATE_AND_VIEW_MODEL.md (for states where actions apply)
