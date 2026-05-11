# Eurydice -- Design Document

## What is Eurydice?

Eurydice is a rule-based Orpheus agent for Persephone's Escape that plays
all roles competently via role-specific strategy modules. It sits on top of
the Orpheus framework (perception, belief state, pipeline, outer loop) and
adds a strategic reasoning layer that selects modes and tasks based on:

1. **Assigned role** (detected from the role reveal screen)
2. **Game phase** (round number, time remaining, current phase type)
3. **Accumulated knowledge** (team identities, role identities, room
   assignments, exchange status, behavioral observations)
4. **Strategic priorities** (derived from role-specific strategy documents)
5. **Temporal urgency** (round budget, probe cycle cost, escalation state)

Named for the mythological figure who Orpheus followed into the
underworld -- fitting for an agent built on the Orpheus framework that
must navigate the Underworld and Mortal Realm.

---

## Architecture Overview

```
+---------------------------------------------------------+
|                    Eurydice Agent                        |
|                                                         |
|  +---------------------------------------------------+  |
|  |           Strategic Layer (Outer Loop)             |  |
|  |                                                   |  |
|  |  +-------------+  +-------------------------+    |  |
|  |  | Role        |  | Strategy Evaluator      |    |  |
|  |  | Dispatcher  |--| (role-specific rules)   |    |  |
|  |  +-------------+  +-------------------------+    |  |
|  |        |                     |                    |  |
|  |        v                     v                    |  |
|  |  +-----------------------------------------+     |  |
|  |  | meta_decide(belief, memory)             |     |  |
|  |  | -> (ModeDirective, inferences)          |     |  |
|  |  +-----------------------------------------+     |  |
|  +---------------------------------------------------+  |
|                       |                                  |
|                       | ModeBuffer                       |
|                       v                                  |
|  +---------------------------------------------------+  |
|  |           Tactical Layer (Inner Loop)             |  |
|  |                                                   |  |
|  |  +--------+ +--------+ +--------+ +-----------+  |  |
|  |  | Modes  | | Tasks  | | Hooks  | | Whisper   |  |  |
|  |  |        | |        | |        | | Protocol  |  |  |
|  |  +--------+ +--------+ +--------+ +-----------+  |  |
|  +---------------------------------------------------+  |
|                       |                                  |
|                       v                                  |
|  +---------------------------------------------------+  |
|  |         Orpheus Framework (Pipeline)              |  |
|  |  Perception -> Belief Update -> Decide -> Act     |  |
|  +---------------------------------------------------+  |
+---------------------------------------------------------+
```

---

## Implementation Status

This document describes the intended full design. The current source does
not yet implement every behavior described here. The source-verified
roadmap and gap list live in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

Current high-level status:

- Pixel perception, Orpheus belief update, Eurydice's post-belief hook,
  `meta_decide`, basic probing modes, and the whisper FSM are implemented.
- Role evaluators exist, but currently return mostly bare mode directives
  for some advanced branches. Core partner-search/probe/positioning branches
  now carry typed params and objectives through `meta_decide`, with pytest
  contracts for key-role cross-room behavior, Shade leader hostage strategy,
  Spy ally verification, and final-round disruption.
- Probe modes now select a target before create-vs-join, cap failed entry
  attempts per target/round, emit probe lifecycle trace events, and avoid
  initiating whispers during HostageSelect.
- The whisper FSM now recovers protocol intent from the directive that caused
  whisper entry. Runtime-supported protocol variants include standard,
  key-exchange, quick-verify, infiltration, and stall. Incoming role offers use
  Spy-specific acceptance rules.
- Leadership, hostage, cross-room, communication, deception, and Spy logic
  are still partial. Spy role-offer handling is wired, but broader cover
  management and outbound deception are not complete.
- LLM runtime control is not implemented yet. `llm_context.py` now provides a
  JSON-safe state packet and closed semantic decision schema, and
  `llm_validator.py` provides the deterministic validation and shadow tracing
  boundary for future model outputs. No provider, prompt templates, saved-trace
  runner, or runtime handoff exists yet. See [`LLM_CONTROL.md`](LLM_CONTROL.md).
- Structured exchange events, active offers, inbound chat parsing, unique
  leader-color observations, post-whisper info-screen reconciliation, and
  Spy-aware color-exchange confidence are wired into Eurydice's knowledge
  layer. Crowded whisper attribution and outbound communication policy remain
  partial.
- Perception still lacks stronger leader detection. Own sprite identity, role
  summary config, round schedule parsing, and visible non-bubble player
  sprites are now implemented. Role summary config has a live Spy/Echo fixture,
  and round schedule parsing has a live non-default schedule fixture. The
  other intro and overworld fields still need broader live-frame validation
  across config presets.

When source and this design disagree, treat source as current behavior and
update this document or the implementation plan in the same change that
changes behavior.

---

## Core Concepts

### LLM Control Boundary

Eurydice's current runtime strategy is deterministic. The intended next
architecture is LLM-assisted social strategy behind deterministic safety
guards. The LLM should choose semantic actions such as `probe_player`,
`send_whisper`, `send_global`, `offer_role`, or `exit_whisper`; Orpheus tasks
remain responsible for menus, button timing, movement, and view legality.

The source contract lives in `agents/eurydice/llm_context.py`:

- `build_llm_context(...)` serializes self identity, current strategic state,
  match config, player knowledge, recent messages, legal actions, and hard
  constraints.
- `llm_decision_schema()` defines the closed model response shape.
- `agents/eurydice/llm_validator.py` rejects malformed, illegal, unsafe, or
  mechanically unsupported decisions and can trace shadow validation results.
- No provider adapter is active yet; model decisions should first run in
  shadow mode against saved contexts and traces.

See [`LLM_CONTROL.md`](LLM_CONTROL.md) for rollout phases, validator
requirements, and trace metrics.

### The Probe Cycle

The probe cycle is the atomic unit of gameplay. Every meaningful
interaction follows this pattern:

```
[select_target] -> [approach] -> [create/enter whisper] -> [in-whisper protocol] -> [exit] -> [knowledge update]
```

**Time budget:** Probe cycle timing depends heavily on target cooperation
and entry method. Two paths exist:

**Flow A — Agent creates whisper near target:**
```
Walk to target -> Press A (create whisper) -> Wait for target to request entry -> GRANT -> interact -> EXIT
```

**Flow B — Agent requests entry to target's existing whisper:**
```
Walk to target (has speech bubble) -> Press B (request entry) -> Wait for GRANT -> interact -> EXIT
```

Both flows share the same bottleneck: **getting both players into the
same whisper requires the other party's cooperation.** Entry requests
timeout after 10 seconds (240 ticks). Non-cooperative targets may never
enter/grant.

**Timing breakdown (cooperative target, per-interaction):**

| Step | Best Case | Typical | Notes |
|------|-----------|---------|-------|
| Walk to target | 1-2s | 3-4s | Room is 100-200px; average ~40-60px distance |
| Whisper entry dance | 1-2s | 2-4s | Create + target requests + GRANT menu nav |
| Color exchange | 3-4s | 3-4s | C.OFFER (menu nav) + 48-tick cooldown + C.ACCPT |
| Role exchange | 3-4s | 3-4s | R.OFFER (menu nav) + 48-tick cooldown + R.ACCPT |
| Exit | 0.5s | 1s | EXIT menu nav + view transition |
| **Full probe total** | **~9s** | **~13s** | Includes both exchanges |
| **Fast probe (skip color)** | **~6s** | **~9s** | For same-team targets already identified |

**Probe throughput varies dramatically by config:**

The game supports multiple config presets with round durations from 15
seconds to 300 seconds. The strategy must work across all of them.

| Round Duration | Full Probes/Round | Fast Probes/Round | Notes |
|---------------|-------------------|-------------------|-------|
| 15s (default) | 0-1 | 1 | Every second precious; target selection critical |
| 30s (short) | 1-2 | 2-3 | Tight but workable |
| 45s (empty3) | 3-4 | 4-5 | Comfortable single-room coverage |
| 60s (simple, debug2r) | 4-6 | 5-7 | Can probe entire 5-person room |
| 120s (medium R2) | 10+ | 12+ | Exhaustive probing + re-probing + positioning |
| 180s (medium R1) | 15+ | 18+ | Full exploration + strategic positioning |

**Key observation:** The `medium` preset family uses **descending round
durations** (e.g., 180s / 120s / 60s). Round 1 is deliberately long
for exploration; the final round is short to create urgency. This
matches the design's urgency escalation model naturally: Round 1 has
ample time for systematic probing, while the final round forces quick
decisive action. The agent's `probe_cycle_cost_ticks` should be read
from `belief_state.round_schedule` (populated from the round config),
not hardcoded.

**Design implication:** The probe cycle FSM and time budgets must be
**config-adaptive**:
- `can_start_probe_cycle` checks `ticks_remaining > probe_cycle_cost`
  against the CURRENT round's duration, not a fixed 15s assumption.
- Target selection priority weights adjust based on time budget: with
  180s rounds, the agent can afford exploratory probes of lower-priority
  targets; with 15s rounds, only the highest-value target is worth
  pursuing.
- The urgency escalation thresholds (CALM / PRESSING / PANIC) must be
  expressed as fractions of round duration, not absolute tick counts.

**Non-cooperative targets (tournament reality):**
- Opponents may not request entry to your whisper (they have their own
  goals, may not notice your speech bubble, or may actively avoid you).
- Opponents may not GRANT your entry request (busy, hostile, or
  indifferent).
- A failed entry attempt wastes 3-5 seconds (walk + wait + timeout or
  abort). Budget at most ONE failed attempt per round before switching
  targets.

**Key design implication:** The scarcity of probe cycles (especially in
short-round configs) makes target selection the most impactful decision
per round. Probing the wrong player is a round-level mistake with no
recovery. The `score_target` algorithm must strongly prefer: (a) nearby
targets, (b) cooperative-seeming targets (approaching us, or currently
in overworld and idle), (c) high-information-value targets (unknown team
> known team).

**Abort conditions:**
- Time budget exceeded (>10s in cycle without completing)
- Target walked away before whisper creation
- Entry request not granted within 72 ticks (3s) — abort early, don't
  wait the full 240-tick timeout
- Hostile occupant identified (exit early for safety)
- Higher-priority event detected (key role spotted, phase transition)

**Interaction range:** `BUBBLE_RADIUS = 20` pixels (`constants.ts:91`).
Both whisper creation and entry requests use `distSq <= 400` (20px
squared) via `findNearbyWhisperPlayer` (`sim.ts:807-817`):

- **Create whisper (A button):** Must be >20px from ALL players currently
  in a whisper (otherwise blocked with "YOU'LL BE OVERHEARD"). The
  TARGET does not need to be in a whisper -- you create alone, then they
  request entry to you.
- **Request entry (B button):** Must be ≤20px from a player who IS in a
  whisper. That player's whisper receives the entry request.

**Implication for approach:** To initiate a probe via Flow A (create
whisper near target), you need the target in the overworld (not already
in a whisper) AND no other whisper player within 20px of your position.
To use Flow B (request entry), the target must already be in a whisper
and you must get within 20px of them.

### Observability Constraints

#### Minimap

The minimap provides partial player location data with specific fog-of-war
behavior:

- **Obstacles:** Always visible regardless of fog (no shadow check).
- **Other players:** Partially fog-aware. A player whose screen-space
  center pixel falls on a shadowed pixel within the camera viewport is
  hidden from the minimap. However, players OUTSIDE the camera viewport
  (far away from the viewer) bypass the shadow check entirely and always
  appear as dots. (`renderer.ts:384-387`: the bounds check
  `sx >= 0 && sx < SCREEN_WIDTH && sy >= 0 && sy < SCREEN_HEIGHT`
  short-circuits the shadow lookup for out-of-viewport players; the
  shadow buffer is only 128x128 and has no data for them.)
