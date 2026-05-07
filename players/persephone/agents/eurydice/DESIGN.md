# Eurydice -- Design Document

## What is Eurydice?

Eurydice is a rule-based Orpheus agent for Persephone's Escape that plays
all roles competently via role-specific strategy modules. It sits on top of
the Orpheus framework (perception, belief state, pipeline, outer loop) and
adds a strategic reasoning layer that selects modes and tasks based on:

1. **Assigned role** (detected from the role reveal screen)
2. **Game phase** (round number, time remaining)
3. **Accumulated knowledge** (team identities, role identities, room
   assignments, exchange status)
4. **Strategic priorities** (derived from role-specific strategy documents)

Named for the mythological figure who Orpheus followed into the
underworld -- fitting for an agent built on the Orpheus framework that
must navigate the Underworld and Mortal Realm.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────┐
│                  Eurydice Agent                     │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │           Strategic Layer (Outer Loop)        │  │
│  │                                              │  │
│  │  ┌────────────┐  ┌───────────────────────┐   │  │
│  │  │ Role       │  │ Strategy Evaluator    │   │  │
│  │  │ Dispatcher │──│ (role-specific rules) │   │  │
│  │  └────────────┘  └───────────────────────┘   │  │
│  │         │                    │                │  │
│  │         ▼                    ▼                │  │
│  │  ┌────────────────────────────────────────┐  │  │
│  │  │ meta_decide(belief, memory)            │  │  │
│  │  │ -> (ModeDirective, inferences)         │  │  │
│  │  └────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────┘  │
│                        │                           │
│                        │ ModeBuffer                │
│                        ▼                           │
│  ┌──────────────────────────────────────────────┐  │
│  │           Tactical Layer (Inner Loop)        │  │
│  │                                              │  │
│  │  ┌────────┐ ┌────────┐ ┌────────┐           │  │
│  │  │ Modes  │ │ Tasks  │ │ Hooks  │           │  │
│  │  └────────┘ └────────┘ └────────┘           │  │
│  └──────────────────────────────────────────────┘  │
│                        │                           │
│                        ▼                           │
│  ┌──────────────────────────────────────────────┐  │
│  │         Orpheus Framework (Pipeline)         │  │
│  │  Perception → Belief Update → Decide → Act   │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

---

## Strategic Design Principles

### 1. Role-Driven Behavior

The agent's strategy is entirely determined by its assigned role. Each role
has a comprehensive strategy document (see `*_STRATEGY.md` files) that
defines:

- Prioritized objectives
- Phase-by-phase behavior
- Interaction protocols with each type of player
- Risk assessment and mitigation
- Decision heuristics

The `meta_decide` function dispatches to role-specific evaluation logic
after role detection.

### 2. Information-First

Before acting on strategic goals, the agent must build a knowledge base:

- **Team identification:** Color exchange reveals team affiliation
- **Role identification:** Mutual role exchange reveals specific role
- **Room mapping:** Track which players are in which room
- **Exchange tracking:** Has the key exchange (Hades-Cerberus or
  Persephone-Demeter) been completed?
- **Leadership state:** Who is leader in each room?

The belief state accumulates this information across ticks; the strategic
layer reasons over the accumulated knowledge.

### 3. Time-Budget Awareness

With only 15 seconds per round and 3 rounds total, every action has an
opportunity cost. The strategic layer must:

- Prioritize high-value interactions over exploratory ones
- Know when to cut losses (exit a whisper that isn't productive)
- Escalate urgency as rounds progress (Round 3 is "panic mode")
- Budget time per interaction (~8-10 seconds for a full probe cycle)

### 4. Deception as a Tool

The game rewards strategic deception:
- Chat messages can contain any text (lies are free)
- Behavioral camouflage (acting like a different role)
- Information warfare via global chat
- Spy-specific fake identity via color exchange

The agent should employ deception when the expected value exceeds the
cost of potential exposure.

---

## Knowledge Model

### Player Knowledge Record

For each player (identified by sprite color + shape):

```
PlayerKnowledge:
  player_id: (color, shape)
  team: Shades | Nymphs | Unknown
  team_source: color_exchange | role_exchange | inferred | none
  role: specific role | Unknown
  role_source: role_exchange | role_reveal | inferred | none
  room: RoomA | RoomB | Unknown
  is_leader: bool
  has_exchanged_with_us: bool
  trust_level: verified | probable | uncertain | hostile
  last_interaction_round: int
```

### Strategic State

```
StrategicState:
  my_role: Role (from role reveal)
  my_team: Team
  my_room: Room
  current_round: int
  time_remaining: float (estimated)
  key_exchange_done: bool
  key_partner_found: bool
  key_partner_room: Room | Unknown
  enemy_key_role_room: Room | Unknown
  am_leader: bool
  current_objective: Objective enum
```

---

## Mode Architecture

Eurydice uses Orpheus modes to express high-level behavioral states:

| Mode | Description | Active During |
|------|-------------|---------------|
| `idle` | Default; waiting for role reveal or between actions | Pre-game, transitions |
| `scout` | Approach players and initiate interactions | Playing phase |
| `engage_whisper` | Create whisper or request entry | Playing phase |
| `in_whisper` | Execute whisper actions (color/role exchange, chat) | Whisper view |
| `seek_target` | Move toward a specific known player | Playing phase |
| `defend_position` | Stay in current room; resist movement | Playing/HostageSelect |
| `seek_leadership` | Usurp current leader or maintain own leadership | Playing phase |
| `hostage_select` | Select hostages as leader | HostageSelect phase |
| `summit_interact` | Interact during leader summit | LeaderSummit phase |
| `observe` | Monitor global chat and shout strip passively | Any view |

### Mode Transitions (Outer Loop)

The outer loop evaluates the strategic state and selects the appropriate
mode. Key decision points:

1. **Do I have a high-priority target to approach?** → `seek_target`
2. **Am I near an unprobed player?** → `engage_whisper`
3. **Am I in a whisper?** → `in_whisper` (with sub-strategy based on
   occupants)
4. **Do I need to seek leadership?** → `seek_leadership`
5. **Is it hostage selection and I'm leader?** → `hostage_select`
6. **Default:** → `scout` (wander and look for opportunities)

---

## Role Dispatch Table

| Role | Primary Objective | Approach Style | Risk Tolerance |
|------|-------------------|---------------|----------------|
| Hades | Exchange with Cerberus | Aggressive with Shades, cautious with Nymphs | Medium |
| Cerberus | Exchange with Hades | Very aggressive probing | High (no positional risk) |
| Shade | Support Hades | Aggressive all-around | Very high (expendable) |
| Persephone | Exchange with Demeter | Selective, defensive | Low (must protect identity) |
| Demeter | Exchange with Persephone | Aggressive with Nymphs | Medium-high |
| Nymph | Protect Persephone | Intelligence-focused | High (expendable) |
| Spy | Infiltrate enemy team | Appears as enemy team | Medium (cover matters) |

---

## Strategic Priority System

Each role's `meta_decide` evaluates objectives in priority order. The
first unsatisfied objective drives mode selection:

### Shades Key Roles (Hades, Cerberus)

```
1. IF key exchange not done AND partner in room → mode: seek_target / engage_whisper
2. IF key exchange not done AND partner not in room → mode: coordinate_movement
3. IF key exchange done AND Persephone's room unknown → mode: scout (intel gathering)
4. IF key exchange done AND positioning wrong → mode: coordinate_movement
5. IF key exchange done AND positioning correct → mode: defend_position
```

### Nymphs Key Roles (Persephone, Demeter)

```
1. IF key exchange not done AND partner in room → mode: seek_target / engage_whisper
2. IF key exchange not done AND partner not in room → mode: coordinate_movement
3. IF key exchange done AND Hades' room unknown → mode: scout (defensive intel)
4. IF key exchange done AND in Hades' room → mode: coordinate_movement (escape)
5. IF key exchange done AND NOT in Hades' room → mode: defend_position
```

### Grunts (Shade, Nymph)

```
1. IF room composition unknown → mode: scout (color exchange everything)
2. IF key roles need help meeting → mode: coordinate_movement (facilitate)
3. IF leadership available and useful → mode: seek_leadership
4. IF enemy key role located → mode: relay_intelligence
5. DEFAULT → mode: scout / disrupt
```

---

## Communication Protocol

### Global Chat Usage

| Situation | Message Pattern | When |
|-----------|----------------|------|
| Seeking teammate | "LOOKING FOR [color]" | Round 1 |
| Meetup coordination | "MEET [x] [y]" | After finding partner |
| Intelligence sharing | "[color] IS [role]" | After verifying identity |
| Deception | False claims about identity/location | When disruption benefits team |
| Decoy | "I AM [fake role]" | Grunts drawing attention |

### Whisper Protocol

Interaction sequences within whispers follow a standard escalation:

```
1. Greet / assess occupants
2. C.OFFER (color exchange) → learn team
3. If same team: R.OFFER (mutual role exchange) → learn specific role
4. If opposite team: extract intel / waste time / exit
5. If partner found: execute key exchange immediately
```

---

## Implementation Phases

### Phase 1: Core Loop

- Role detection from role reveal screen
- Basic mode dispatch (idle / scout / seek_target)
- Movement toward players
- Whisper creation

### Phase 2: Information Gathering

- Color exchange execution (menu navigation)
- Mutual role exchange execution
- Knowledge accumulation in belief state
- Team/role tracking per player

### Phase 3: Strategic Reasoning

- Role-specific `meta_decide` logic
- Priority-based objective evaluation
- Round-aware urgency escalation
- Hostage selection as leader

### Phase 4: Social Dynamics

- Global chat communication
- Deception and misdirection
- Usurp coordination
- Cross-room intelligence relay

### Phase 5: Advanced Play

- Spy-specific infiltration logic
- Behavioral camouflage
- Counter-intelligence (detecting enemy probes)
- Adaptive strategy based on observed enemy behavior

---

## Key Design Decisions

### Why rule-based instead of LLM?

- **Latency:** LLM calls (~500-1500ms) are incompatible with 15-second
  rounds where every second counts. Rule-based decisions execute in <1ms.
- **Determinism:** Reproducible behavior for testing and debugging.
- **Efficiency:** No token costs, no API dependencies, no rate limits.
- **Sufficiency:** The game's strategy space is large but well-structured.
  Role-specific heuristics can cover the vast majority of situations
  without general-purpose reasoning.

### Why one agent for all roles?

- Shared perception and framework infrastructure
- Role dispatch is a natural Orpheus outer-loop concern
- Avoids code duplication across 7 similar-but-different agents
- Easier to test and validate (one policy, many configurations)

### Why prioritize the key exchange over positioning?

The win condition decision tree shows that without the mutual role
exchange, **nobody wins**. Positioning only matters as a tiebreaker when
both teams complete their exchanges. Therefore:
- Exchange is a strict prerequisite
- Positioning is a secondary optimization
- An agent that always completes its exchange but gets positioning wrong
  50% of the time still wins more than one that optimizes position but
  fails the exchange.

---

## Reference Documents

- `HADES_STRATEGY.md` -- Hades role strategy
- `CERBERUS_STRATEGY.md` -- Cerberus role strategy
- `SHADE_STRATEGY.md` -- Shade grunt strategy
- `PERSEPHONE_STRATEGY.md` -- Persephone role strategy
- `DEMETER_STRATEGY.md` -- Demeter role strategy
- `NYMPH_STRATEGY.md` -- Nymph grunt strategy
- `SPY_STRATEGY.md` -- Spy role strategy (both team variants)