- **Implication:** The minimap reliably shows far-away players but may
  hide nearby players behind walls. This is the inverse of viewport
  observation (which shows nearby but can't see far). Together, viewport
  + minimap provide complementary coverage.
- **Color only:** Minimap dots are single-pixel, color-only (no shape).
  Up to 3 players can share a color (player indices with same `i % 8`).
  Disambiguation requires inference: co-location of a viewport-identified
  player (known color + shape) with a minimap dot of matching color
  establishes identity for that dot. Once identified, the dot can be
  tracked across frames even when the player leaves viewport range.
- **Self dot:** Always drawn last in color 2 (dark magenta), overwriting
  others at the same minimap cell. A target you're pursuing can "disappear"
  from the minimap when you're at the same cell.

#### Viewport (Overworld)

- Shows a ~110x110 pixel window centered on the player.
- Full (color, shape) identification of visible player sprites.
- Fog of war hides players behind obstacles (via raycasting).
- Walls (color 5) are exempt from fog darkening -- always visible.
- Speech bubbles indicate whisper participation (but not WHO they're
  whispering with -- only spatial proximity suggests partnerships).

#### Whisper View (Private)

- Full occupant list visible (color + shape in header).
- All system messages visible to current occupants only.
- No overworld information available while in whisper.
- No global chat access (cannot read, send, or see unread indicator).

### The Information Hierarchy

Information has different reliability levels:

| Level | Source | Reliability | Example |
|-------|--------|-------------|---------|
| Mechanical truth | Mutual role exchange | 100% | "This player is Cerberus" |
| Mechanical partial | Color exchange | High (Spy caveat) | "This player appears Shades" |
| Behavioral inference | Observation | Medium | "Refuses role exchange = likely key role" |
| Social claim | Chat message | Unverified | "I'm Hades" (could be lying) |
| Absence inference | Elimination | Medium-high | "All local Nymphs are grunts, so Persephone is in other room" |

The Spy exception: color exchange shows the **opposite** team for Spies.
Only mutual role exchange reveals truth. In configurations that include a
Spy, one player's color exchange will yield a false team identification.
In the **default composition** (no Spy role), color exchange is 100%
reliable. The `team_confidence` for color-exchanged players should be
1.0 in default composition, reduced to 0.9 only when the game config
includes a Spy (detectable from Panel 2 of the intro sequence, which
lists all roles present in the match).

### Urgency Escalation

The agent's risk tolerance and action priority change over rounds:

| Round | Posture | Risk Tolerance | Priority |
|-------|---------|----------------|----------|
| 1 | Exploratory | Low | Information gathering; find key partner |
| 2 | Execution | Medium | Complete exchange; begin positioning |
| 3 | Desperate | High | Win condition at any cost; reveal identity if needed |

Urgency escalation is a multiplier on the priority system: in Round 3,
an agent will take actions it would reject in Round 1 (e.g., revealing
identity in global chat to coordinate, accepting risky hostage moves).

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
- **Behavioral profiling:** Who is acting like a key role?

The belief state accumulates this information across ticks; the strategic
layer reasons over the accumulated knowledge.

### 3. Time-Budget Awareness

With only 15 seconds per round and 3 rounds total, every action has an
opportunity cost. The strategic layer must:

- Prioritize high-value interactions over exploratory ones
- Know when to cut losses (exit a whisper that isn't productive)
- Escalate urgency as rounds progress (Round 3 is "panic mode")
- Budget time per interaction (~8-10 seconds for a full probe cycle)
- Never waste a probe cycle on an already-identified player

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

```python
@dataclass
class PlayerKnowledge:
    player_id: tuple[Color, Shape]        # Visual identity
    name: str | None                      # Character name from roster

    # Team/role identification
    team: Team | None                     # Shades | Nymphs | None
    team_source: TeamSource               # color_exchange | role_exchange | inferred | none
    team_confidence: float                # 0.0-1.0; color_exchange=0.9, role_exchange=1.0
    role: Role | None                     # Specific role or None
    role_source: RoleSource               # role_exchange | one_way_reveal | inferred | none

    # Spatial
    room: Room | None                     # Last known room
    room_confidence: float                # Decays over time; 1.0=confirmed this phase
    room_last_confirmed_tick: int         # When room was last verified
    last_seen_position: tuple[int, int] | None  # Last overworld coords

    # Interaction state
    has_exchanged_colors_with_us: bool    # We've done C.OFFER/C.ACCPT
    has_exchanged_roles_with_us: bool     # We've done R.OFFER/R.ACCPT
    we_have_pending_offer_to: str | None  # "color" | "role" | None
    they_have_pending_offer: str | None   # "color" | "role" | None
    last_interaction_tick: int            # Last time we were in a whisper together
    last_interaction_round: int           # Round of last interaction
    times_interacted: int                 # Total whisper sessions together

    # Behavioral observations
    behavioral_flags: set[str]            # See "Behavioral Inference Flags" below
    refused_role_exchange: bool           # Declined our R.OFFER (suspicious)
    exchange_eagerness: float             # 0-1; how quickly they proposed exchange
    is_leader: bool                       # Currently has leadership
    was_leader_round: list[int]           # Rounds where they held leadership

    # Social graph
    probable_whisper_partners: list[tuple[PlayerID, float]]  # (player_id, confidence)
    # Derived from spatial proximity of speech-bubbled players. Two players
    # with simultaneous speech bubbles within ~15px are LIKELY in the same
    # whisper (confidence ~0.7). Confirmed partnerships (from whispers WE
    # participate in) have confidence 1.0. Cannot directly observe other
    # players' whisper occupant lists from the overworld.
    claims_made: list[str]                # Messages they've sent (global + whisper)
    claims_about_identity: str | None     # What they claim to be (if any)

    # Deception tracking (what WE have told/shown THEM)
    we_claimed_to_be: str | None          # Role/team we claimed in chat
    we_showed_color: bool                 # Did we color-exchange with them
    we_showed_role: bool                  # Did we role-reveal/exchange with them

    # Trust classification
    trust_level: TrustLevel              # verified | probable | uncertain | hostile
```

### Behavioral Inference Flags

Observable behaviors that inform strategic reasoning:

| Flag | Observation | Inference |
|------|-------------|-----------|
| `seeks_specific_teammate` | Urgently approaching same-team players | Likely key role (Hades/Cerberus or Persephone/Demeter) |
| `refuses_role_exchange` | Declined R.OFFER | Likely key role or Spy (grunts have no reason to refuse) |
| `exchange_eager` | Immediately proposed R.OFFER in whisper | Likely key role seeking partner |
| `avoids_interaction` | Declines whisper entry, moves away from approachers | Likely Persephone (identity protection) |
| `aggressive_probing` | Rapidly cycling through players | Likely Cerberus or Demeter (searchers) |
| `defensive_posture` | Staying still, seeking leadership, few interactions | Likely Persephone (defense) |
| `chatty_global` | Frequent global chat messages | Grunt or decoy (key roles stay quiet) |
| `inconsistent_claims` | Chat messages contradict mechanical reveals | Deceptive; possibly enemy or Spy |
| `whispers_with_both_teams` | Probable whisper partnerships (proximity-inferred) include known players from both teams | Possible Spy or well-informed grunt (confidence reduced: proximity inference, not direct observation) |
| `relaxed_after_urgency` | Player was aggressively probing (3+ whisper entries in prior rounds), then became passive/defensive in current round | Likely completed key exchange (mission accomplished, now optimizing positioning) |
| `co_seeking_positioning` | Two same-team players both seeking leadership or simultaneously avoiding hostage selection | Likely both completed their team's exchange, now cooperating on tiebreaker positioning |

### Strategic State

The strategic state is the high-level reasoning context for `meta_decide`:

```python
@dataclass
class StrategicState:
    # Identity
    my_role: Role                         # From role reveal
    my_team: Team                         # From role reveal
    my_room: Room                         # Current room assignment
    my_player_id: PlayerID                # Own sprite identity

    # Temporal
    current_round: int                    # 1, 2, or 3
    current_phase: Phase                  # Playing, HostageSelect, LeaderSummit, etc.
    round_start_tick: int                 # Tick when current round started
    ticks_remaining_in_phase: int         # Estimated ticks left (from perception)
    urgency: Urgency                     # calm | pressing | panic (derived from round + time)

    # Key exchange status
    key_exchange_done: bool               # Has OUR team's key pair exchanged?
    key_partner_found: bool               # Have we identified our key partner?
    key_partner_id: PlayerID | None       # Sprite identity of partner (if known)
    key_partner_room: Room | None         # Where partner is (if known)
    enemy_key_exchange_done: bool | None  # Has THEIR key pair exchanged? (if known)
    # NOTE: enemy_key_exchange_done is None in the vast majority of games.
    # Can only be populated via: direct observation (extremely unlikely),
    # credible ally chat claim (confidence 0.5), or late-game behavioral
    # inference (enemy key roles showing relaxed/positioning behavior).
    # Strategy MUST be robust to this being None. When None, conservative
    # assumptions apply: assume enemy MIGHT have completed in Round 3.
    enemy_key_exchange_likely: bool       # Derived: True if evidence suggests completion
    # Derived from: enemy_key_exchange_done == True, OR Round 3 time
    # pressure, OR behavioral flags (relaxed_after_urgency on enemy
    # key roles observed after prior urgency).
    enemy_key_role_id: PlayerID | None    # Enemy key role identity (Hades or Persephone)
    enemy_key_role_room: Room | None      # Where enemy key role is (if known)

    # Room composition (reconstructed from knowledge)
    players_in_my_room: list[PlayerID]    # All players confirmed in my room
    players_in_other_room: list[PlayerID] # All players confirmed in other room
    players_room_unknown: list[PlayerID]  # Players whose room we don't know
    allies_in_my_room: list[PlayerID]     # Confirmed same-team in my room
    enemies_in_my_room: list[PlayerID]    # Confirmed opposite-team in my room

    # Leadership
    am_leader: bool                       # Am I currently the leader?
    room_leader_id: PlayerID | None       # Who is leader in my room?
    room_leader_team: Team | None         # Leader's team (if known)
    met_other_leader_in_summit: bool      # Did we summit with other leader? (intel source)
    other_leader_team: Team | None        # Other leader's team (from summit interaction)

    # Interaction tracking
    players_probed_this_round: list[PlayerID]  # Already completed probe cycles
    players_unprobed_in_room: list[PlayerID]   # Not yet interacted with
    probe_cycles_remaining: int           # Estimated remaining cycles this round

    # Scaling parameters (derived from config at game start)
    room_player_count: int                # Players in my room (varies: 3-12)
    total_player_count: int               # Total players in game (6-24)
    usurp_votes_needed: int               # floor(room_player_count / 2) + 1
    probe_coverage_fraction: float        # probes_remaining / room_player_count
    # probe_coverage_fraction drives strategy: >0.8 = can probe everyone
    # (exhaustive), 0.3-0.8 = must prioritize (selective), <0.3 = triage
    # (only highest-value targets)

    # Intelligence (local only -- cross-room relay is impossible)
    local_intel_to_share: list[IntelItem] # Intel to share with local allies (via whisper/chat)
    intel_for_summit: list[IntelItem]     # Intel to use if we become leader for summit

    # Spy-specific
    cover_intact: bool                    # (Spy only) Is our fake identity intact?
    cover_identity: Team | None           # (Spy only) What team we appear to be
    verified_ally: PlayerID | None        # (Spy only) One real ally who knows we're Spy

    # Current mode tracking
    current_objective: Objective          # Active strategic objective
    mode_entered_tick: int                # When current mode was activated
    consecutive_idle_ticks: int           # Stuck detection
```

### Inference Engine

The inference engine updates `PlayerKnowledge` and `StrategicState` by
applying rules to observations. Rules are evaluated in priority order;
higher-confidence inferences override lower ones.

#### Hard Inference Rules (Certainty = 1.0)

These produce verified knowledge:

```
IF mutual_role_exchange(P) THEN P.role = revealed_role, P.team = revealed_team, confidence = 1.0
IF color_exchange(P) reveals Shades THEN P.team = Shades, confidence = 1.0 if no Spy in config, else 0.9
IF color_exchange(P) reveals Nymphs THEN P.team = Nymphs, confidence = 1.0 if no Spy in config, else 0.9
IF one_way_role_reveal(P) observed THEN P.role = revealed_role, confidence = 0.95
IF P is in my room (visible) THEN P.room = my_room, room_confidence = 1.0
IF roster_reveal shows P in RoomX THEN P.room = RoomX, room_confidence = 1.0
IF P selected as hostage from RoomX THEN P.room = other_room (after exchange), room_confidence = 1.0
```

**Spy-in-config detection:** Panel 2 of the intro sequence lists all
unique roles present in the match (including Spy if configured). The boolean
`spy_in_game_config` is set during the intro and persists for the game's
lifetime. When false, color exchange is mechanically guaranteed truthful
(no player can produce a false color reveal), so confidence = 1.0. When true,
color-only team confidence is reduced to 0.9 until a role exchange verifies
the player. The default 10-player composition does NOT include a Spy.

#### Soft Inference Rules (Certainty < 1.0)

These produce probabilistic beliefs:

```
IF all_nymphs_in_my_room_are_grunts THEN persephone.room = other_room (confidence 0.85)
IF all_shades_in_my_room_are_grunts THEN hades.room = other_room (confidence 0.85)
IF P.team == my_team AND P.refuses_role_exchange THEN P.role likely key_role (confidence 0.3 per refusal, max 0.6)
IF P.team == my_team AND P.exchange_eager THEN P.role likely key_role_searcher (confidence 0.35 per observation, max 0.7)
# NOTE: These flags are typically derived from a single interaction (our
# own whisper with the player). Single-datapoint confidence is halved.
# Confidence accumulates with repeated observations across interactions.
IF P.behavioral_flags has 'avoids_interaction' THEN P might be Hades (confidence 0.3)
# Reduced from 0.5: avoidance has many explanations (behind obstacles,
# focused on other targets, simply far away). Only meaningful when
# visible_ticks_this_round is high (player was genuinely observable).
IF P.claims_about_identity contradicts P.team (from exchange) THEN P is deceptive (confidence 0.8)
```

#### Elimination Rules

Deductive reasoning from known identities:

```
IF I know N grunts on my team AND total grunts expected == N THEN remaining unknowns on my team are key roles
IF key_partner found AND all other same-team players identified THEN remaining unidentified same-team = key_partner (if partner not found)
```

#### Spy Awareness Rules

```
IF P.team_source == color_exchange AND P behaves inconsistently with claimed team THEN P might be Spy (confidence 0.4)
IF P shows Shades via color exchange BUT whispers extensively with confirmed Nymphs THEN Spy suspicion += 0.3
IF mutual_role_exchange reveals "Spy" THEN P.role = Spy, P.team = revealed_true_team, confidence = 1.0
```

---

## Behavioral Accumulation Pipeline

### The Problem

Orpheus's belief update phase integrates **instantaneous** perception data
each tick: who is visible, what view we're in, what messages appeared. But
the behavioral inferences we need (e.g., "this player is aggressively
probing everyone") emerge from **patterns over time** -- watching the same
player approach 3 different people across 200 ticks, or noting that they've
been in 4 whispers in a single round.

The belief state captures the raw data. The behavioral accumulation
pipeline transforms it into actionable pattern knowledge.

### Architecture: Post-Belief-Update Hook

Eurydice registers a `post_belief_update` hook with Orpheus. Every tick,
after the framework integrates perception into belief state, this hook
runs:

```python
def eurydice_post_belief_update(belief_state: BeliefState, action_memory: ActionMemory) -> None:
    """Registered as post_belief_update hook. Runs every tick.

    Updates long-term behavioral accumulators and derives behavioral
    flags from accumulated patterns. Mutates belief_state directly
    (permitted in hooks).
    """
    accumulators = belief_state.ext["eurydice_accumulators"]
    knowledge = belief_state.ext["player_knowledge"]

    # 1. Feed raw observations into accumulators
    update_position_tracker(accumulators, belief_state)
    update_whisper_tracker(accumulators, belief_state)
    update_exchange_tracker(accumulators, belief_state)
    update_chat_tracker(accumulators, belief_state)
    update_leadership_tracker(accumulators, belief_state)

    # 2. Derive behavioral flags from accumulators
    for player_id, acc in accumulators.player_accumulators.items():
        flags = derive_behavioral_flags(acc, belief_state)
        knowledge[player_id].behavioral_flags = flags

    # 3. Run soft inference rules against updated flags
    run_soft_inferences(knowledge, belief_state)

    # 4. Update strategic-relevant summaries
    update_interaction_counts(accumulators, belief_state)
```

### Accumulators

Each accumulator tracks a specific class of observation over time. They
are append-only during a round and partially reset between rounds (to
account for position changes from hostage exchange).

```python
@dataclass
class PlayerAccumulator:
    """Per-player running state for behavioral inference."""
    player_id: PlayerID

    # Position tracking
    # NOTE: Position observations are intermittent due to fog of war.
    # A player behind an obstacle is invisible -- their position is not
    # updated. Counters like stationary_ticks only count VISIBLE ticks.
    position_history: deque[tuple[int, int, int]]  # (tick, x, y) ring buffer, max 120 entries (~5s)
    visible_ticks_this_round: int = 0  # Total ticks this player was observable
    stationary_ticks: int = 0          # Consecutive VISIBLE ticks with <2px movement
    not_visible_since: int | None = None  # Tick when we lost sight (fog/distance)
    total_distance_this_round: float = 0.0
    distinct_players_approached: set[PlayerID] = field(default_factory=set)

    # Whisper tracking
    whisper_entries_this_round: int = 0
    whisper_partners_this_round: set[PlayerID] = field(default_factory=set)
    total_time_in_whispers_ticks: int = 0
    whisper_entry_ticks: list[int] = field(default_factory=list)  # tick of each entry (cross-round; never reset)
    max_whisper_entries_any_round: int = 0  # Peak per-round whisper entries across all prior rounds (cross-round)

    # Exchange behavior
    color_offers_made: int = 0
    color_offers_received_and_accepted: int = 0
    role_offers_made: int = 0
    role_offers_received_and_declined: int = 0
    role_offers_received_and_accepted: int = 0
    ticks_before_first_offer: int | None = None  # How quickly they offered in whisper

    # Chat behavior
    global_messages_sent_this_round: int = 0
    whisper_messages_sent: int = 0
    message_content_log: list[tuple[int, str]] = field(default_factory=list)  # (tick, text)

    # Leadership behavior
    sought_leadership: bool = False     # Voted for self in usurp
    passed_leadership: bool = False
    leadership_rounds: list[int] = field(default_factory=list)


@dataclass
class GlobalAccumulators:
    """Cross-player and game-level tracking."""
    player_accumulators: dict[PlayerID, PlayerAccumulator]
    current_round: int = 0
    round_start_tick: int = 0

    # Our own interaction tracking
    our_whisper_history: list[WhisperRecord] = field(default_factory=list)
    our_probe_cycles_this_round: int = 0
```

### Derivation Rules: From Accumulators to Flags

Each behavioral flag is derived from one or more accumulator values
crossing a threshold. Derivation runs every tick but flags only change
when underlying accumulators cross boundaries.

```python
def derive_behavioral_flags(acc: PlayerAccumulator, belief: BeliefState) -> set[str]:
    flags = set()
    round_ticks = belief.tick - belief.ext["eurydice_accumulators"].round_start_tick

    # "aggressive_probing": many whisper entries in short time
    if acc.whisper_entries_this_round >= 3 and round_ticks < 300:
        flags.add("aggressive_probing")
    elif acc.whisper_entries_this_round >= 2 and round_ticks < 180:
        flags.add("aggressive_probing")

    # "avoids_interaction": visible for extended time but rarely/never in whispers
    # Gate on visible_ticks (not round_ticks) to distinguish "not seen" from "seen and passive"
    if acc.visible_ticks_this_round > 200 and acc.whisper_entries_this_round == 0 and acc.stationary_ticks > 100:
        flags.add("avoids_interaction")

    # "defensive_posture": low movement, no probing, possibly seeking leadership
    if acc.total_distance_this_round < 50 and acc.whisper_entries_this_round <= 1:
        if acc.sought_leadership or acc.stationary_ticks > 150:
            flags.add("defensive_posture")

    # "exchange_eager": offered role exchange very quickly in whisper
    if acc.ticks_before_first_offer is not None and acc.ticks_before_first_offer < 48:
        flags.add("exchange_eager")

    # "refuses_role_exchange": declined at least one R.OFFER
    if acc.role_offers_received_and_declined > 0:
        flags.add("refuses_role_exchange")

    # "seeks_specific_teammate": approaches same-team players preferentially
    if len(acc.distinct_players_approached) >= 2:
        # Check if all approached players are same team
        approached_teams = [knowledge_of(p).team for p in acc.distinct_players_approached]
        if all(t == approached_teams[0] for t in approached_teams if t is not None):
            flags.add("seeks_specific_teammate")

    # "chatty_global": high global chat frequency
    if acc.global_messages_sent_this_round >= 2:
        flags.add("chatty_global")

    # "relaxed_after_urgency": was highly active in prior rounds, now passive
    # Requires cross-round summary field (updated during round reset)
    if (acc.max_whisper_entries_any_round >= 3
        and acc.whisper_entries_this_round == 0
        and round_ticks > 120):  # Give 5s before calling "passive"
        flags.add("relaxed_after_urgency")

    # "whispers_with_both_teams": probable whisper partnerships include both teams
    # NOTE: This uses proximity-inferred partnerships (confidence ~0.7) for
    # OTHER players' whispers. Only partnerships from OUR whispers have full
    # confidence. Treat this flag as suggestive, not definitive.
    partner_teams = set()
    for partner_id in acc.whisper_partners_this_round:
        partner_knowledge = knowledge_of(partner_id)
        if partner_knowledge and partner_knowledge.team:
            partner_teams.add(partner_knowledge.team)
    if len(partner_teams) >= 2:
        flags.add("whispers_with_both_teams")

    return flags
```

### How Accumulators Are Fed (Per-Tick Updates)

Each `update_*` function examines the current belief state and appends to
accumulators. These run unconditionally every tick:

**`update_position_tracker`:** For each player currently visible in
overworld, append their position to their ring buffer and increment
`visible_ticks_this_round`. Compute `stationary_ticks` (increment if
position delta < 2px AND player is visible, reset on movement). When a
player is NOT visible (absent from viewport sprites and not identifiable
on minimap), set `not_visible_since` to current tick and do NOT modify
`stationary_ticks` -- "not seen" is distinct from "seen and stationary."
Track `distinct_players_approached` by watching if a player moves toward
and arrives within interaction range of another player.

**`update_whisper_tracker`:** When belief state indicates a player entered
a whisper (new speech bubble visible, or player ID appears in our whisper
occupants list), increment their `whisper_entries_this_round`. Track
partners via two sources:
- **Confirmed (confidence 1.0):** Occupant lists from whispers WE are in.
- **Inferred (confidence ~0.7):** Spatial clustering of speech-bubbled
  players observed from the overworld. Two players with simultaneous
  speech bubbles within proximity_threshold (~15px world distance) are
  probable partners. This is heuristic -- adjacent separate whispers or
  entering/exiting players can produce false positives.

**`update_exchange_tracker`:** When system messages in our whisper
indicate offers/accepts/declines (e.g., "offered color", "shared roles"),
update the relevant player's accumulator. Track
`ticks_before_first_offer` as delta from whisper entry to first action.

**`update_chat_tracker`:** When new messages appear in global chat or
whisper, attribute to sender and append to their `message_content_log`.
Increment counters.

**`update_leadership_tracker`:** When system messages indicate usurp
votes or leadership changes, update relevant accumulators.

### Accumulator Lifecycle

| Event | Action |
|-------|--------|
| Game start | Initialize all accumulators to zero |
| New round starts | Snapshot cross-round summaries, then reset per-round counters (see below) |
| Player hostaged away | Freeze their accumulator (no more observations possible) |
| Player hostaged in | Initialize fresh accumulator for them |
| We are hostaged | Reset position-dependent accumulators; preserve interaction knowledge |
| Game ends | Accumulators are discarded |

**Round-reset procedure:**

```python
def reset_for_new_round(acc: PlayerAccumulator):
    # 1. Snapshot cross-round summaries BEFORE clearing
    acc.max_whisper_entries_any_round = max(
        acc.max_whisper_entries_any_round,
        acc.whisper_entries_this_round
    )

    # 2. Reset per-round counters (fields with "_this_round" suffix)
    acc.whisper_entries_this_round = 0
    acc.whisper_partners_this_round = set()
    acc.visible_ticks_this_round = 0
    acc.total_distance_this_round = 0.0
    acc.global_messages_sent_this_round = 0
    acc.stationary_ticks = 0
    acc.distinct_players_approached = set()

    # 3. Preserved across rounds (no reset):
    #    - whisper_entry_ticks (timestamped log; filterable by tick range)
    #    - total_time_in_whispers_ticks (cumulative)
    #    - max_whisper_entries_any_round (cross-round summary)
    #    - position_history (ring buffer; old entries age out naturally)
    #    - color_offers_made, role_offers_* (cumulative interaction counts)
    #    - ticks_before_first_offer (first-interaction measurement)
    #    - leadership_rounds (list of round numbers)
    #    - message_content_log (timestamped; filterable)
    #    - sought_leadership, passed_leadership (cumulative booleans)
```

### Relationship to Inference Engine

The inference engine (hard/soft rules) runs AFTER behavioral flags are
derived. The pipeline each tick is:

```
[Orpheus perception] -> [Orpheus belief update] -> [post_belief_update hook]:
    1. Feed accumulators from belief state
    2. Derive behavioral flags from accumulators
    3. Run soft inference rules using flags + knowledge
    4. Update PlayerKnowledge trust levels
```

This means `meta_decide` (which reads belief state on its next iteration)
always sees the latest behavioral assessments.

---

## The meta_decide Engine

### Execution Model

`meta_decide` is the outer-loop function that selects the active mode.
Per the Orpheus framework, it runs in a **continuous async loop** that
blocks on the belief buffer, consumes a snapshot, runs, pushes to the
mode buffer, then blocks again:

```
while True:
    belief_snapshot, memory_snapshot = belief_buffer.consume()  # blocks until available
    directive, inferences = meta_decide(belief_snapshot, memory_snapshot)
    mode_buffer.push((directive, inferences))  # overwrites any unconsumed prior
```

**We do not control when meta_decide is called.** The framework calls it
in a tight loop, throttled to at most once per inner-loop tick by the
consume-on-read buffer semantics. It receives a **read-only snapshot** of
belief state and action memory -- it cannot mutate the inner loop's state.

**Communication back to inner loop:**
- `ModeDirective`: tells the inner loop what mode to run
- `dict | None` (inferences): written to `belief_state.inferences`
  namespace, replacing it wholesale. This is the ONLY channel for
  outer-loop-produced reasoning state to reach the inner loop.

**Implications for Eurydice:**
- `meta_decide` must be **fast** (rule-based, <1ms). Since we're not
  calling an LLM, the loop runs at effectively tick rate.
- `meta_decide` must be **idempotent on stable state**: if nothing
  changed in the belief state, it should produce the same directive
  (reaffirmation, which the framework treats as a no-op).
- `meta_decide` must produce **durable strategic decisions** that remain
  correct even if the inner loop processes a few more ticks before
  consuming the mode buffer.
- Mode "completion" is communicated by the inner loop writing a signal
  into belief state (e.g., a `mode_complete` flag or `current_task ==
  IdleTask`). The next time `meta_decide` runs, it reads this and
  decides what mode to switch to.

When `meta_decide` runs, it:
1. Rebuilds `StrategicState` from the belief state snapshot
2. Dispatches to the role-specific evaluator
3. Returns `(ModeDirective, inferences: dict | None)`

### Role Dispatch

```python
def meta_decide(belief_state, action_memory) -> tuple[ModeDirective, dict | None]:
    strategic_state = build_strategic_state(belief_state)

    if strategic_state.my_role is None:
        return (ModeDirective(mode="idle", params=ModeParams()), None)

    evaluator = ROLE_EVALUATORS[strategic_state.my_role]
    return evaluator(strategic_state, belief_state, action_memory)
```

### Priority Evaluation Pattern

Each role evaluator checks conditions in strict priority order. The
first matching condition produces the mode directive. This ensures
the highest-priority unsatisfied objective always drives behavior.

```python
def evaluate_hades(state, belief, memory) -> tuple[ModeDirective, dict | None]:
    # Priority 1: Complete key exchange (prerequisite for ANY win)
    if not state.key_exchange_done:
        if state.key_partner_found and state.key_partner_room == state.my_room:
            # Partner here -- go get them
            return (ModeDirective(mode="probe_target", params=ProbeTargetParams(
                target=state.key_partner_id,
                intent=ProbeIntent.ROLE_EXCHANGE,
                skip_color_exchange=True,  # Already know they're Cerberus
            )), None)
        elif state.key_partner_found and state.key_partner_room != state.my_room:
            # Partner in other room -- can't communicate with them.
            # Cerberus's strategy says HE should volunteer as hostage.
            # We (Hades) should stay put (our room matters for positioning).
            # Best local action: seek leadership to control hostage picks
            # (maybe we can bring Cerberus here by requesting them via summit).
            # Fallback: continue probing in case our intel is wrong.
            if state.am_leader:
                return (ModeDirective(mode="hold_position", params=HoldPositionParams(
                    reason="leader_awaiting_summit_to_request_partner",
                    seek_leadership=False,
                )), None)
            else:
                # Cannot influence other room directly. Cerberus's strategy
                # prescribes volunteering as hostage -- trust shared strategy
                # convergence. Best local action: seek leadership to control
                # hostage picks (summit negotiation can request Cerberus).
                return (ModeDirective(mode="seek_leadership", params=SeekLeadershipParams(
                    reason="control_hostage_picks_for_partner_retrieval",
                )), None)
        elif not state.key_partner_found:
            # Partner not found -- systematic probing
            return (ModeDirective(mode="probe_systematic", params=ProbeSystematicParams(
                target_team=Team.SHADES,
                intent=ProbeIntent.FIND_KEY_PARTNER,
            )), None)

    # Priority 2: Locate enemy key role (Persephone)
    if state.key_exchange_done and state.enemy_key_role_room is None:
        return (ModeDirective(mode="probe_systematic", params=ProbeSystematicParams(
            target_team=None,  # Probe anyone for intel
            intent=ProbeIntent.LOCATE_ENEMY_KEY,
        )), None)

    # Priority 3: Ensure co-location with Persephone
    if state.key_exchange_done and state.enemy_key_role_room is not None:
        if state.enemy_key_role_room == state.my_room:
            # Same room -- defend position (DON'T seek leadership -- leaders can't be hostaged,
            # but we need to stay here, not be immune from movement. Actually leadership IS
            # good here: it prevents US from being moved away.)
            return (ModeDirective(mode="hold_position", params=HoldPositionParams(
                reason="co-located_with_target",
                seek_leadership=True,  # Prevents being hostaged away
            )), None)
        else:
            # Different room -- need to get there. Volunteer as hostage.
            # Do NOT seek leadership (leaders can't be hostaged).
            return (ModeDirective(mode="coordinate_cross_room", params=CrossRoomParams(
                who_should_move="self",
                reason="co_location",
            )), None)

    # Default: scout for opportunities
    return (ModeDirective(mode="scout", params=ScoutParams()), None)
```

### Role-Specific Evaluator Summaries

Each role evaluator follows the same priority-check pattern. The key
differences are in **what** conditions are checked and **which** mode
directives are produced.

**Important constraint re-stated:** There is NO cross-room communication.
When a role's partner or target is in the other room, the agent can only:
(a) try to get itself moved there, (b) try to get the target moved here
(if agent is leader), (c) use the leader summit to negotiate, or (d) fall
back to productive local actions while hoping for compatible behavior
from allies in the other room.

#### Hades

```
P1: key_exchange_not_done + partner_in_room     -> probe_target(Cerberus, role_exchange)
P2: key_exchange_not_done + partner_other_room  -> seek_leadership(control_hostage_picks)
    (Cannot influence other room. Cerberus's strategy prescribes volunteering as
     hostage -- trust shared strategy convergence. Hades seeks leadership to control
     hostage picks and use summit to request partner.)
P3: key_exchange_not_done + partner_unknown     -> probe_systematic(Shades, find_partner)
P4: key_exchange_done + persephone_unknown      -> probe_systematic(any, locate_enemy)
P5: key_exchange_done + persephone_same_room    -> hold_position(seek_leadership)
P6: key_exchange_done + persephone_other_room   -> coordinate_cross_room(self, co_location)
    (Hades must get to Persephone. Volunteer as hostage. Seek leadership is
     counterproductive -- leaders can't be hostaged.)
```

#### Cerberus

```
P1: key_exchange_not_done + partner_in_room     -> probe_target(Hades, role_exchange)
P2: key_exchange_not_done + partner_other_room  -> coordinate_cross_room(self, key_exchange)
    (Cerberus is the mobile one -- volunteer as hostage to reach Hades.)
P3: key_exchange_not_done + partner_unknown     -> probe_systematic(Shades, find_partner)
P4: key_exchange_done + persephone_unknown      -> probe_systematic(any, locate_enemy)
P5: key_exchange_done                           -> support_local(relay_intel_to_local_allies)
    (Help position Hades. If Hades is local, relay Persephone intel to him.
     If Hades is in other room, nothing we can do directly -- seek leadership
     to influence hostage picks that might help.)
```

#### Persephone

```
P1: key_exchange_not_done + partner_in_room     -> probe_target(Demeter, role_exchange)
P2: key_exchange_not_done + partner_other_room  -> hold_position(seek_leadership, defensive)
    (Cannot influence other room. Demeter's strategy prescribes volunteering as
     hostage -- trust shared strategy convergence. Persephone holds position and
     seeks leadership for hostage immunity and summit negotiation.)
P3: key_exchange_not_done + partner_unknown     -> probe_systematic(Nymphs, find_partner, cautious=True)
P4: key_exchange_done + hades_in_my_room + enemy_exchange_likely
                                                -> coordinate_cross_room(self, escape)
    (Hades is HERE and Shades may have completed their exchange too.
     Room co-location triggers tiebreaker favoring Shades. Must escape.)
P4b: key_exchange_done + hades_in_my_room + enemy_exchange_unknown
                                                -> hold_position(seek_leadership)
    (Hades is here but if Shades haven't exchanged, we already win
     regardless of room position. Seek leadership for immunity while
     monitoring for evidence of enemy exchange completion.)
P5: key_exchange_done + hades_unknown           -> hold_position(seek_leadership, defensive)
    (Unknown = 50/50 chance of separation. Stay put; leadership = immunity.)
P6: key_exchange_done + hades_other_room        -> hold_position(seek_leadership, safe)
    (Already separated. Hold. Leadership makes it permanent.)
```

**Tiebreaker nuance:** Room co-location only matters when BOTH teams
complete their key exchange (it determines which team is checked first
in the win condition). If only Nymphs complete theirs, Nymphs win
regardless of room. P4 therefore only fires when there's evidence the
enemy may have ALSO completed (behavioral flags: `relaxed_after_urgency`
on enemy key roles, Round 3 time pressure assumption, or direct
observation). Without such evidence, P4b applies -- hold position is
sufficient since our exchange alone guarantees victory.
```

#### Demeter

```
P1: key_exchange_not_done + partner_in_room     -> probe_target(Persephone, role_exchange)
P2: key_exchange_not_done + partner_other_room  -> coordinate_cross_room(self, key_exchange)
    (Demeter is mobile -- volunteer as hostage to reach Persephone.
     But FIRST check: is Hades in the other room? If so, going there
     puts both Demeter and eventually Persephone in Hades's room. Risky.)
P3: key_exchange_not_done + partner_unknown     -> probe_systematic(Nymphs, find_partner, aggressive)
P4: key_exchange_done + hades_unknown           -> probe_systematic(any, locate_hades)
P5: key_exchange_done                           -> hold_position(seek_leadership)
    (Protect Persephone via leadership. If Persephone is local, never send her.)
```

#### Shade (Grunt)

```
P1: room_composition_unknown                    -> probe_systematic(any, map_room)
P2: key_roles_need_help + am_leader             -> hostage_select(facilitate_key_meeting)
    (As leader, can directly send/keep players to help Hades-Cerberus meet)
P3: key_roles_need_help + not_leader            -> seek_leadership() OR volunteer_as_hostage
    (If Hades or Cerberus needs someone moved, and we're expendable:
     volunteer ourselves, or get leadership to control picks)
P4: leadership_useful + hostile_leader          -> usurp(coordinate_allies)
P5: enemy_key_role_located + local_ally_needs_it -> relay_intelligence(local_whisper)
P6: default                                     -> probe_systematic(any, disrupt) OR time_waste()
```

#### Nymph (Grunt)

```
P1: persephone_local + needs_protection         -> hold_position(seek_leadership)
    (If Persephone is here, our #1 job is ensuring she isn't hostaged away.
     Leadership is the best defense.)
P2: hostile_leader + hostage_threatens_persephone -> usurp(coordinate_allies)
P3: hades_location_unknown                      -> probe_systematic(Shades, find_hades)
P4: hades_located + persephone_local            -> relay_intelligence(tell_persephone)
P5: can_disrupt_shades_coordination             -> time_waste(shades_key_role)
P6: default                                     -> scout() OR decoy()
```

#### Spy (see Spy-Specific Design section)

```
P1: no_verified_ally_on_real_team               -> probe_target(real_ally, verify_self)
P2: high_value_target_accessible                -> infiltrate(target, maintain_cover)
P3: critical_intel_gathered + local_ally_exists  -> relay_intelligence(whisper_to_ally)
P4: round_3 + am_leader + decisive_action       -> hostage_select(sabotage)
P5: cover_blown                                 -> pivot_to_grunt_strategy()
P6: default                                     -> infiltrate_passively()
```

#### All Roles: Exchange-Impossible Endgame

When the key exchange becomes impossible, a final priority overrides
normal role logic:

```
P_FINAL (any key role): key_exchange_not_done + round_3 + partner_unreachable
    -> disrupt_enemy_exchange
    Rationale: If our exchange is impossible, the only remaining path to
    avoid a loss is ensuring the enemy ALSO fails their exchange (producing
    "nobody wins" -- a draw rather than a defeat).
```

`partner_unreachable` is true when ALL of:
- Partner is confirmed in other room (or never found after 2+ rounds
  of probing)
- We are in Round 3 (any phase from Playing3 onward)

**Why Round 3 = unreachable:** The game flow is
`[Playing -> HostageSelect -> LeaderSummit -> HostageExchange] x3 -> Reveal`.
If partner is in the other room at the start of Playing3:
- Playing3: different rooms, no shared whisper possible.
- HostageSelect3: partner still in other room.
- LeaderSummit3: chat only (no mechanical exchanges).
- HostageExchange3: partner MIGHT arrive, but...
- Reveal: no interaction phase follows. Zero time for R.OFFER + R.ACCPT.

Even if the partner is hostaged to our room in HostageExchange3, the
game proceeds directly to Reveal with no Playing time for the exchange.
Being hostaged ourselves to their room has the same problem. Therefore,
"partner in other room at Round 3 start" = definitively unreachable.

**Edge cases NOT considered unreachable:**
- Partner never found but only 1-2 rounds of probing done: partner might
  be in our room unidentified. Continue probing (probe_systematic).
- Partner in other room during Round 2: HostageExchange2 will move players
  before Playing3 begins. Partner may arrive. Not yet unreachable.

**`disrupt_enemy_exchange` behavior:**
- Locate enemy key roles (if known from prior probing)
- Time-waste them in whispers (burn their remaining interaction budget)
- If leader: send enemy key roles to opposite rooms (separate them)
- If not leader + majority available: usurp, then send them
- Global chat: misdirect ("HADES IS [wrong color]") to confuse coordination

**Correction on disruption:** Mutual role exchange does NOT "use up" an
exchange slot. The win condition checks whether the key pair exchanged
with EACH OTHER, not whether they exchanged with anyone at all. A player
can mutual-exchange with multiple people. Therefore, time-wasting and
misdirection are the only effective disruption tools -- not "tricking"
them into exchanging with the wrong person.

### Priority Override: Phase-Sensitive

Certain game phases override the role-specific priority system:

| Phase | Override |
|-------|---------|
| HostageSelect + am_leader | -> `hostage_select` mode (must pick before timer) |
| HostageSelect + not_leader + hostile_leader | -> `usurp` mode (if time permits) |
| LeaderSummit + am_leader | -> `summit_interact` mode |
| HostageExchange | -> `idle` mode (no input; perception + belief update still active) |
| RoleReveal | -> `idle` mode (absorb information; see Intro Sequence Behavior) |
| RosterReveal | -> `idle` mode (see Intro Sequence Behavior below) |

**HostageExchange intelligence (passive):** Although no input is accepted
during this 8-second phase, the exchange screen reveals:

- **Departing hostages** (leaving your room): full sprites with color and
  shape (player identification). Updates room assignments.
- **Arriving hostages** (coming to your room): same. Updates room
  assignments.
- **Your room's leader**: sprite (always visible).
- **Other room's leader**: sprite. **Only visible if YOU are a leader**
  (`renderer.ts:794-796`: `if (isLeader)` gates the other leader's
  sprite). Non-leaders cannot identify the other room's leader.

**Role indicators — server bug (may be patched):** The current renderer
(`renderExchangeRow`, `renderer.ts:760`) unconditionally calls
`drawRoleSlot(p.role, p.team)` on all exchange-screen sprites WITHOUT
checking `revealedTo` or `colorRevealedTo`. This bypasses the visibility
gates used in the overworld (where role indicators only render for
mechanically-discovered players). If exploited, this leaks true team and
key-role identity (Hades/Persephone/Cerberus/Demeter distinguishable by
dot patterns) for ALL shown sprites.

**Design stance:** This is inconsistent with the game's information
model and likely unintentional. Do NOT make it load-bearing in strategic
reasoning. Perception should extract role indicators from the exchange
screen opportunistically (free intelligence if present), but the
strategic layer must be correct even if this is patched to gate on
`revealedTo` like the overworld does. In other words: treat exchange-
screen role indicators as bonus confidence, not a reliable source.

The Orpheus belief update extracts this automatically. After each
HostageExchange completes, `meta_decide` should re-check the player
registry for newly-revealed room assignments -- this is guaranteed free
intelligence that requires no action.

### Intro Sequence Behavior

The intro sequence (RosterReveal + RoleReveal) is the most
information-dense moment of the game and requires active management
despite being "non-interactive" in the gameplay sense.

**Panel 0 -- Roster Reveal (phase = RosterReveal):**
- Remain on this panel for at least 48 ticks (2 seconds).
- Output idle (0x00) to prevent accidental advancement.
- This panel shows all players' room assignments -- critical for the
  strategic layer to know who starts where.
- After belief_state's player registry is populated with room assignments
  (confirmed by checking `len(players_with_known_room) == player_count`),
  advance to Panel 1 by pressing A/Right.

**Panel 1 -- Role Card (phase = RoleReveal):**
- Remain for at least 24 ticks (1 second).
- Extracts: own role, team, room assignment, room size.
- These populate the core identity fields in belief state.
- After `my_role` is populated in belief state, advance.

**Panel 2 -- Role Summary (phase = RoleReveal):**
- Remain for at least 24 ticks.
- Shows unique roles present in the match and any missing/echo substitutions.
- Critical for determining whether Spy is in the game (affects color
  exchange confidence levels).
- Current source classifies this as `RoleRevealPerception.panel_index == 2`
  and parses `match_roles`, `missing_roles`, `echo_substitutions`, and
  `spy_in_game_config`. Exact duplicate role counts are not rendered by the
  game and are therefore not available from this panel.

**Panel 3 -- Round Schedule (phase = RoleReveal):**
- Remain for at least 24 ticks.
- Shows round durations and hostage counts per round.
- Current source classifies this as `RoleRevealPerception.panel_index == 3`
  and parses visible rows into `round_schedule` as
  `(duration_secs, hostage_count)` tuples.
- After this panel, press A/Right to mark "ready" and begin the game.

**Implementation note:** The Orpheus perception module currently
uses a single `ROLE_REVEAL` view for panels 1-3, with
`RoleRevealPerception.panel_index` distinguishing role card, role summary,
and round schedule when OCR markers are visible. Panel content parsing is
still incomplete; see `IMPLEMENTATION_PLAN.md` Phase 1.

### Mode Hysteresis

Since `meta_decide` runs continuously (every tick, effectively), it must
implement its own stability logic to prevent mode thrashing. The framework
will apply ANY new ModeDirective that differs from current -- it's up to
`meta_decide` to not produce spurious switches.

**Implementation within meta_decide:**

```python
def meta_decide(belief_state, action_memory):
    strategic_state = build_strategic_state(belief_state)

    # Hysteresis: check if we should suppress mode switching
    current_mode = belief_state.ext.get("last_directive_mode")
    mode_active_since = belief_state.ext.get("last_directive_tick", 0)
    ticks_in_mode = belief_state.tick - mode_active_since

    # Rule 1: Minimum mode duration (2s) unless critical override
    if ticks_in_mode < 48 and not is_critical_override(strategic_state):
        return reaffirm_current_mode(current_mode)

    # Rule 2: Never interrupt in_whisper (whisper has its own timeout)
    if current_mode == "in_whisper" and belief_state.view == "whisper":
        return reaffirm_current_mode(current_mode)

    # Rule 3: Don't re-enter the same mode within 1s of exit
    last_exit_tick = belief_state.ext.get("last_mode_exit_tick", 0)
    if belief_state.tick - last_exit_tick < 24:
        candidate = evaluate_role(strategic_state, belief_state, action_memory)
        if candidate.mode_type == current_mode:
            return (ModeDirective(mode="scout", params=ScoutParams()), None)  # Fallback

    # Normal evaluation
    directive, inferences = evaluate_role(strategic_state, belief_state, action_memory)

    # Track what we produced in belief_state.ext (persistent across ticks).
    # Using ext instead of inferences avoids the fragility of needing every
    # code path to re-include hysteresis keys in the returned dict.
    belief_state.ext["last_directive_mode"] = directive.mode_type
    belief_state.ext["last_directive_tick"] = belief_state.tick

    return (directive, inferences)


def is_critical_override(state) -> bool:
    """Conditions that bypass mode hysteresis."""
    return (
        state.current_phase != state.ext.get("_last_phase")  # Phase changed
        or state.key_exchange_done != state.ext.get("_last_exchange_status")  # Exchange completed!
        or state.key_partner_found and not state.ext.get("_last_partner_found")  # Partner discovered!
    )
```

**Key principles:**
1. `meta_decide` must be **deterministic on stable input**: if belief
   state hasn't meaningfully changed, produce the same directive (which
   the framework treats as reaffirmation / no-op).
2. Mode "completion" is signaled by the inner loop writing
   `belief_state.ext["mode_complete"] = True`. meta_decide reads this
   and selects a new mode.
3. The `inferences` dict serves as meta_decide's cross-iteration
   memory (it's replaced wholesale each time, so meta_decide must
   re-include anything it wants to persist).

---

## Mode Specifications

### Mode Registry

| Mode | Purpose | Active During | Key Params |
|------|---------|---------------|------------|
| `idle` | No-op; absorb information | Non-interactive phases, transitions | reason: str |
| `scout` | Wander room, look for targets | Playing | -- |
| `probe_target` | Approach specific player, initiate whisper | Playing | target, intent |
| `probe_systematic` | Probe next-priority unknown player | Playing | target_team, intent |
| `in_whisper` | Execute whisper interaction protocol | Playing (whisper view) | occupants, intent, protocol |
| `hold_position` | Stay in room; resist movement | Playing, HostageSelect | seek_leadership, reason |
| `coordinate_cross_room` | Arrange cross-room movement | Playing, HostageSelect | who_moves, method |
| `seek_leadership` | Usurp current leader or maintain own | Playing, HostageSelect | reason |
| `hostage_select` | Leader selects hostages | HostageSelect | selection_strategy |
| `summit_interact` | Leader summit interaction | LeaderSummit | probe_strategy |
| `relay_intelligence` | Communicate intel via available channel | Playing | target_info, channel |
| `time_waste` | Keep enemy player occupied in whisper | Playing | target, stall_strategy |
| `decoy` | Impersonate key role to draw attention | Playing | impersonate_role |
| `usurp` | Coordinate majority vote against leader | Playing, HostageSelect | candidate, allies |
| `check_info_screen` | Proactively read info screen for knowledge validation | Playing | -- |

### Mode: `idle`

**Purpose:** Wait without acting. Used during non-interactive phases and
brief transitions.

**select_task behavior:**
- Returns `IdleTask()` every tick
- Monitors belief state for phase transitions
- Absorbs perception data passively (roster, role reveal, etc.)

**Enters when:** Game is in non-interactive phase, or between strategic
decisions.

**Exits when:** Phase transitions to an interactive phase, or
`meta_decide` selects a different mode.

---

### Mode: `scout`

**Purpose:** Move through the room looking for interaction opportunities.
The "default" mode when no higher-priority objective is active.

**Internal state:**
```python
@dataclass
class ScoutState:
    current_waypoint: tuple[int, int] | None = None
    waypoint_set_tick: int = 0
    waypoint_attempts: int = 0           # Times we've re-targeted same waypoint
    players_seen_this_sweep: set[PlayerID] = field(default_factory=set)
```

**select_task behavior (per tick):**
```python
def scout_select_task(belief_state, action_memory):
    scout_state = belief_state.ext["scout_state"]

    # Check: are we near an unprobed player?
    for player in visible_players(belief_state):
        if is_unprobed(player) and distance_to(player) < INTERACTION_RANGE:
            # Signal to meta_decide: we found a target
            belief_state.ext["mode_complete"] = True
            belief_state.ext["found_target"] = player.player_id
            return IdleTask()  # Wait for meta_decide to switch to probe_target

    # Check: waypoint reached or stale?
    if scout_state.current_waypoint is None:
        scout_state.current_waypoint = select_waypoint(belief_state)
        scout_state.waypoint_set_tick = belief_state.tick

    if reached_waypoint(belief_state, scout_state.current_waypoint):
        scout_state.current_waypoint = select_waypoint(belief_state)
        scout_state.waypoint_set_tick = belief_state.tick

    # Waypoint stale (stuck for >3s)? Pick new one.
    if belief_state.tick - scout_state.waypoint_set_tick > 72:
        scout_state.current_waypoint = select_waypoint(belief_state)
        scout_state.waypoint_set_tick = belief_state.tick

    return MoveToTask(scout_state.current_waypoint)
```

**Waypoint selection:**
```python
def select_waypoint(belief_state) -> tuple[int, int]:
    candidates = []

    # Priority 1: Last-known positions of unprobed players
    for player in all_known_players(belief_state):
        if is_unprobed(player) and player.last_seen_position:
            candidates.append((player.last_seen_position, 3.0))  # weight 3

    # Priority 2: Unexplored areas of the room (from occupancy grid)
    unexplored = get_unexplored_regions(belief_state)
    for region_center in unexplored:
        candidates.append((region_center, 1.0))  # weight 1

    # Priority 3: Room center (fallback -- neutral location equidistant from edges)
    room_center = get_room_center(belief_state)
    candidates.append((room_center, 0.5))

    # Weighted random selection (avoid deterministic loops)
    return weighted_random_choice(candidates)
```

**Exits when:**
- Finds an unprobed player in range (sets `mode_complete`)
- `meta_decide` overrides with higher priority
- Phase transitions to non-interactive (HostageSelect, etc.)

---

### Mode: `probe_target`

**Purpose:** Approach a specific known player and initiate a whisper.

**Params:**
```python
@dataclass
class ProbeTargetParams(ModeParams):
    target: PlayerID                      # Who to approach
    intent: ProbeIntent                   # Why (ROLE_EXCHANGE, FIND_KEY_PARTNER, LOCATE_ENEMY_KEY, etc.)
    skip_color_exchange: bool = False     # Already know their team
    max_approach_ticks: int = 96          # 4 seconds -- give up if can't reach
```

**select_task behavior:**
1. If target not visible: `MoveToTask(last_known_position)`. If position
   unknown, signal mode completion (can't execute).
2. If target visible and not in range: `MoveToTask(target.position)`.
3. If target in range and not in whisper: `CreateWhisperTask()` or
   `RequestWhisperEntryTask(target)` (if target is in a whisper).
4. If whisper created/entered: signal mode completion -> meta_decide
   should transition to `in_whisper`.

**Timeout:** If `max_approach_ticks` exceeded without reaching target,
signal mode completion with failure reason.

**Probe failure escalation:** Against evasive or uncooperative targets,
the probe cycle can fail at multiple points. Each failure type has a
specific escalation:

| Failure | Detection | Escalation |
|---------|-----------|-----------|
| Target runs away (2x) | Distance increasing over 48+ ticks despite pursuit | Mark `evasive`; skip to next target; infer `avoids_interaction` flag (possible key role) |
| Entry never granted | 72 ticks (3s) without grant | Abort; try creating OWN whisper near target next time (reverse flow) |
| Target exits immediately | Whisper duration <24 ticks before they leave | Note behavioral flag; infer reluctance; move on |
| Target ignores all offers | No response to C.OFFER within 72 ticks | Exit; target may be AFK, scripted, or hostile |

**Key insight:** Some opponents are simply unprobable. The agent must
accept this and reason from behavioral signals alone (evasion itself is
a strong signal of key-role identity). Never spend more than 2 failed
probe attempts on the same target per round.

---

### Mode: `probe_systematic`

**Purpose:** Select the highest-priority unprobed player and approach them.
Wraps target selection logic around `probe_target`.

**Params:**
```python
@dataclass
class ProbeSystematicParams(ModeParams):
    target_team: Team | None              # Filter to specific team (None = any)
    intent: ProbeIntent                   # Why we're probing
    cautious: bool = False                # (Persephone) Be selective about targets
    aggressive: bool = False              # (Demeter/Cerberus) Minimize time per probe
```

**Target prioritization algorithm:**

```python
def score_target(player: PlayerKnowledge, state: StrategicState) -> float:
    score = 0.0

    # Never re-probe fully identified players
    if player.role is not None and player.has_exchanged_roles_with_us:
        return -1.0  # Skip

    # Prefer unprobed over probed
    if player.times_interacted == 0:
        score += 50.0

    # Team filter bonus
    if state.target_team is not None:
        if player.team == state.target_team:
            score += 30.0
        elif player.team is not None and player.team != state.target_team:
            score -= 100.0  # Wrong team, skip

    # Proximity bonus (closer = less time wasted)
    distance = manhattan_distance(my_pos, player.last_seen_position)
    score += max(0, 40.0 - distance * 0.5)  # Closer = higher score

    # Behavioral suspicion bonus (might be key role)
    if 'exchange_eager' in player.behavioral_flags:
        score += 20.0
    if 'refuses_role_exchange' in player.behavioral_flags:
        score += 15.0

    # Staleness penalty (interacted recently = lower priority)
    ticks_since_interaction = current_tick - player.last_interaction_tick
    if ticks_since_interaction < 360:  # Same round
        score -= 40.0

    # Role-specific modifiers
    if state.intent == ProbeIntent.FIND_KEY_PARTNER:
        if player.team == state.my_team and not player.has_exchanged_roles_with_us:
            score += 40.0  # Same team, haven't verified role yet

    return score
```

**select_task behavior:**
1. Score all visible players using prioritization algorithm.
2. Select highest-scoring target.
3. Delegate to `probe_target` behavior (approach + whisper initiation).
4. If no valid targets: signal mode completion.

---

### Mode: `in_whisper`

**Purpose:** Execute the whisper interaction protocol. This is the most
complex mode and handles the core gameplay loop.

**Internal state:**
```python
@dataclass
class WhisperModeState:
    protocol: str                         # "standard" | "key_exchange" | "infiltration" | "stall"
    fsm_state: str                        # Current state in the state machine
    entered_tick: int                     # When we entered this whisper
    occupants_at_entry: list[PlayerID]    # Who was here when we arrived
    target_occupant: PlayerID | None      # Primary interaction target
    color_exchange_initiated: bool = False
    color_exchange_completed: bool = False
    role_exchange_initiated: bool = False
    role_exchange_completed: bool = False
    waiting_for_response_since: int = 0   # Tick when we last sent an action
    messages_sent: int = 0
    exit_initiated: bool = False
```

**select_task behavior (per tick):**
```python
def in_whisper_select_task(belief_state, action_memory):
    ws = belief_state.ext["whisper_mode_state"]
    current_tick = belief_state.tick

    # --- Forced ejection detection (phase transition kicked us out) ---
    if belief_state.view != "whisper" and not ws.exit_initiated:
        # Game force-ejected us (e.g., HostageExchange started)
        post_whisper_knowledge_update(ws, belief_state)
        belief_state.ext["mode_complete"] = True
        belief_state.ext["whisper_exit_reason"] = "forced_ejection"
        return IdleTask()

    # --- Handle incoming entry requests (every tick, before FSM) ---
    if belief_state.pending_entry is not None:
        requester = belief_state.pending_entry
        requester_knowledge = get_knowledge(requester)
        # Deny during sensitive operations (key exchange, role exchange)
        if ws.protocol == "key_exchange" or ws.fsm_state == "ROLE_EXCHANGE":
            pass  # Ignore; will timeout after 240 ticks
        elif is_probable_ally(requester_knowledge, belief_state):
            return MenuNavTask("GRANT")  # Let allies in
        # Enemies and unknowns: ignore (auto-timeout)

    # --- Monitor for new hostile entrants mid-interaction ---
    current_occupants = get_whisper_occupants(belief_state)
    new_entrants = set(current_occupants) - set(ws.occupants_at_entry)
    if new_entrants:
        for entrant in new_entrants:
            if is_confirmed_enemy(entrant, belief_state):
                # Hostile entered during our interaction -- abort if sensitive
                if ws.fsm_state in ("ROLE_EXCHANGE", "COLOR_EXCHANGE") and not ws.role_exchange_completed:
                    ws.fsm_state = "EXIT"
                    return IdleTask()
        ws.occupants_at_entry = current_occupants  # Update tracked list

    # --- Global timeout check ---
    elapsed = current_tick - ws.entered_tick
    max_duration = PROTOCOL_TIMEOUTS[ws.protocol]
    if elapsed > max_duration:
        ws.fsm_state = "EXIT"

    # Rate limit check: can't act if action cooldown active
    if action_memory.ticks_since_last_command < 48:  # 2s action cooldown
        return IdleTask()  # Wait for cooldown

    # State machine dispatch
    match ws.fsm_state:
        case "ENTER":
            return handle_enter(ws, belief_state)
        case "ASSESS":
            return handle_assess(ws, belief_state)
        case "COLOR_EXCHANGE":
            return handle_color_exchange(ws, belief_state, action_memory)
        case "EVALUATE":
            return handle_evaluate(ws, belief_state)
        case "ROLE_EXCHANGE":
            return handle_role_exchange(ws, belief_state, action_memory)
        case "EXTRACT":
            return handle_extract(ws, belief_state, action_memory)
        case "STALL":
            return handle_stall(ws, belief_state, action_memory)
        case "EXIT":
            return handle_exit(ws, belief_state)


def handle_enter(ws, belief_state):
    """First tick in whisper. Orient, select target, assess safety."""
    # Perception should now show whisper view
    if belief_state.view == "whisper":
        ws.occupants_at_entry = get_whisper_occupants(belief_state)

        # Select target by priority (not arbitrary [0]):
        # 1. Known key partner (critical exchange)
        # 2. Unknown-team player (highest information value)
        # 3. Same-team unverified player (role verification)
        # 4. Known enemy (extract intel or stall)
        ws.target_occupant = select_whisper_target(ws.occupants_at_entry, belief_state)

        # Assess eavesdrop risk: hostile occupant present?
        ws.hostile_present = any(
            is_confirmed_enemy(occ, belief_state) for occ in ws.occupants_at_entry
        )
        # If hostile is watching and we intend a key exchange, abort immediately.
        # They would observe the system messages revealing our identity.
        if ws.hostile_present and ws.protocol == "key_exchange":
            ws.fsm_state = "EXIT"
            return IdleTask()

        ws.fsm_state = "ASSESS"
    return IdleTask()  # Wait one tick for perception to stabilize


def select_whisper_target(occupants: list[PlayerID], belief_state) -> PlayerID | None:
    """Select highest-priority interaction target from whisper occupants."""
    if not occupants:
        return None

    knowledge = belief_state.ext["player_knowledge"]
    my_team = belief_state.ext["my_team"]
    key_partner_id = belief_state.ext.get("key_partner_id")

    # Priority 1: Key partner present -> immediate exchange target
    if key_partner_id and key_partner_id in occupants:
        return key_partner_id

    scored = []
    for occ_id in occupants:
        k = knowledge.get(occ_id)
        score = 0.0
        if k is None or k.team is None:
            score += 50.0  # Unknown: highest info value
        elif k.team == my_team and not k.has_exchanged_roles_with_us:
            score += 40.0  # Same team, unverified role
        elif k.team != my_team:
            score += 10.0  # Enemy: some intel value
        else:
            score += 5.0   # Already fully known
        scored.append((occ_id, score))

    scored.sort(key=lambda x: -x[1])
    return scored[0][0]


def handle_assess(ws, belief_state):
    """Check what we already know about occupants. Decide protocol path."""
    knowledge = get_knowledge(ws.target_occupant)

    # --- Multi-occupant eavesdrop guard ---
    # System messages from exchanges are visible to ALL occupants.
    # If >2 occupants and any non-target is hostile/unknown, exchanges
    # would leak our team/role to them. Key roles must not take this risk.
    occupant_count = len(get_whisper_occupants(belief_state))
    if occupant_count > 2:
        my_role = belief_state.ext["my_role"]
        non_targets = [o for o in get_whisper_occupants(belief_state)
                       if o != ws.target_occupant]
        hostile_or_unknown_witness = any(
            is_confirmed_enemy(o, belief_state) or get_knowledge(o).team is None
            for o in non_targets
        )
        if hostile_or_unknown_witness:
            if my_role in (Role.HADES, Role.PERSEPHONE, Role.CERBERUS, Role.DEMETER):
                # Key roles: abort -- information leakage too dangerous
                ws.fsm_state = "EXIT"
                return IdleTask()
            # Grunts: proceed anyway (leaking "Shade" or "Nymph" is low-cost)

    # If this is a key exchange protocol, skip straight to role exchange
    if ws.protocol == "key_exchange":
        ws.fsm_state = "ROLE_EXCHANGE"
        return IdleTask()

    # If we already know their team (from prior interaction), skip color exchange
    if knowledge and knowledge.team is not None:
        ws.fsm_state = "EVALUATE"
        return IdleTask()

    # Default: proceed to color exchange
    ws.fsm_state = "COLOR_EXCHANGE"
    return IdleTask()


def handle_color_exchange(ws, belief_state, action_memory):
    """Execute or respond to color exchange."""
    # Check if THEY already offered (reactive path)
    if belief_state.ext.get("incoming_color_offer"):
        ws.fsm_state = "COLOR_EXCHANGE_RESPONDING"
        return MenuNavTask("C.ACCPT")  # Accept their offer

    # Check if WE already offered and are waiting
    if ws.color_exchange_initiated:
        # Check for completion (system message "swapped colors")
        if belief_state.ext.get("color_exchange_completed"):
            ws.color_exchange_completed = True
            ws.fsm_state = "EVALUATE"
            return IdleTask()
        # Check for timeout (3s without response)
        if belief_state.tick - ws.waiting_for_response_since > 72:
            ws.fsm_state = "EXIT"  # They're not responding; leave
            return IdleTask()
        return IdleTask()  # Keep waiting

    # Initiate color exchange
    ws.color_exchange_initiated = True
    ws.waiting_for_response_since = belief_state.tick
    return MenuNavTask("C.OFFER")


def handle_evaluate(ws, belief_state):
    """Decide next action based on revealed team."""
    target_team = get_knowledge(ws.target_occupant).team
    my_role = belief_state.ext["my_role"]
    intent = ws.protocol  # Or derived from mode params

    next_state = evaluate_after_color(target_team, my_role, intent)
    ws.fsm_state = next_state  # "ROLE_EXCHANGE" | "EXTRACT" | "STALL" | "EXIT"
    return IdleTask()


def handle_role_exchange(ws, belief_state, action_memory):
    """Execute or respond to role exchange."""
    # Check if THEY offered (reactive)
    if belief_state.ext.get("incoming_role_offer"):
        should_accept = evaluate_role_exchange_acceptance(
            ws.target_occupant, belief_state
        )
        if should_accept:
            return MenuNavTask("R.ACCPT")
        else:
            ws.fsm_state = "EXIT"  # Decline by leaving
            return IdleTask()

    # Check if WE already offered and are waiting
    if ws.role_exchange_initiated:
        if belief_state.ext.get("role_exchange_completed"):
            ws.role_exchange_completed = True
            # Update knowledge immediately
            update_knowledge_from_exchange(ws.target_occupant, belief_state)
            ws.fsm_state = "EXIT"
            return IdleTask()
        if belief_state.tick - ws.waiting_for_response_since > 72:
            ws.fsm_state = "EXIT"  # No response
            return IdleTask()
        return IdleTask()

    # Initiate role exchange
    ws.role_exchange_initiated = True
    ws.waiting_for_response_since = belief_state.tick
    return MenuNavTask("R.OFFER")


def handle_extract(ws, belief_state, action_memory):
    """Chat-based intel gathering. Send a probe question, read response."""
    # Send one message if we haven't yet
    if ws.messages_sent == 0:
        ws.messages_sent += 1
        message = compose_probe_message(ws, belief_state)
        return SendChatTask(message)

    # Wait a few seconds for response, then exit
    if belief_state.tick - ws.waiting_for_response_since > 96:  # 4s
        ws.fsm_state = "EXIT"
    return IdleTask()


def handle_stall(ws, belief_state, action_memory):
    """Time-wasting protocol. Slow responses, fake interest."""
    elapsed = belief_state.tick - ws.entered_tick

    # Stall actions at intervals: send messages every ~4s
    if ws.messages_sent == 0 and elapsed > 48:
        ws.messages_sent += 1
        return SendChatTask("THINKING")
    if ws.messages_sent == 1 and elapsed > 144:
        ws.messages_sent += 1
        return SendChatTask("WHO ARE YOU")
    if ws.messages_sent == 2 and elapsed > 240:
        # Offer color exchange (further time sink)
        return MenuNavTask("C.OFFER")

    # Exit after stall timeout
    if elapsed > PROTOCOL_TIMEOUTS["stall"]:
        ws.fsm_state = "EXIT"

    return IdleTask()


def handle_exit(ws, belief_state):
    """Leave the whisper."""
    if not ws.exit_initiated:
        ws.exit_initiated = True
        return MenuNavTask("EXIT")

    # Wait for overworld view to confirm exit
    if belief_state.view != "whisper":
        # Post-exit: update knowledge, mark mode complete
        post_whisper_knowledge_update(ws, belief_state)
        belief_state.ext["mode_complete"] = True
        return IdleTask()

    return IdleTask()  # Still exiting
```

### Whisper Exchange State Derivation

The whisper FSM relies on structured exchange-state fields
(`incoming_color_offer`, `color_exchange_completed`,
`role_exchange_completed`, etc.) that are NOT part of the base Orpheus
belief state schema. Eurydice derives these from raw observations via
its `post_belief_update` hook.

**Implementation:** The hook scans `belief_state.chat_history` each tick
for new system messages (identified by color 8 rendering, no sender
sprite prefix) and pattern-matches against known templates:

| System Message Text | Derived State Update |
|--------------------|--------------------|
| "offered color" | `whisper_exchange_state.active_color_offers` += sender |
| "swapped colors" | `whisper_exchange_state.color_exchange_completed` = True; clear offers |
| "offered role" | `whisper_exchange_state.active_role_offers` += sender |
| "shared roles" | `whisper_exchange_state.role_exchange_completed` = True; clear offers |
| "withdrew" | Clear relevant offer from sender |
| "showed role" | `whisper_exchange_state.one_way_reveal` = sender |
| "offered lead" | `whisper_exchange_state.leadership_offer_pending` = True |

**Attribution challenge:** When multiple occupants are present, system
messages don't explicitly name the actor. Attribution uses temporal
heuristics:
1. The most recent action (within 48 ticks / 2s cooldown) was likely
   triggered by the occupant who was idle longest (their cooldown expired).
2. "swapped colors" / "shared roles" involve exactly two participants --
   one of whom is us (if we initiated) or the offerer (from prior "offered"
   message).
3. When attribution is ambiguous, mark the event but leave the actor as
   `None` -- the FSM handles this conservatively.

**OCR error resilience:** System message detection is critical for the
win condition (detecting exchange completion). Three layers of defense
against OCR misreads:

1. **Substring matching, not exact:** Match on "SWAP" (not full "SWAPPED
   COLORS"), "SHARED" (not full "SHARED ROLES"), "OFFER" (not full
   "OFFERED COLOR/ROLE"). Shorter patterns are less likely to be
   corrupted by a single-character OCR error.
2. **Redundant inference:** If we sent R.OFFER and the next system
   message from that whisper contains any of {"SHARED", "ROLE"}, infer
   completion even if the full text is garbled. Track (offer_sent_tick,
   offer_type) and match against any subsequent system message within
   120 ticks.
3. **Info-screen reconciliation:** After exiting a whisper where an
   exchange may have completed, tab to info screen. If the target player
   now appears with a role indicator (full role known), the exchange
   succeeded regardless of whether we parsed the system message. This is
   the ground-truth fallback.

**Current source status:** Orpheus now provides structured whisper fields
(`active_color_offers`, `active_role_offers`, `last_exchange_event`, and
`my_exchange_partner`), but attribution in crowded whispers still needs
work. Eurydice should consume those structured fields rather than duplicate
chat parsing. Additional source gaps that still affect Eurydice:
- **Panel content parsing:** panel index classification exists, but role
  summary contents are not structured yet. Round schedule rows are parsed.
- **Visible non-bubble sprites:** ordinary overworld players without speech
  bubbles are exposed as direct observations, including visible role
  indicators. This still needs live-frame validation in fog/obstacle cases.

See the full **Whisper Interaction Protocol** section below for the
protocol variants and detailed state transition rules.

---

### Mode: `hold_position`

**Purpose:** Stay in current room. Resist being moved. Optionally seek
leadership (which provides hostage immunity).

**Params:**
```python
@dataclass
class HoldPositionParams(ModeParams):
    seek_leadership: bool = False         # Try to become/maintain leader
    reason: str = ""                      # Why holding (for logging)
```

**Internal state:**
```python
@dataclass
class HoldPositionState:
    leadership_attempted: bool = False
    usurp_vote_cast: bool = False
    idle_wander_waypoint: tuple[int, int] | None = None
```

**select_task behavior (per tick):**
```python
def hold_position_select_task(belief_state, action_memory):
    state = belief_state.ext["hold_position_state"]
    params = current_mode_params()

    # If we should seek leadership and don't have it
    if params.seek_leadership and not belief_state.am_leader:
        leader_team = get_leader_team(belief_state)

        # If leader is hostile and usurp is achievable
        if leader_team is not None and leader_team != my_team:
            if not state.usurp_vote_cast and can_usurp(belief_state):
                # Usurp via global chat view
                state.usurp_vote_cast = True
                return ViewGlobalChatTask()  # Opens chat; next tick: navigate usurp selector

        # If leader is ally, we're safe -- they won't send us
        # If leader is unknown, wait for more info

    # If we ARE leader: stay here, maintain position
    if belief_state.am_leader:
        # Check if someone approaches with whisper request
        if has_pending_whisper_request(belief_state):
            # Enter whisper if requester is likely ally (intel opportunity)
            requester = get_whisper_requester(belief_state)
            if is_probable_ally(requester):
                return GrantWhisperEntryTask(requester)

        # Otherwise: gentle idle movement (don't stand perfectly still
        # as that's a behavioral flag for "defensive_posture")
        return gentle_wander(state)

    # If we're not leader and not seeking leadership:
    # Just exist in the room. Gentle movement. Respond to whisper
    # requests from allies. Don't initiate interactions.
    if has_pending_whisper_request(belief_state):
        requester = get_whisper_requester(belief_state)
        if is_probable_ally(requester):
            return GrantWhisperEntryTask(requester)

    return gentle_wander(state)


def gentle_wander(state) -> Task:
    """Move slightly to avoid behavioral detection, but stay in room center.

    Note: the behavioral camouflage rationale (avoiding "defensive_posture"
    flag) only matters against other Eurydice agents. Against non-Eurydice
    opponents this is harmless idle behavior. The low cost (no probe time
    consumed, no information revealed) makes it acceptable as a default.
    In longer rounds (>60s), consider replacing with productive actions
    (check info screen, read global chat) if no higher-priority mode fires.
    """
    if state.idle_wander_waypoint is None or reached(state.idle_wander_waypoint):
        # Pick a point near room center (within 20px radius)
        state.idle_wander_waypoint = random_near(room_center, radius=20)
    return MoveToTask(state.idle_wander_waypoint)
```

**Anti-hostage sub-behavior (during HostageSelect phase):**

When phase transitions to HostageSelect and we're not leader:
- If leader is ally: no action needed (trust them)
- If leader is enemy: signal to meta_decide that `usurp` is needed
  (but by HostageSelect, usurp may be too late -- this is why
  proactive usurp in Playing phase is important)
- We cannot prevent being selected. The only defenses are:
  (a) being leader ourselves, or (b) having an ally as leader

---

### Mode: `coordinate_cross_room`

**Purpose:** Influence the hostage exchange to move a player (self or
other) between rooms. This is one of the hardest strategic problems in
the game.

**Critical constraint: NO CROSS-ROOM COMMUNICATION.**

Global chat is **room-local** -- only players in the same room can see
messages. There is NO mechanism for communicating with the other room
except:

1. **Leader Summit** -- the ONLY moment two players from different rooms
   can interact directly (forced whisper between leaders).
2. **Hostage movement** -- a player physically moves to the other room
   and can then communicate there.
3. **Pre-separation knowledge** -- information shared before a player
   was hostaged away persists in their memory.

This means "coordinate with an ally in the other room" is mostly
**impossible in real-time**. Cross-room strategy must be:
- Decided by the leader during summit
- Pre-arranged via shared strategic understanding (both Eurydice agents
  playing optimally will make compatible decisions without explicit
  coordination)
- Achieved through unilateral action on YOUR side of the divide

**Params:**
```python
@dataclass
class CrossRoomParams(ModeParams):
    who_should_move: str                  # "self" | "target_in_my_room"
    reason: str                           # "key_exchange" | "co_location" | "escape"
```

**Available methods (priority order):**

1. **I am leader → select target as hostage.**
   If the player who needs to move is in MY room and I'm leader, I can
   send them directly during HostageSelect. This is the only guaranteed
   method.

2. **I want to move → signal willingness to local leader.**
   Approach my room's leader. Whisper with them. Send "SEND ME" message.
   Or use global chat "SEND ME" (leader can see it, same room).
   Whether the leader acts on this depends on THEIR priorities.

3. **I am leader → use summit to coordinate.**
   During Leader Summit, I meet the other room's leader. I can negotiate:
   "Send me [color] and I'll send you [color]." This is the ONLY
   real-time cross-room negotiation channel.

4. **Implicit coordination via shared strategy.**
   If both Eurydice agents are playing the same role-specific strategy,
   they will independently arrive at compatible decisions. E.g., Cerberus
   always volunteers as hostage when Hades is in the other room;
   a Shade leader in the other room "knows" to send Cerberus across
   because that's what the strategy prescribes.

5. **Accept randomness.**
   If no method is available, the hostage exchange may randomly help
   (auto-fill selects random eligible players). This is a last resort.

**What this mode CANNOT do:**
- Tell an ally in the other room what to do
- Send a message to the other room
- Know what's happening in the other room (except via summit)

**select_task behavior:**
1. Assess which methods are available given current state.
2. If `who_should_move == "self"` and I'm not leader:
   - Find local leader → approach → whisper → request "SEND ME"
   - If leader unavailable: global chat "SEND ME" (room-local, leader sees)
3. If `who_should_move == "target_in_my_room"` and I'm leader:
   - Set a flag for `hostage_select` mode to pick this target
   - Wait for HostageSelect phase
4. If I'm leader and summit is upcoming:
   - Prepare summit negotiation strategy (what to request from other leader)

**Key insight:** `coordinate_cross_room` is only produced when the agent
CAN take meaningful action (is leader and can select hostages, or wants
to volunteer itself). When direct action is impossible (partner in other
room, not leader), the evaluator produces an appropriate local mode
directly (seek_leadership, hold_position, probe_systematic) rather than
delegating to a mode that would immediately give up.

---

### Mode: `seek_leadership`

**Purpose:** Become or maintain room leader via usurp mechanics.

**Timing constraint:** Leaders are randomly reassigned at the start of
each round. A successful usurp grants leadership only for the remainder
of the current round (through HostageSelect). Investment in usurp is
only worthwhile when HostageSelect is upcoming and the current leader
threatens team positioning. Pursuing usurp early in Playing phase is
still valuable because it secures control of the imminent HostageSelect.

**select_task behavior:**
1. Open global chat view (`ViewGlobalChatTask`).
2. Navigate usurp candidate selector to "ME" (or ally candidate).
3. Cast vote for self/ally.
4. Monitor for usurp success/failure.
5. If already leader: maintain position (don't pass leadership unless
   strategically beneficial).

**Coordination:** Usurp requires `floor(room_size / 2) + 1` votes.
In a 5-person room, that's 3 votes. The agent must:
- Know how many allies are in the room
- Estimate whether majority is achievable
- Consider timing (usurp must complete before hostage select)

---

### Mode: `hostage_select`

**Purpose:** As leader, select hostages strategically during HostageSelect.

**Selection algorithm:**

```python
def select_hostage(state: StrategicState, players: list[PlayerKnowledge]) -> PlayerID:
    # Eligible: all players in room except self (leader exempt)
    eligible = [p for p in players if p.player_id != state.my_player_id]

    # Priority 0: Honor "SEND ME" requests from confirmed allies
    # This enables shared-strategy convergence (e.g., Cerberus volunteering
    # to cross rooms to reach Hades). Only honor requests from players whose
    # team is verified (color_exchange or role_exchange source).
    volunteer = find_ally_volunteer(state, eligible)
    if volunteer is not None:
        return volunteer

    if state.my_team == Team.SHADES:
        return select_hostage_shades(state, eligible)
    else:
        return select_hostage_nymphs(state, eligible)


def find_ally_volunteer(state: StrategicState, eligible: list[PlayerKnowledge]) -> PlayerID | None:
    """Check if a confirmed ally has requested to be sent via chat."""
    for p in eligible:
        # Must be confirmed same-team (not just claimed)
        if p.team != state.my_team:
            continue
        if p.team_source not in ("color_exchange", "role_exchange"):
            continue
        # Check for pending "send_hostage" action request targeting "self"
        if has_send_me_request(p.player_id, state):
            # Safety: never send our own key roles even if they ask
            # (unless they explicitly need to cross for exchange -- checked
            # by whether key_exchange_done is False and partner is in other room)
            if p.role in (Role.HADES, Role.PERSEPHONE) and state.key_exchange_done:
                continue  # Key role asking to move AFTER exchange = suspicious
            return p.player_id
    return None


def select_hostage_shades(state, eligible):
    # Priority 1: Send Nymph to make room for incoming ally
    # Priority 2: Send Persephone to Hades's room (if we know both locations)
    # Priority 3: Remove Nymph intelligence asset
    # Priority 4: Never send Hades or Cerberus (unless they need to cross)

    if state.enemy_key_role_room == state.my_room:
        # Persephone is HERE -- do NOT send her away from Hades
        pass  # Actually: keep her here if Hades is also here

    # If Cerberus needs to go to other room for exchange:
    if not state.key_exchange_done and state.key_partner_room == "other":
        # DON'T send Cerberus -- he needs to COME here
        # Instead send a Nymph to "make room"
        nymphs = [p for p in eligible if p.team == Team.NYMPHS]
        if nymphs:
            return nymphs[0].player_id

    # Default: send least-valuable-to-us player
    # (confirmed Nymph grunt > unknown > confirmed Shade grunt; never key roles)
    ...


def select_hostage_nymphs(state, eligible):
    # Priority 1: NEVER send Persephone
    # Priority 2: Send Hades away from Persephone (if Persephone is here)
    # Priority 3: Send Shades player (weakens their local network)
    # Priority 4: Self-sacrifice (grunt) if it helps positioning

    persephone_here = any(p.role == Role.PERSEPHONE for p in eligible)
    if persephone_here:
        # Absolutely never select Persephone
        eligible = [p for p in eligible if p.role != Role.PERSEPHONE]

    hades_here = [p for p in eligible if p.role == Role.HADES]
    if hades_here and persephone_here:
        # Send Hades AWAY -- this separates them
        return hades_here[0].player_id

    shades = [p for p in eligible if p.team == Team.SHADES]
    if shades:
        return shades[0].player_id

    # Default: send self (grunt sacrifice) or random
    ...
```

---

### Mode: `summit_interact`

**Purpose:** Interact with opposing leader during the forced Leader Summit
whisper.

**Available actions during summit:** The whisper action menu is blocked
during LeaderSummit (`sim.ts:544` gates B-button on `!isSummit`). The
summit creates a fresh whisper with empty offer sets, and since no
player can open the action menu, no offers can be initiated. This means:

- **NOT available:** C.OFFER, C.ACCPT, R.OFFER, R.ACCPT, PASS, TAKE,
  GRANT, EXIT — all require the action menu which cannot be opened.
- **Available:** Chat messages (PACKET_CHAT) — always routed to the
  summit whisper occupants.
- **Available:** Tab cycling (Left/Right) — switches between whisper,
  shout (global chat), and info screen surfaces. The player remains
  `inWhisper` but the rendered view changes.
- **Available:** Message scrolling (Up/Down).
- **NOT available:** Leave whisper (Select button also gated by
  `!isSummit`). The summit ends only when its timer expires; leaders
  are returned to their rooms automatically.

**Implication:** The summit is a **chat-only** interaction window. No
mechanical information exchange (color/role) is possible. Its value is
entirely in:
1. Social engineering via text messages (probing, misdirection, negotiation)
2. Observing the other leader's responses (evasion = signal)
3. Reading global chat from your room (tab to shout view)
4. Checking info screen for knowledge validation (tab to info view)

**Strategy varies by situation:**

| Situation | Strategy |
|-----------|----------|
| Unknown opposing leader's team | Probe via chat ("WHAT TEAM"); read behavioral cues from response |
| Confirmed enemy leader | Extract intel via questions; misdirect about own room composition |
| Confirmed ally leader (rare) | Coordinate hostage strategy; share room intel; agree on picks |
| I have critical intel to trade | Negotiate verbally ("I'LL SEND [color] IF YOU SEND [color]") |
| I'm a Spy maintaining cover | Act as expected team member in chat |

**select_task behavior:**
1. Send a probing chat message (identity question or negotiation opener).
2. Tab to info screen briefly (validate known-player state; 2-3 ticks).
3. Tab back to whisper; read any response from the other leader.
4. Based on response, execute role-appropriate follow-up:
   - **Shades leader vs suspected Nymphs leader:** Probe for Persephone
     location. Offer misleading hostage deals. "I'LL SEND YOU [color]
     IF YOU TELL ME WHERE PERSEPHONE IS."
   - **Nymphs leader vs suspected Shades leader:** Probe for Hades
     location. Misdirect about Persephone's location. Propose trades
     that benefit Nymphs positioning.
   - **Same team:** Share room composition intel. Agree on hostage
     strategy. "I HAVE [key role] HERE SEND ME [partner]."
5. Tab to shout view before summit ends (read any global chat from own
   room that accumulated during the summit).

**Chat rate limit during summit:** Whisper chat has a 2-second (48-tick)
cooldown. With 15 seconds of summit time, that's a maximum of ~7
messages. Budget them carefully.

**Strategic value reassessment:** Given that the summit is chat-only,
its value is lower than if mechanical exchanges were possible. However,
it remains the ONLY cross-room interaction point. Verbal agreements are
non-binding (lies are free), but the other leader's responses (or
refusal to respond) carry behavioral signal. A leader who immediately
asks about a specific player color may be revealing their team's search
target.

---

### Mode: `relay_intelligence`

**Purpose:** Communicate gathered intelligence to allies who are in the
**same room**.

**Critical constraint:** Intelligence can ONLY be relayed to players in
your current room. There is no mechanism to communicate with the other
room during Playing phase. If the ally who needs the intel is in the
other room, you must either:
- Wait for summit (if you're leader)
- Wait for them to be hostaged to you
- Act on the intel yourself (adjust your own behavior)

**Channel selection (same-room only):**

| Channel | When to Use | Pros | Cons |
|---------|-------------|------|------|
| Whisper with ally | Ally is nearby and reachable | Private; enemies can't hear | Costs probe cycle time |
| Global chat | Need all local allies to hear; or ally far away | Immediate; no approach needed | Enemies in room also see it |

**select_task behavior:**
1. Identify target ally (specific player, or "all local allies").
2. If specific ally and ally is reachable: approach → whisper → share.
3. If broadcast to room: open global chat → send message.
4. Rate limit awareness: global chat has 10s cooldown. Don't waste it.
5. Mark intel as relayed once sent.

**When this mode fires:**
- We identified Hades/Persephone and a local ally needs to know
- We learned enemy exchange status and local key role needs to adjust
- A grunt discovered something that affects local team strategy

---

### Mode: `time_waste`

**Purpose:** Occupy an enemy player in a whisper to consume their limited
interaction time.

**Stall strategies:**
- Pretend to consider their offers (don't accept/decline immediately)
- Ask probing questions via chat ("who are you looking for?")
- Offer color exchange (costs them time even if mutual)
- Appear conflicted about role exchange ("I need to think about it")
- Exit just before they would give up (maximizes time wasted)

**select_task behavior:**
1. If not in whisper with target: approach and create/join whisper.
2. If in whisper: execute stall protocol (see Whisper Protocol, stall variant).
3. Target time: 8-10 seconds of their round consumed.
4. Exit when they seem about to leave (prevents them from extracting value).

---

### Mode: `decoy`

**Purpose:** Impersonate a key role (as a grunt) to draw enemy attention
away from the real key role.

**Params:**
```python
@dataclass
class DecoyParams(ModeParams):
    impersonate_role: Role                # Who to pretend to be
    channel: str                          # "global_chat" | "behavioral" | "both"
```

**Decoy behaviors:**
- **Global chat:** Send messages claiming to be key role ("I'M PERSEPHONE"
  or acting urgent about finding a partner).
- **Behavioral:** Act like the key role would (defensive posture for
  Persephone, aggressive probing for Hades).
- **Accept investigation:** When enemies approach to verify, waste their
  time in whisper before they discover the truth.

**Risk:** Enemies eventually role-exchange with you and discover "Nymph"
or "Shade." This is acceptable -- the time waste already happened.

---

### Mode: `usurp`

**Purpose:** Coordinate a majority vote to replace the current leader.

**Prerequisites:**
- Current leader is hostile (enemy team) or unhelpful
- Majority is achievable (enough allies in room)
- Timing: must complete before hostage select to matter

**select_task behavior:**
1. Count allies in room. Estimate vote count.
2. If majority achievable: open global chat, navigate to usurp selector.
3. Vote for self (or coordinated ally candidate).
4. Monitor for success (system message: "[player] is now leader").
5. If usurp fails (not enough votes): signal mode completion.

**Coordination:** Usurp relies on implicit coordination rather than
explicit pre-vote whispers (which cost 3-5s and may not complete before
HostageSelect). All Eurydice agents running `should_usurp()` with the
same knowledge base will independently vote for the same candidate
(deterministic evaluator). If team allies have compatible knowledge
(from shared probing), votes converge without communication. Known
limitation: against non-Eurydice allies, usurp may fail due to
uncoordinated votes.

### Mode: `check_info_screen`

**Purpose:** Validate accumulated knowledge against the game's
mechanically-revealed state. The info screen shows players whose roles
or colors have been revealed TO the viewer via mechanical exchanges.

**What the info screen actually shows** (GAME_API §Info Screen):
- Players you have done a mutual role exchange with: full role indicator
  + role name in team color
- Players you have done a color exchange with: team-color dot + "???"
- Self: always shown first with full role indicator
- Scroll support for long lists

**Primary value:** OCR error recovery. If a system message was missed
(exchange completed but "shared roles" text was garbled), the info
screen provides ground-truth confirmation. Also catches one-way reveals
(ROLE action) that might have been missed in whisper message parsing.

**When to trigger:** Integrated into the post-whisper-exit routine
rather than as a standalone mode. After exiting any whisper where an
exchange MAY have occurred (we sent or received an offer), tab to info
screen for 2-3 ticks to confirm state. This is cheaper than a dedicated
mode and catches errors at the point of highest value.

**Fallback as standalone mode:** If the post-whisper check isn't
sufficient (e.g., missed an exchange that happened in a whisper we
weren't in -- another player showed us their role), trigger once per
round as a reconciliation pass during a convenient transition (entering
global chat view to read messages → tab to info → tab back).

**select_task behavior:**
1. If currently in whisper or global chat view: cycle Left/Right to
   reach info screen surface.
2. Allow perception to parse the known-players list (2-3 ticks).
3. Compare parsed info against `PlayerKnowledge` records.
4. Update any discrepancies (info screen reflects mechanical truth).
5. Return to previous surface (Left/Right back to chat).

**Exit:** After 48 ticks (2s) or once perception has extracted the list.
Signals mode_complete.

**Current source status:** Exchange-related whisper events set a pending
reconciliation flag. `meta_decide` opens `check_info_screen` after leaving
whisper during normal playable surfaces, and also routes any existing
`INFO_SCREEN` view through `check_info_screen` so the visit is bounded and
closes explicitly. Eurydice's post-belief hook updates `PlayerKnowledge` from
parsed info-screen role/color entries. A full role entry is treated as
mechanical role-exchange truth; a color-only entry is treated as mechanical
color-exchange truth. Long-list scrolling and any hostage-exchange-specific
trigger still need live-trace validation before being called complete.

---

## Whisper Interaction Protocol

The whisper protocol is a state machine that governs behavior once inside
a whisper. It is the implementation of `in_whisper` mode and handles the
core information exchange gameplay.

### State Machine

```
[ENTER] -> [ASSESS] -> [COLOR_EXCHANGE] -> [EVALUATE] -> [ROLE_EXCHANGE or EXTRACT or STALL] -> [EXIT]
```

States:

| State | Description | Duration |
|-------|-------------|----------|
| ENTER | Just entered whisper; orient to occupants | 1-2 ticks |
| ASSESS | Identify occupants, check what we already know | ~24 ticks (1s) |
| COLOR_EXCHANGE | Execute C.OFFER -> wait for C.ACCPT | ~72 ticks (3s) |
| EVALUATE | Process team reveal; decide next action | ~12 ticks (0.5s) |
| ROLE_EXCHANGE | Execute R.OFFER -> wait for R.ACCPT | ~72 ticks (3s) |
| EXTRACT | Chat-based intel gathering | variable |
| STALL | Time-wasting against enemy | variable |
| EXIT | Leave whisper | ~24 ticks (1s) |

### Protocol Variants

The whisper protocol runs differently based on context:

#### Standard Probe Protocol

Used for: general information gathering (most common).

```
ENTER -> ASSESS -> COLOR_EXCHANGE -> EVALUATE:
  IF same_team AND intent is FIND_KEY_PARTNER:
    -> ROLE_EXCHANGE -> check if partner -> EXIT
  IF same_team AND intent is general:
    -> ROLE_EXCHANGE (to verify role) -> EXTRACT (ask for intel) -> EXIT
  IF opposite_team:
    -> EXTRACT (probe for intel) -> EXIT
  IF unknown (exchange failed/timeout):
    -> EXIT
```

#### Key Exchange Protocol

Used for: completing the win-condition mutual role exchange with known
partner.

```
ENTER -> ASSESS (confirm partner is present) -> ROLE_EXCHANGE (immediately) -> EXIT
```

No color exchange needed (partner already confirmed). This should take
<4 seconds.

#### Infiltration Protocol (Spy)

Used for: Spy maintaining cover while gathering intelligence.

```
ENTER -> ASSESS -> COLOR_EXCHANGE (reinforces fake identity) -> EVALUATE:
  IF "same team" (they think we're allies):
    -> EXTRACT (gather intel on key roles) -> EXIT
  IF "opposite team" (they correctly identified us somehow):
    -> EXIT immediately
```

Never accept R.OFFER in this protocol (would reveal Spy status).

#### Stall Protocol

Used for: `time_waste` mode against enemy players.

```
ENTER -> ASSESS -> COLOR_EXCHANGE (slow; delay between actions) ->
  EVALUATE (act confused/conflicted) ->
  EXTRACT (ask lots of questions; show interest) ->
  [delay 3-5 seconds total] -> EXIT (just before they leave)
```

Goal: maximize enemy time spent in this whisper.

### Detailed State Behaviors

#### ASSESS State

```python
def assess(whisper_occupants, knowledge_base):
    for occupant in whisper_occupants:
        known = knowledge_base.get(occupant.player_id)
        if known is None:
            return AssessResult.UNKNOWN_OCCUPANT
        if known.team == my_team:
            return AssessResult.ALLY_PRESENT
        if known.team != my_team:
            return AssessResult.ENEMY_PRESENT
    return AssessResult.MIXED_OR_UNKNOWN
```

#### COLOR_EXCHANGE State

Actions:
1. Select "C.OFFER" from action menu (`MenuNavTask("C.OFFER")`)
2. Wait for partner to C.ACCPT (observe system message "swapped colors")
3. If they C.OFFER first: select "C.ACCPT" + target picker

**Timeout:** If no response within 72 ticks (3s), transition to EXIT.

**Response to incoming C.OFFER from others:**
- Always accept (information is always valuable; our team color is
  acceptable to reveal in most cases)
- Exception: Persephone in cautious mode may decline if room is unknown
  players (revealing Nymphs narrows identity)

#### EVALUATE State

After color exchange reveals team:

```python
def evaluate_after_color(occupant_team, my_role, intent):
    if occupant_team == my_team:
        if intent == ProbeIntent.FIND_KEY_PARTNER:
            return NextAction.ROLE_EXCHANGE  # Might be our partner
        elif intent == ProbeIntent.GENERAL:
            return NextAction.ROLE_EXCHANGE  # Verify role for intel
        else:
            return NextAction.EXTRACT        # Chat for intel
    elif occupant_team != my_team:
        if my_role in [Role.SHADE, Role.NYMPH]:
            return NextAction.EXTRACT        # Grunts can probe enemies
        elif my_role in [Role.HADES, Role.PERSEPHONE]:
            return NextAction.EXIT           # Key roles avoid enemy interaction
        elif my_role in [Role.CERBERUS, Role.DEMETER]:
            return NextAction.EXIT           # Searchers don't waste time on enemies
        elif my_role == Role.SPY:
            return NextAction.EXTRACT        # Spy infiltrates
```

**Note on EXIT after color exchange (key roles):** Exiting after
discovering an enemy does NOT undo the information already leaked --
the color exchange was mutual, so the enemy now knows our team color.
However, EXIT still limits further exposure (prevents role reveal or
behavioral analysis from extended interaction). The damage is
acceptable: team color alone doesn't identify specific role (multiple
players share the same team). To minimize even this exposure, key roles
(Hades/Persephone) should prefer REACTIVE color exchanges (accept
C.OFFER from others) over PROACTIVE ones (never C.OFFER first with
unknowns). Reactively accepting still reveals your team, but lets you
assess the whisper situation before committing.

#### ROLE_EXCHANGE State

Actions:
1. Select "R.OFFER" from action menu (`MenuNavTask("R.OFFER")`)
2. Wait for partner to R.ACCPT (observe system message "shared roles")
3. If they R.OFFER first: evaluate whether to accept

**Decision: Accept incoming R.OFFER?**

| My Role | Their Team | Accept? | Reasoning |
|---------|-----------|---------|-----------|
| Hades | Shades (confirmed) | YES | Might be Cerberus (critical) |
| Hades | Nymphs | NO | Reveals Hades identity + location |
| Hades | Unknown | NO (Round 1-2) / MAYBE (Round 3) | Risk vs time pressure |
| Cerberus | Shades | YES | Might be Hades (critical) |
| Cerberus | Nymphs | NO | Reveals identity |
| Shade | Any | YES | Nothing to hide; information is always good |
| Persephone | Nymphs (confirmed) | YES | Might be Demeter (critical) |
| Persephone | Shades | NEVER | Catastrophic identity reveal |
| Persephone | Unknown | NO | Too risky |
| Demeter | Nymphs | YES | Might be Persephone (critical) |
| Demeter | Shades | NO | Reveals identity |
| Nymph | Any | YES | Nothing to hide |
| Spy | Real team (verified) | YES | Establishes trust with real ally |
| Spy | Fake team (enemy) | NO | Would reveal Spy status |
| Spy | Unknown | NO | Too risky |

#### EXIT State

Actions:
1. Select "EXIT" from action menu (`MenuNavTask("EXIT")`)
2. Wait for overworld view to return

**Post-exit knowledge update:**
- Mark player as interacted-with this round
- Update team/role knowledge based on exchange results
- Update behavioral flags based on their behavior in whisper
- Clear pending offers state

### Incoming Offer Handling (Reactive)

While in a whisper, other occupants may initiate offers. The agent must
respond:

| Incoming Action | Default Response | Role Exceptions |
|----------------|-----------------|-----------------|
| C.OFFER | Accept (C.ACCPT) | Persephone may decline in cautious mode |
| R.OFFER | Role-dependent (see table above) | -- |
| PASS (leadership) | Accept if strategically useful | -- |
| GRANT (entry request) | Grant if occupant count < 4 | Deny if enemy and wanting privacy |
| Chat message | Parse for intel; respond if useful | -- |

### Whisper Isolation Cost

While in a whisper, the agent has NO access to global chat (RULEBOOK
constraint: "While in a whisper, a player has no access to global chat --
they cannot send global messages, read global messages, or see an unread
indicator"). This means:

- **Missed global messages:** Allies may share intel via global chat that
  the agent won't see until exiting the whisper.
- **No usurp participation:** Cannot vote or coordinate usurp attempts.
- **No global sending:** Cannot send critical broadcasts.
- **No unread awareness:** Doesn't even know messages were missed.

**Mitigations:**
1. Before entering a whisper, check the unread global indicator (green
   dot at pixel (124, barY+4), color 11). The dot blinks on a 16-tick
   cycle -- a single-frame check has ~50% detection rate (if color 11 is
   present, unread is guaranteed; if absent, it might be in the off-blink
   phase). This 50% rate is acceptable for a "nice to have" optimization
   -- it costs zero ticks (just a pixel check on the current frame).
2. Keep whisper interactions as short as possible. The stall protocol's
   12-second duration is especially costly in terms of missed information.
3. In Round 3 / PANIC urgency, abbreviate all whisper protocols: skip
   color exchange, go straight to role exchange with same-team players.
4. If you are leader and HostageSelect is imminent, exit whispers early
   to maintain global chat awareness and respond to usurp attempts.

### Whisper Time Budget

Each probe cycle in a whisper has a maximum time budget. If the budget
is exceeded, force EXIT regardless of protocol state:

| Protocol Variant | Max Duration |
|-----------------|-------------|
| Standard probe | 240 ticks (10s) |
| Key exchange | 96 ticks (4s) |
| Infiltration | 240 ticks (10s) |
| Stall | 288 ticks (12s) -- deliberately long |
| Quick verify | 144 ticks (6s) |

---

## Communication Protocol

### Fundamental Constraint: Room-Local Chat

**Global chat is room-local.** Only players currently in the same room
can see each other's global messages. There is NO broadcast mechanism
that reaches the other room. The only cross-room communication channel
is the Leader Summit (a forced whisper between the two room leaders,
occurring between rounds).

This means:
- You can only relay intel to allies in YOUR room
- "Coded messages" to the other room are impossible
- The leader summit is strategically precious -- it's the only time
  you can learn about or influence the other room

### Global Chat Usage

Global chat is rate-limited (10s cooldown) and visible to all players in
your room (allies AND enemies). Every message must be worth the cooldown
cost.

#### Sending: Message Templates

| Situation | Template | When to Send | Role Restriction |
|-----------|----------|--------------|------------------|
| Seeking teammate | `LOOKING FOR [color]` | Round 1, seeking partner | Key roles (risky -- draws attention) |
| Meetup request | `MEET [direction]` | After finding partner, need whisper | Any |
| Identity claim (true) | `I AM [role]` | Emergency coordination (panic mode) | Rarely |
| Identity claim (false) | `I AM [role]` | Deception / decoy | Grunts |
| Location intel | `[color] IS [role]` | Share enemy ID with local allies | Grunts (acceptable risk) |
| Hostage request | `SEND ME` | Volunteering for cross-room move | Any |
| Hostage suggestion | `SEND [color]` | Lobbying leader | Any |
| Usurp call | `VOTE FOR ME` | Coordinating usurp | Non-leaders |
| Warning | `DONT SEND [color]` | Protecting ally from hostage | Any (risky) |

#### When NOT to Send Global Chat

- When cooldown would prevent a more important later message
- When the information helps local enemies more than local allies
- Key roles (Hades, Persephone) should minimize chat to avoid drawing
  attention and behavioral inference
- When in a whisper (impossible -- chat routes to whisper)
- When you have nothing strategically useful to say (don't waste the slot)

#### Message Priority System (One Per Round)

Global chat has a 240-tick (10-second) cooldown. During a typical Playing
phase, this allows AT MOST one message. The agent must choose the
highest-applicable priority:

| Priority | Situation | Template | When |
|----------|-----------|----------|------|
| 1 (critical) | Panic identity reveal to find partner | `I AM [role]` | Round 3 only, key exchange incomplete |
| 2 (critical) | Usurp coordination when achievable | `VOTE FOR ME` | Before HostageSelect, hostile leader |
| 3 (high) | Key role location to local key-role ally | `[color] IS [role]` | Ally key role is in our room |
| 4 (high) | Hostage request to ally leader | `SEND ME` | Need cross-room movement |
| 5 (medium) | Meetup coordination | `MEET [direction]` | Partner found, need whisper |
| 6 (low) | General intel sharing | `[color] IS [team]` | Allies may benefit |

**Rule:** Never send a priority-6 message in Round 1 if a priority-1-4
message might be needed later in the round. In Round 1, prefer deferring
global chat entirely unless a clear high-priority opportunity arises.
Defer the message slot for unexpected opportunities (enemy key role
spotted, usurp needed).

### Whisper Chat Usage

Whisper chat is rate-limited (2s cooldown) and visible only to current
occupants. Used for in-context communication during interactions.

| Situation | Template | Purpose |
|-----------|----------|---------|
| Probe | `WHO ARE YOU` | Open conversation / social pressure |
| Intel request | `FOUND [role]?` | Ask ally if they've located key role |
| Intel share | `[color] IS [team/role]` | Share verified information |
| Request hostage | `SEND ME` | Ask leader (if in whisper with them) |
| Stall | `THINKING` or `WAIT` | Buy time (time_waste mode) |
| Deception | `I AM [false role]` | Mislead enemy in whisper |
| Coordination | `VOTE ME` | Usurp request to ally |
| Negotiate (summit) | `SEND ME [color] I SEND YOU [color]` | Leader summit trade |

### Chat Parsing: Receiving and Interpreting Messages

**Design principle:** Other agents are NOT Eurydice agents. They may:
- Use completely different vocabulary and message formats
- Send multi-word natural-language messages
- Use abbreviations, misspellings, or unconventional syntax
- Send strategically meaningless chatter
- Lie with any content
- Not respond to our messages at all

Chat parsing must be **robust to arbitrary input** and **conservative in
its conclusions**. The parser extracts semantic intents with confidence
levels, never assumes message format.

#### Parser Architecture

```python
@dataclass
class ParsedMessage:
    raw_text: str
    sender_id: PlayerID
    channel: str                          # "global" | "whisper"
    tick: int

    # Extracted intents (each with independent confidence)
    identity_claim: IdentityClaim | None  # "I am X" type claims
    location_claim: LocationClaim | None  # "[player] is in [room]" type claims
    action_request: ActionRequest | None  # "send me", "vote for X" type requests
    question: Question | None             # "who are you", "found X?" type probes
    uninterpretable: bool                 # True if no intent extracted


@dataclass
class IdentityClaim:
    claimed_role: str | None              # Fuzzy-matched role name, or None
    claimed_team: str | None              # Fuzzy-matched team name, or None
    confidence: float                     # How confident we are in the parse (not truth)
    subject: str                          # "self" | player_descriptor


@dataclass
class LocationClaim:
    subject: str                          # Player descriptor (color, name, role)
    location: str                         # Room descriptor or direction
    confidence: float


@dataclass
class ActionRequest:
    action_type: str                      # "send_hostage" | "vote_usurp" | "meet" | "exchange"
    target: str | None                    # Who/what the action targets
    confidence: float
```

#### Parsing Strategy: Keyword Extraction

Rather than template matching, the parser uses keyword/pattern extraction
with fuzzy matching:

```python
def parse_message(text: str, sender_id: PlayerID, channel: str, tick: int) -> ParsedMessage:
    text_upper = text.upper().strip()
    result = ParsedMessage(raw_text=text, sender_id=sender_id, channel=channel, tick=tick)

    # Identity claims: look for "I AM", "IM", "I'M" + role/team keyword
    identity_match = extract_identity_claim(text_upper)
    if identity_match:
        result.identity_claim = identity_match

    # Location claims: look for color/name + "IS" / "IN" + room descriptor
    location_match = extract_location_claim(text_upper)
    if location_match:
        result.location_claim = location_match

    # Action requests: look for action keywords
    action_match = extract_action_request(text_upper)
    if action_match:
        result.action_request = action_match

    # Questions: look for "?" or question keywords ("WHO", "WHERE", "FOUND")
    question_match = extract_question(text_upper)
    if question_match:
        result.question = question_match

    # If nothing extracted, mark uninterpretable
    if not any([result.identity_claim, result.location_claim,
                result.action_request, result.question]):
        result.uninterpretable = True

    return result


# Keyword dictionaries for fuzzy matching
ROLE_KEYWORDS = {
    "HADES": Role.HADES, "HAD": Role.HADES,
    "PERSEPHONE": Role.PERSEPHONE, "PERS": Role.PERSEPHONE, "SEPH": Role.PERSEPHONE,
    "CERBERUS": Role.CERBERUS, "CERB": Role.CERBERUS,
    "DEMETER": Role.DEMETER, "DEM": Role.DEMETER,
    "SHADE": Role.SHADE, "SHADES": Role.SHADE,
    "NYMPH": Role.NYMPH, "NYMPHS": Role.NYMPH,
    "SPY": Role.SPY,
    "GRUNT": None,  # Ambiguous team
}

TEAM_KEYWORDS = {
    "SHADES": Team.SHADES, "SHADE": Team.SHADES, "GREEN": Team.SHADES,
    "NYMPHS": Team.NYMPHS, "NYMPH": Team.NYMPHS, "PINK": Team.NYMPHS,
}

ACTION_KEYWORDS = {
    "SEND ME": ("send_hostage", "self"),
    "SEND": ("send_hostage", None),       # Needs target extraction
    "VOTE": ("vote_usurp", None),         # Needs target extraction
    "MEET": ("meet", None),               # Needs location extraction
    "EXCHANGE": ("exchange", None),
    "SWAP": ("exchange", None),
}
```

#### Credibility Assessment

After parsing, the message's claims are assessed for credibility:

```python
def assess_credibility(parsed: ParsedMessage, sender_knowledge: PlayerKnowledge) -> float:
    """Return 0.0-1.0 credibility score for the parsed claims."""
    base_credibility = 0.3  # Chat messages start at low trust

    # Boost for verified allies
    if sender_knowledge.team == my_team and sender_knowledge.team_source == "role_exchange":
        base_credibility = 0.85  # Verified teammate; likely honest

    if sender_knowledge.team == my_team and sender_knowledge.team_source == "color_exchange":
        base_credibility = 0.6  # Probably teammate (Spy caveat)

    # Reduce for known enemies
    if sender_knowledge.team is not None and sender_knowledge.team != my_team:
        base_credibility = 0.1  # Enemy; likely lying or misdirecting

    # Reduce for contradictions with known facts
    if parsed.identity_claim and contradicts_known_facts(parsed.identity_claim, sender_knowledge):
        base_credibility *= 0.1  # Almost certainly lying

    # Reduce for unknown sender
    if sender_knowledge.team is None:
        base_credibility = 0.2  # Can't assess intent

    return base_credibility
```

#### Knowledge Update from Chat

Only claims with sufficient credibility update the knowledge model:

```python
def update_knowledge_from_chat(parsed: ParsedMessage, credibility: float, knowledge_base):
    # Identity claims from credible allies update knowledge
    if parsed.identity_claim and credibility > 0.5:
        target = resolve_player_reference(parsed.identity_claim.subject)
        if target and parsed.identity_claim.claimed_role:
            target_knowledge = knowledge_base[target]
            # Only update if we don't have better info
            if target_knowledge.role_source in [None, "inferred"]:
                target_knowledge.role = parsed.identity_claim.claimed_role
                target_knowledge.role_source = "chat_claim"
                target_knowledge.team_confidence = credibility * 0.7  # Further discounted

    # Action requests are always noted (even from enemies -- useful signal)
    if parsed.action_request:
        note_action_request(parsed.sender_id, parsed.action_request)
```

### Communication in Leader Summit

The leader summit is the ONLY cross-room interaction opportunity. It
deserves special handling:

**Information flow (chat-only -- no mechanical exchanges possible):**
- You can probe for information about the other room via chat
- You can negotiate hostage swaps verbally ("I'll send X if you send Y")
- Verbal agreements are non-binding (lies are free)
- You can tab to shout view to read your own room's global chat
- You can tab to info screen to validate accumulated knowledge
- You CANNOT color/role exchange, transfer leadership, or leave early

**Summit chat strategy:**

| My Team | Their Team | Strategy |
|---------|-----------|----------|
| Shades | Nymphs | Probe for Persephone location; offer misleading trades |
| Nymphs | Shades | Probe for Hades location; misdirect about Persephone |
| Same team | Same team | Coordinate! Share intel about room compositions, plan hostage swaps |

**Summit as intelligence source:**
- Their chat responses (even refusals) reveal information
- If they eagerly discuss hostage trades involving specific players,
  those players may be their key roles
- Time pressure in the summit means they may be less guarded
- Their team must be inferred from behavioral cues (no color exchange
  available); prior knowledge from Playing phase is essential

---

## Cross-Room Strategy: Working Without Communication

### The Fundamental Constraint

Rooms in Persephone's Escape are **completely isolated** during the
Playing phase. No mechanism exists for real-time communication between
rooms:

- Global chat is room-local (only same-room players see it)
- Whispers only exist within a room
- There is no "peeking" or shared channel

The ONLY cross-room interaction points are:
1. **Roster Reveal** (pre-game): all players see both room assignments
2. **Leader Summit** (between rounds): leaders from each room whisper
3. **Hostage Exchange** (between rounds): physical player transfer

### Implications for Strategy

This constraint fundamentally shapes viable strategy:

**What's impossible:**
- Telling an ally in the other room what you've learned
- Requesting an ally in the other room to take specific action
- Coordinating real-time movement between rooms
- Knowing what's happening in the other room during Playing phase

**What IS possible:**
- **Shared strategy convergence:** If all Eurydice agents follow the
  same role-specific strategy, they'll independently make compatible
  decisions. E.g., Cerberus ALWAYS volunteers as hostage when Hades
  is in the other room -- no communication needed.
- **Summit negotiation:** Leaders can exchange information and negotiate
  during the 15-second summit. This is extremely high-value.
- **Inference from hostage arrivals:** When a player arrives via hostage
  exchange, you learn they were in the other room, and you can now
  interact with them directly.
- **Pre-separation knowledge:** If you interacted with a player before
  they were hostaged away, you retain that knowledge.

### Implicit Coordination via Shared Strategy

Since Eurydice agents can't explicitly coordinate across rooms, the
strategy documents must be designed so that **independent optimal play
from each role produces team-coherent behavior**:

| Scenario | How It Resolves Without Communication |
|----------|---------------------------------------|
| Hades and Cerberus in different rooms | Cerberus's strategy says: "volunteer as hostage." Hades's strategy says: "stay put (positioning matters)." Result: Cerberus moves toward Hades. |
| Persephone needs Demeter from other room | Demeter's strategy says: "if all local Nymphs are grunts, volunteer as hostage." Persephone's strategy says: "wait." Result: Demeter moves to Persephone. |
| Shade grunt in other room finds Persephone | Shade can't tell Hades (different room). But: Shade seeks leadership to control hostage picks. Shade sends Persephone toward Hades's room if possible. |
| Nymph grunt discovers Hades's location | Nymph can only tell local allies. If Persephone is local, relay directly. If not, Nymph seeks leadership to PREVENT Persephone from being sent to Hades's room. |

**Deployment constraint:** Implicit coordination requires all Eurydice
agents to share the exact same strategy code and knowledge state
evaluators. This is naturally satisfied in tournament bundles (single
codebase). Against non-Eurydice teammates (mixed lobbies), implicit
coordination is unavailable -- the agent falls back to explicit
communication (whisper/global chat) and independent rational play. The
strategy must be correct even when teammates DON'T make the "expected"
complementary decision.

### What the Leader Summit Should Accomplish

Given that the summit is the only cross-room channel (chat-only, no
mechanical exchanges), a Eurydice leader should:

1. **Determine other leader's team via behavioral inference** (no color
   exchange available). Prior knowledge from Playing phase is essential:
   if you interacted with the other leader before they became leader
   (e.g., probed them in a prior round), you may already know their
   team. If not, their chat responses provide behavioral signal.
2. **If same team (known from prior interaction):** Share room composition
   intel via chat. Agree on hostage strategy. "I HAVE [key role] HERE
   SEND ME [partner]."
3. **If enemy team:** Extract intel through questioning. Negotiate
   misleading trades. Consume their message slots with questions (every
   message they spend answering you is one less they spend planning).
4. **Tab to shout view:** Read any global chat from your room that
   accumulated during the summit. Your teammates may have shared intel
   or usurp updates.
5. **Prepare pre-summit:** Before the summit (during Playing phase),
   local allies should whisper with the leader to share intel that the
   leader can then use in summit chat negotiation.

---

## Deception Framework

### Deception State

```python
@dataclass
class DeceptionState:
    # What identity am I projecting?
    projected_role: Role | None           # What I'm pretending to be (None = honest)
    projected_team: Team | None           # Team I'm claiming (None = honest)
    target_audience: set[PlayerID]        # Who have I deceived?
    lies_told: list[LieRecord]            # (tick, target, claim, channel)
    cover_consistent: bool                # No contradictions yet?
```

### When to Deceive

Deception is EV-positive when:

```
EV(deception) = P(believed) * V(belief) - P(caught) * C(exposure) > 0
```

| Role | Can Claim | Safe To | Risky To |
|------|-----------|---------|----------|
| Shade grunt | Hades, Cerberus, Nymph, Demeter | Claim anything in chat | Role-exchange (reveals truth) |
| Nymph grunt | Persephone, Demeter, Shade, Hades | Claim anything in chat | Role-exchange (reveals truth) |
| Hades | Shade grunt, Cerberus | Claim to Nymphs (deflects targeting) | Color-exchange (confirms Shades team) |
| Persephone | Nymph grunt, Demeter | Claim to Shades (deflects targeting) | Color-exchange (confirms Nymphs team) |
| Spy | Opposite team member | Color-exchange (reinforces cover!) | Role-exchange (reveals Spy) |

### Deception Principles

1. **Never contradict mechanical reveals.** If you've already color-
   exchanged with someone, don't claim to be on the other team to them.
2. **Track who believes what.** Don't tell Player A "I'm Hades" and
   Player B "I'm a grunt" if they might compare notes.
3. **Deception has diminishing returns.** Each lie increases the chance
   of a contradiction being discovered.
4. **Grunts have the most deception freedom.** Being caught costs nothing
   -- their actual role is uninteresting to enemies.
5. **Key roles should minimize deception surface.** Fewer interactions =
   fewer chances to be caught in a lie. Deception through omission
   (behavioral camouflage) is safer than active lying.

### Behavioral Camouflage

Beyond verbal deception, roles can mimic other roles' behavioral patterns:

| Role | Camouflage as | Behavior to Mimic |
|------|---------------|-------------------|
| Persephone | Nymph grunt | Probe players freely; don't avoid interaction |
| Hades | Shade grunt | Accept role exchanges casually; don't seem urgent |
| Key roles | Grunt | Show team color freely; act like room composition doesn't matter |

---

## Spy-Specific Design

### Spy Mode Evaluator

The Spy has a fundamentally different strategic loop because its primary
asset (cover identity) must be actively maintained:

```python
def evaluate_spy(state, belief, memory):
    # Phase 0: Establish one verified ally on real team
    if state.verified_ally is None:
        real_allies = [p for p in players if p.team == state.my_team and p.team_source == "role_exchange"]
        if real_allies:
            state.verified_ally = real_allies[0].player_id
        else:
            # Find a real teammate and role-exchange to establish trust.
            # The Spy's dilemma: color exchange shows the WRONG team, so
            # color-exchanging first makes us appear as "enemy" to real
            # allies. Strategy: skip color exchange, go straight to R.OFFER.
            # Mutual role exchange reveals "Spy" + true team to them.
            # This is safe IF they're a real ally (they learn we're on their
            # side). If they're an enemy, our cover is blown -- but we also
            # learn their role.
            #
            # Target selection: prioritize players who appear to be on our
            # FAKE team via prior color exchanges (with others, not us).
            # These are actually our REAL teammates -- the color exchange
            # shows them as our "fake" team because that IS their real team
            # (we see the opposite). This is the one case where Spy's
            # inverted perception helps: players we'd normally avoid (same
            # color as fake team) are actually our real allies.
            return (ModeDirective(mode="probe_target", params=ProbeTargetParams(
                target=find_probable_real_ally(state),
                intent=ProbeIntent.VERIFY_SELF_AS_SPY,
                skip_color_exchange=True,  # Go straight to role exchange
            )), None)

    # Phase 1: Infiltrate enemy circles
    if state.cover_intact:
        high_value_target = find_infiltration_target(state)
        if high_value_target:
            return (ModeDirective(mode="in_whisper", params=InWhisperParams(
                protocol="infiltration",
                target=high_value_target,
            )), None)

    # Phase 2: Relay intelligence to a verified local ally
    if state.local_intel_to_share and state.verified_ally and ally_is_local(state):
        return (ModeDirective(mode="relay_intelligence", params=RelayParams(
            channel="whisper",  # Private relay to verified ally in same room
        )), None)

    # Phase 3: Decisive action (Round 3)
    if state.current_round == 3 and has_decisive_play(state):
        return (ModeDirective(mode="break_cover", params=BreakCoverParams(
            action=best_decisive_play(state),
        )), None)

    # Phase 4: Cover blown -- revert to grunt
    if not state.cover_intact:
        grunt_role = Role.SHADE if state.my_team == Team.SHADES else Role.NYMPH
        return evaluate_grunt(state, belief, memory, grunt_role)

    # Default: continue infiltration
    return (ModeDirective(mode="scout", params=ScoutParams(target_fake_team=True)), None)
```

### Spy Phase 0: Finding a Real Ally (Detail)

The Spy's hardest bootstrapping problem: identifying a real ally without
revealing itself to enemies.

**Strategy:**
1. **Skip color exchange entirely** when approaching Phase 0 targets.
   Color exchange reinforces our cover (shows wrong team) but provides
   no useful information to US about the target's real identity relative
   to our real team.
2. **Go straight to R.OFFER.** If they accept: mutual role exchange
   reveals both identities. If they're a real ally, they see "Spy + [our
   real team]" and we see their true role. Trust established.
3. **Target selection via process of elimination:**
   - Players whose team color (from others' color exchanges or behavioral
     observation) matches our FAKE team are likely our REAL allies. This
     is because our fake team IS their real team (Spy's color is inverted).
   - Avoid players confirmed via role exchange as enemies (their role
     reveals their team definitively).
4. **Accept the risk:** The first role exchange is the Spy's highest-risk
   moment. Naive odds: roughly even (40-55% ally depending on room
   split). But informed targeting improves this significantly: players
   whose color (from others' exchanges) matches the Spy's FAKE team are
   likely REAL allies (Spy's inversion means fake team = real team's
   color). Prioritizing these targets raises success probability to
   ~65-75% when at least one color exchange has been observed. If we hit
   an enemy, cover is blown -- but without a verified ally, the Spy is
   strategically useless.

### Cover Management Rules

| Action | Cover Impact |
|--------|-------------|
| Color exchange | REINFORCES cover (shows opposite team) |
| One-way ROLE reveal | BREAKS cover (shows "Spy") |
| Mutual role exchange with enemy | BREAKS cover (shows "Spy" + true team) |
| Mutual role exchange with real ally | Establishes trust (they see Spy + true team) |
| Chat message consistent with fake team | MAINTAINS cover |
| Chat message inconsistent | WEAKENS cover (behavioral suspicion) |
| Being seen with real teammates | WEAKENS cover (association suspicion) |

### Spy Decision: Accept R.OFFER?

This is the Spy's hardest recurring decision:

```python
def spy_should_accept_role_exchange(offerer, state):
    if offerer.player_id == state.verified_ally:
        return True  # Already know we're Spy; safe

    if offerer.team == state.my_team:  # Real teammate (but they don't know we're Spy)
        if state.urgency == "panic":
            return True  # Need to establish trust fast
        return False  # Reveals Spy status; only do if strategically needed

    if offerer.team != state.my_team:  # Enemy (thinks we're their ally)
        return False  # Would immediately blow cover

    return False  # Default: decline
```

### Spy High-Value Plays

| Play | Setup | Impact | Cover Cost |
|------|-------|--------|-----------|
| Become enemy-supported leader | Color-exchange → usurp support → win vote | Control hostage selection for your real team | Breaks at decision time |
| Locate key role from inside | Infiltrate circles → witness exchange/discussion | Most valuable single intel in game | Maintained until relay |
| Waste key role's time | Pretend to be their partner (Spy Cerberus to Hades) | Burns their interaction slot | Broken on R.EXCHANGE |
| Feed false intel | Tell enemy team wrong locations | Misdirects their positioning | Maintained |

---

## Hostage and Leadership Strategy

### Leadership Value Assessment

Leadership is not always desirable. The assessment:

| Condition | Leadership Value | Reasoning |
|-----------|-----------------|-----------|
| I'm a grunt + ally key role in room | HIGH | Protect key role from hostage selection |
| I'm a grunt + need to control positioning | HIGH | Direct hostage picks |
| I'm Persephone | HIGH | Immune to being hostaged; controls own safety |
| I'm Hades + positioning is wrong | LOW | Leaders can't be hostaged (can't move self) |
| Enemy has leadership + threatens our positioning | MUST USURP | Defensive necessity |
| I'm Cerberus + need to cross rooms | LOW | Would block own movement |

### Usurp Decision Framework

```python
def should_usurp(state):
    # Calculate threat level of current leader
    if state.room_leader_team == state.my_team:
        return False  # Ally leader; don't undermine

    if state.room_leader_team is None:
        return False  # Unknown; wait for more info

    # Enemy leader -- assess threat
    threat = assess_hostage_threat(state)
    if threat == "critical":  # They'll send our key role or us (if we're key)
        votes_available = count_ally_votes(state)
        votes_needed = (len(state.players_in_my_room) // 2) + 1
        if votes_available >= votes_needed:
            return True  # Can win; do it

    # Round 3 always usurp if possible (last chance)
    if state.current_round == 3 and state.room_leader_team != state.my_team:
        votes_available = count_ally_votes(state)
        votes_needed = (len(state.players_in_my_room) // 2) + 1
        if votes_available >= votes_needed:
            return True

    return False
```

### Hostage Volunteering

There is no "volunteer" button. To volunteer as hostage:

1. **Signal to leader via whisper:** Enter whisper with leader, send
   "SEND ME" chat message. Most reliable if leader is an ally.
2. **Signal via global chat:** Send "SEND ME" in global chat (room-local;
   leader can see it since they're in the same room).
3. **Positional signal:** Stand near leader during HostageSelect phase.
   (Weak signal -- leader may not interpret this correctly, especially
   if leader is not an Eurydice agent.)

**Key realization:** If the leader is an ENEMY, volunteering is useless --
they'll pick whoever hurts YOUR team most. Volunteering only works when:
- Leader is an ally (they'll respect the request)

**Note:** Auto-fill (when leader doesn't commit) selects randomly from
eligible unselected players. Proximity has no effect on auto-fill selection.

Volunteering makes sense when:
- You need to cross rooms (Cerberus going to Hades, or vice versa)
- Your room position doesn't matter (grunts)
- Being in the other room lets you take useful action next round

---

## Temporal Mechanics

### Configuration Awareness

Round durations vary dramatically across game configs (15s to 300s per
round). The agent MUST adapt its time budgeting to the actual config,
not assume fixed durations. The config is discoverable from:
- `belief_state.round_schedule` (populated from intro Panel 3, if
  perception extracts it)
- Falling back to observation: measure actual round duration from first
  Playing tick to HostageSelect transition

**Known preset families:**

| Family | Round Pattern | Strategic Character |
|--------|-------------|-------------------|
| `default`/`fast` | 3x 15s | Extreme scarcity; ~1 probe/round; target selection is everything |
| `short`/`empty` | 1x 30s | Single round; no escalation; must complete exchange in one shot |
| `empty3` | 3x 45s | Moderate; 3-4 probes/round; comfortable coverage |
| `simple` | 1x 60s | Single round; ample probing time; no hostage dynamics |
| `debug2r` | 2x 60s | Two rounds; solid exploration + execution split |
| `medium` | 180s/120s/60s | Descending; generous R1 exploration, tight R3 execution |
| `medium12` | 300s/240s/180s/120s/60s | 5 rounds, 12 players; long-form strategic game |

**Descending-duration configs** (medium family) naturally match the
urgency escalation model: Round 1 has generous time for systematic
probing and information gathering, while the final round forces quick
decisive action. The agent should NOT enter PANIC mode in Round 1 of a
180s round just because it's "late in the round" -- 180s provides ample
time.

### Round Budget Tracker

```python
@dataclass
class RoundBudget:
    round_duration_ticks: int             # From config; NOT hardcoded
    ticks_elapsed: int = 0
    probe_cycles_completed: int = 0
    probe_cycle_cost_ticks: int = 216     # ~9 seconds average (full probe)
    fast_probe_cost_ticks: int = 144      # ~6 seconds (skip color exchange)

    @property
    def ticks_remaining(self) -> int:
        return max(0, self.round_duration_ticks - self.ticks_elapsed)

    @property
    def can_start_full_probe(self) -> bool:
        return self.ticks_remaining > self.probe_cycle_cost_ticks

    @property
    def can_start_fast_probe(self) -> bool:
        return self.ticks_remaining > self.fast_probe_cost_ticks

    @property
    def can_start_quick_action(self) -> bool:
        return self.ticks_remaining > 72  # 3 seconds for a quick chat/exchange

    @property
    def probes_remaining_estimate(self) -> int:
        """Estimated remaining full probes possible this round."""
        return self.ticks_remaining // self.probe_cycle_cost_ticks
```

### Urgency Computation

Urgency is expressed relative to the game's round structure, not
absolute round numbers. A 5-round game's Round 3 is mid-game, not
endgame. The computation uses `rounds_remaining` and fractional time
position.

```python
def compute_urgency(state: StrategicState) -> Urgency:
    total_rounds = len(state.round_schedule)  # From config
    rounds_remaining = total_rounds - state.current_round  # 0 = final round
    fraction_elapsed = state.ticks_elapsed / state.round_duration_ticks

    # PANIC: final round + exchange incomplete
    if rounds_remaining == 0 and not state.key_exchange_done:
        return Urgency.PANIC

    # PANIC: final round, last 20% of time
    if rounds_remaining == 0 and fraction_elapsed > 0.8:
        return Urgency.PANIC

    # PRESSING: penultimate round (or later) + exchange incomplete
    if rounds_remaining <= 1 and not state.key_exchange_done:
        return Urgency.PRESSING

    # PRESSING: final round (even if exchange done, positioning matters)
    if rounds_remaining == 0:
        return Urgency.PRESSING

    # PRESSING: more than half the game elapsed + exchange incomplete
    if state.current_round > total_rounds // 2 and not state.key_exchange_done:
        return Urgency.PRESSING

    return Urgency.CALM
```

### Urgency Effects on Behavior

| Urgency | Effect on Behavior |
|---------|-------------------|
| CALM | Follow standard priority system; full probe cycles; cautious |
| PRESSING | Skip low-priority interactions; accept moderate risks; abbreviate probes |
| PANIC | Reveal identity if needed; accept any risk; global chat coordination; abandon stealth |

Specific panic-mode overrides:

- **Key roles in panic:** May reveal identity in global chat to find partner
- **Grunts in panic:** Sacrifice everything to facilitate key role meeting
- **Spy in panic:** Break cover for decisive action (hostage pick, intel relay)
- **All roles in panic:** Skip color exchange, go straight to role exchange
  with same-team players ("no time for verification theatre")

---

## Error Recovery and Fallback Behavior

### Stuck Detection

If `consecutive_idle_ticks` exceeds 120 (5 seconds) during a Playing
phase, the agent is stuck. Recovery:

1. Force mode switch to `scout` (break out of whatever isn't working)
2. Reset current interaction state
3. Log a warning for trace analysis

### Interrupted Interactions

| Interruption | Recovery |
|-------------|----------|
| Target walked away mid-approach | Re-evaluate targets; pick next |
| Whisper force-ejected (phase transition) | FSM detects view != whisper before EXIT state; cleans up knowledge, signals mode_complete with reason "forced_ejection"; meta_decide re-evaluates |
| Hostaged unexpectedly | Re-evaluate all strategic state (new room!) |
| Usurped from leadership | Assess new leader; possibly re-usurp |
| Role exchange reveals Spy | Update knowledge; adjust trust model |
| Round ended mid-probe | Carry over knowledge; re-plan for new round |

### Unexpected Hostage (Room Change)

When the agent is hostaged to the other room:

1. **Immediate:** Room assignment changes. All "players in my room"
   knowledge is invalidated.
2. **Re-scan:** Must re-identify visible players and rebuild room
   composition.
3. **Strategic re-evaluation:** Force `meta_decide` trigger with updated
   room. Priorities may change dramatically (e.g., Hades hostaged TO
   Persephone's room = positioning achieved accidentally).
4. **New leader:** Leadership resets after exchange. Reassess leadership
   landscape.

### Role Detection Failure

If role reveal is not detected by perception:

1. **Fallback behavior:** Act as a grunt (safest -- grunts have no
   critical secrets and their strategy is universally useful).
2. **Retry detection:** On each tick, attempt to re-read role from
   belief state (may be updated by later perception frames).
3. **If persists past Round 1:** Escalate to "unknown role" strategy
   (maximize information gathering, avoid commitments).

---

## Implementation Phases

### Phase 1: Core Loop (Week 1)

**Objective:** Agent can move, create whispers, and detect its role.

**Deliverables:**
- `meta_decide` dispatches based on role (idle before role known, scout after)
- `scout` mode with random waypoints
- `probe_target` mode with approach + whisper creation
- Role detection from role reveal perception

**Acceptance criteria:**
- Agent reliably detects its role within 15s of role reveal screen
- Agent moves toward other players when in `scout` mode
- Agent successfully creates whispers when near a target
- No crashes over a full 3-round game

### Phase 2: Information Gathering (Week 2)

**Objective:** Agent can execute color and role exchanges, build knowledge.

**Deliverables:**
- `in_whisper` mode with standard probe protocol
- Color exchange execution (menu navigation: C.OFFER, C.ACCPT)
- Role exchange execution (menu navigation: R.OFFER, R.ACCPT)
- Knowledge model population from exchange results
- `probe_systematic` mode with target prioritization

**Acceptance criteria:**
- Agent successfully completes color exchanges in >80% of whisper entries
- Agent correctly identifies team for color-exchanged players
- Agent role-exchanges with same-team players when appropriate
- Knowledge model tracks all interacted players accurately
- Target prioritization correctly avoids re-probing identified players

### Phase 3: Strategic Reasoning (Week 3)

**Objective:** Agent makes role-appropriate strategic decisions.

**Deliverables:**
- Full role-specific `meta_decide` evaluators (all 7 roles)
- Priority system with urgency escalation
- `hold_position` mode
- `coordinate_cross_room` mode (hostage volunteering + leader summit strategy)
- Phase-sensitive mode overrides (HostageSelect, etc.)

**Acceptance criteria:**
- Agent seeks partner exchange as top priority for key roles
- Agent shifts to positioning after exchange complete
- Round 3 behavior is measurably more aggressive than Round 1
- Agent correctly enters `hold_position` when positioning is favorable
- Agent volunteers as hostage when cross-room movement is needed
- Agent uses leader summit to negotiate/probe when it's leader

### Phase 4: Social Dynamics (Week 4)

**Objective:** Agent communicates strategically and handles leadership.

**Deliverables:**
- Global chat sending with message templates
- `hostage_select` mode with role-appropriate selection algorithm
- `seek_leadership` / `usurp` modes
- `summit_interact` mode
- `relay_intelligence` mode
- Incoming message parsing and knowledge update

**Acceptance criteria:**
- Agent sends contextually appropriate global chat messages
- Leader-agent makes correct hostage picks (never sends own key role)
- Agent successfully usurps hostile leaders when majority available
- Agent communicates intel to allies via available channels
- Agent correctly interprets incoming chat from allies

### Phase 5: Advanced Play (Week 5)

**Objective:** Deception, Spy play, counter-intelligence.

**Deliverables:**
- Deception framework (deception state, lie tracking, camouflage)
- Spy-specific evaluator and modes (infiltration, cover management)
- `time_waste` and `decoy` modes
- Counter-intelligence heuristics (detecting enemy deception)
- Behavioral inference engine (flagging suspicious behavior)

**Acceptance criteria:**
- Grunt agents successfully run decoy plays (draw enemy attention)
- Spy agent maintains cover through at least 2 rounds of infiltration
- Spy agent relays intelligence to real team at least once
- Agent detects and flags obviously inconsistent behavior from others
- Deception state prevents self-contradiction across interactions

---

### Testing Strategy

Each implementation phase has quantitative acceptance criteria. Testing
uses a combination of automated trace analysis and live game validation.

**Phase 1-2 (Core Loop + Information Gathering):**
- **Method:** `scripts/capture.py` with Eurydice as the player agent and
  baseline fillers. Capture 3+ games across `short` and `empty3` presets.
- **Metrics:** Parse capture metadata for: role detection latency (ticks
  from RoleReveal to `my_role` populated), whisper creation success rate,
  color/role exchange completion rate.
- **Pass criteria:** Role detected within 120 ticks. Whisper creation
  succeeds >90% of attempts (when target is cooperative). Exchange
  completion >80%.

**Phase 3-5 (Strategic + Social + Advanced):**
- **Method:** Full multi-agent match via `run_agents.py eurydice:10`
  against the `medium` preset (180s/120s/60s rounds, 10 players).
  Enable tracing (`--trace-dir`). Run 5+ matches with different seeds.
- **Metrics from traces:** Key exchange completion rate (by role), rounds
  to exchange completion, win rate (Eurydice vs Eurydice = should be
  ~50/50; Eurydice vs baseline = should win majority), usurp success
  rate, hostage pick correctness (never sends own key role).
- **Pass criteria:** Key exchange completed in >70% of games where
  partner is reachable. Win rate vs baseline >60%. Zero cases of
  sending own key role as hostage.
- **Regression:** Run after every significant change. Compare metrics
  against prior baseline.

---

## Key Design Decisions

### Why deterministic mechanics with LLM-assisted strategy?

- **Latency:** button timing, menu navigation, entry grants, and phase
  overrides must remain deterministic because 15-second rounds leave little
  room for slow or retry-heavy control loops.
- **Determinism:** perception, belief updates, mechanical exchange truth, and
  safety guards need reproducible behavior for tests and trace review.
- **Social complexity:** probe priority, reveal decisions, global/whisper
  messages, deception, and coalition management are where pure rules become
  brittle. These are the surfaces that should move toward LLM assistance.
- **Operational safety:** the LLM should choose semantic actions from a closed
  schema, not press buttons or invent unsupported modes. Runtime code validates
  legality and falls back to deterministic policy when needed.

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

### Why formalize the probe cycle?

Round durations can be as short as 15 seconds, making every interaction
expensive. Without explicit time budgeting, the agent would:
- Start interactions it can't finish
- Linger in whispers beyond the point of useful information
- Fail to abort losing interactions
- Waste the majority of its limited round time on overhead

The probe cycle as a first-class concept forces the design to account
for the temporal cost of every action.

### Why separate infiltration from standard probing?

The Spy's whisper protocol is fundamentally different:
- Standard: maximize information extraction
- Spy: maximize information extraction WHILE maintaining false identity

The difference isn't just "what actions to take" but "what actions to
AVOID" (never accept R.OFFER from enemies). This inverted logic needs
a separate protocol variant to prevent accidental cover breaks.

---

## Belief State Extension Keys Registry

All `belief_state.ext` keys used by Eurydice, with types and lifecycle.
This prevents namespace collisions and documents the agent's memory
footprint.

| Key | Type | Lifecycle | Purpose |
|-----|------|-----------|---------|
| `eurydice_accumulators` | `GlobalAccumulators` | Game lifetime | Behavioral tracking per player |
| `player_knowledge` | `dict[PlayerID, PlayerKnowledge]` | Game lifetime | Extended knowledge model |
| `strategic_state` | `StrategicState` | Rebuilt each meta_decide | High-level reasoning context |
| `whisper_exchange_state` | `WhisperExchangeState` | Whisper lifetime | Parsed system message events |
| `scout_state` | `ScoutState` | Mode lifetime (scout) | Waypoint and sweep state |
| `hold_position_state` | `HoldPositionState` | Mode lifetime | Leadership/wander state |
| `whisper_mode_state` | `WhisperModeState` | Mode lifetime (in_whisper) | FSM state machine |
| `mode_complete` | `bool` | Per-tick flag, cleared on read | Mode -> meta_decide completion signal |
| `found_target` | `PlayerID` | Per-tick flag | Scout -> meta_decide target discovery |
| `whisper_exit_reason` | `str` | Per-tick flag | Why whisper ended (normal/forced_ejection) |
| `last_directive_mode` | `str` | Persistent (ext) | Hysteresis: last mode produced |
| `last_directive_tick` | `int` | Persistent (ext) | Hysteresis: when last mode was set |
| `_last_phase` | `Phase` | Persists in inferences | Phase-change detection |
| `_last_exchange_status` | `bool` | Persists in inferences | Exchange-completion detection |
| `_last_partner_found` | `bool` | Persists in inferences | Partner-discovery detection |
| `_eurydice_prev_strategic` | `dict` | Persists in inferences + extra | Strategic state change detection |
| `_eurydice_whisper_exit_logged` | `bool` | Mode lifetime (in_whisper) | Prevents duplicate whisper_exit log |

Hysteresis keys (`last_directive_mode`, `last_directive_tick`) are stored
in `belief_state.ext` (persistent across ticks) rather than `inferences`
to avoid fragility from missed propagation. Keys prefixed with `_` are
stored in `inferences` (replaced wholesale each iteration) and must be
re-included by every code path that returns inferences. All others are
stored directly on belief_state via hooks or mode_enter.

---

## Open Questions (Audit)

All items resolved. Original audit identified 24 issues (3 critical, 5
major, 8 moderate, 5 minor, 3 structural) by cross-referencing this
document against RULEBOOK.md, GAME_API.md, and the upstream server
source. Resolutions have been applied inline throughout the document.
Key corrections:

- Summit is chat-only (no mechanical exchanges); design rewritten
- P_FINAL partner-unreachability logic corrected
- Exchange screen shows other leader only to leaders (not all players)
- Probe cycle timing made config-adaptive (15s-300s rounds)
- Urgency computation uses relative round position, not hardcoded rounds
- Color exchange confidence conditional on Spy presence
- Minimap viewport-boundary behavior verified and cited
- Cross-round behavioral accumulators specified
- Hostage-select honors ally "SEND ME" requests
- Interaction range defined (BUBBLE_RADIUS = 20px)
- Multi-occupant eavesdrop guard added for key roles
- OCR resilience layers specified
- Hysteresis moved to persistent storage
- Probe failure escalation specified
- Testing strategy added

---

## Observability and Instrumentation

Eurydice emits structured JSONL events at every decision point via the
Orpheus `Logger`. Events are guarded behind a module-level proxy singleton
(`agents/eurydice/log.py`) that is falsey until `policy.py` wires the
concrete logger at startup.

### Log Levels

| Level | What fires |
|-------|-----------|
| `events` | Orpheus infrastructure plus compact Eurydice lifecycle signals needed for live audit: strategic state changes, probe target/attempt/completion/failure, tick metadata, and view/task/mode transitions |
| `decisions` | Detailed implemented agent decisions: meta_decide reasons, whisper FSM transitions, inference firings, and deception-helper decisions when those helpers are invoked |
| `verbose` | Everything above plus: evaluator branch traces, min-duration holds, periodic strategic state snapshots (every 24 ticks) |

### Event Catalog

| Event Type | Level | Source | Key Fields |
|-----------|-------|--------|------------|
| `meta_decide_reason` | decisions | `meta_decide.py` | reason, mode, evaluator, mode_complete, ticks_in_mode |
| `strategic_state_change` | events | `meta_decide.py` | Only changed fields from the compact strategic snapshot: my_role, my_team, my_room, key_partner_found, key_exchange_done, partner_location, enemy_key_location, urgency, current_objective, spy_in_game_config, round_number, current_phase, ticks_remaining_in_phase, round_schedule |
| `strategic_state_snapshot` | verbose | `meta_decide.py` | Full state including game_elapsed_ticks (fires every 24 ticks) |
| `evaluator_branch` | verbose | `evaluators.py` | role, branch, mode |
| `probe_target_selected` | events | `modes.py` | target, round |
| `probe_attempt_started` | events | `modes.py` | target, round, action |
| `whisper_created` | events | `modes.py` | target, round |
| `entry_requested` | events | `modes.py` | target, round |
| `probe_failed` | events | `modes.py` | target, round, reason, failures_this_round |
| `probe_completed` | events | `pipeline.py` | target, started_tick, total_ticks |
| `whisper_fsm_transition` | decisions | `whisper_mode.py` | old_state, new_state, protocol, target, tick_in_whisper |
| `whisper_protocol_selected` | decisions | `whisper_mode.py` | protocol, reason, occupants, hostile_present |
| `whisper_exchange_outcome` | decisions | `whisper_mode.py` | exchange_type, action, target, our_offer |
| `whisper_exit` | decisions | `whisper_mode.py` | reason, protocol, total_ticks |
| `inference_fired` | decisions | `pipeline.py` | rule, player_id, inference_type, old_value, new_value, confidence, source |
| `deception_decision` | decisions | `deception.py` | should_deceive, reason; emitted only when runtime code calls the deception helper |
| `lie_recorded` | decisions | `deception.py` | target, lie_type, content, consistent |
| `cover_blown` | decisions | `deception.py` | reason |

### Frame Recording

Raw WebSocket frames can be recorded for post-mortem replay and overlay
rendering. Enabled via `--record-frames DIR`. Output format is a binary
file (`{name}_{timestamp}.frames`) with records of:

```
[4 bytes: tick (uint32 LE)] [4 bytes: frame length (uint32 LE)] [N bytes: raw frame]
```

Frames are correlated to log events via the shared `tick` field.

### Usage

```bash
# Normal operation with decision-level logging
python run_agents.py eurydice:10 --log-level decisions

# Full verbosity with frame recording
.venv/bin/python agents/eurydice/policy.py \
    --url ws://localhost:2500/player --name eurydice_1 \
    --log-level verbose --record-frames /tmp/frames
```

### Extension Keys (Instrumentation)

| Key | Type | Purpose |
|-----|------|---------|
| `_eurydice_prev_strategic` | `dict` | Previous strategic snapshot for change detection |
| `_eurydice_whisper_exit_logged` | `bool` | Prevents duplicate whisper_exit events |

---

## Reference Documents

- `HADES_STRATEGY.md` -- Hades role strategy
- `CERBERUS_STRATEGY.md` -- Cerberus role strategy
- `SHADE_STRATEGY.md` -- Shade grunt strategy
- `PERSEPHONE_STRATEGY.md` -- Persephone role strategy
- `DEMETER_STRATEGY.md` -- Demeter role strategy
- `NYMPH_STRATEGY.md` -- Nymph grunt strategy
- `SPY_STRATEGY.md` -- Spy role strategy (both team variants)
- `../orpheus/DESIGN.md` -- Orpheus framework specification
- `../RULEBOOK.md` -- Game rules and mechanics
- `../GAME_API.md` -- Technical API reference
