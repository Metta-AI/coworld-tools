# guided_bot — Design Report (v0.5)

> **Status:** phases 0–6.6 implemented. Phase 0 scaffolded the type
> system and no-op pipeline. Phase 1 (1.0–1.6) built the full
> perception pipeline. Phase 2 (2.0–2.7) built the action layer
> (button masks, hierarchical waypoint navigation) and six mode handlers
> (`task_completing`, `meeting`, `hunting`, `pretending`, `reporting`,
> `fleeing`) plus the four-reflex system. Phase 3 (3.1–3.6) wired the
> LLM guidance loop: `snapshot.nim` renders beliefs to JSON,
> `llm.nim` calls the Anthropic Messages API via curly+jsony,
> `guidance.nim` runs a worker thread with channels, `bot.nim`
> submits snapshots periodically/on-trigger and reads directives,
> `modes/meeting.nim` executes LLM-driven chat/vote actions with a
> safety-net fallback, and `prompts.nim` holds system prompts.
> Phase 4 added the structured trace writer (7 JSONL streams +
> manifest). Phase 5 added fallback-only playability: a stale-default
> re-evaluation in `reconcileDirective` that transitions idle→gameplay
> modes on role detection, fixture-replay fallback tests (8th test
> suite), and a Docker-compatible `mettagrid.bitworld` import
> fallback. Phase 6 completed the core mode lifecycles and replaced
> per-pixel runtime pathfinding with the hierarchical waypoint system
> described in §6.3 and `NAVIGATION_DESIGN.md`.
>
> **Audience:** future self, collaborators, and the LLM harness that will
> eventually consume this file. This doc describes the *shape* of the
> agent and the decisions already made. Where the implementation
> diverges from earlier design sketches, the implementation wins and
> this doc has been updated to match.
>
> **Related reading** — load-bearing context:
>
> - `bitworld/among_them/players/how_to_make_a_bot.md` — the hard-won
>   lessons about localization, task states, radar, momentum, voting.
>   Still all applicable.
> - `bitworld/src/bitworld/ais/{claude,openai}.nim` — existing Nim HTTP
>   LLM clients (`curly` + `jsony`, ~60 LOC each). We adapt these.
> - `bitworld/among_them/players/italkalot.nim` — existence proof of a
>   Nim-native Among Them bot making live LLM calls.
> - `metta/packages/cogames/POLICY_SECRETS.md` — how API keys reach the
>   policy subprocess in the tournament (env-var injection via
>   `--secret-env`). The LLM is a first-class submission citizen.
>
> **Deprecated reference:** the local `among_them/modulabot/` tree is
> historical-only. Do not inspect, modify, test, run, or rely on it for
> guided_bot work unless James explicitly asks for modulabot. Older
> references to modulabot in this design record provenance, not current
> implementation guidance.

---

## 1. Goals & non-goals

### Goals

1. **A single agent with two time scales.** An inner loop at game tick
   rate (~24 Hz) and an outer loop at LLM-call rate (fractions of a Hz),
   cooperating through a narrow, well-defined interface. The inner loop
   is always responsive; the outer loop is always thinking.
2. **Modular, extensible, easy to reason about.** The primary
   extensibility axis is **modes**. Adding a new mode (a new way for
   the bot to behave) is a new file implementing one interface, with no
   changes to perception, action, or the core loop.
3. **Uniform belief state.** Every mode consumes the same structured
   belief-state object. Modes disagree about *what to do*, never about
   *what is true*.
4. **LLM-in-the-loop strategy, with LLM-in-the-loop control during
   meetings.** The LLM shapes the active mode + parameters during
   gameplay. In meetings, the LLM drives actions directly (chat line
   or vote) rather than submitting a single plan up front.
5. **The LLM is part of the submission, not an accelerant.** We ship
   the LLM. We also ship safe defaults in case it fails mid-match. But
   we don't ship a version of the bot that isn't trying to talk to an
   LLM.
6. **Graceful degradation.** If the LLM is slow, rate-limited, or
   transiently unreachable, the bot keeps playing competently on the
   most recent directive or the default.
7. **Cogames-submission-ready.** Bundle format, Nim-via-ctypes wrapper,
   and validation gate follow the current guided_bot submission wrapper.
   LLM keys flow in via `--secret-env` (cogames' documented mechanism).

### Non-goals (v0)

- **No dependency on local modulabot.** Perception kernels live under
  `among_them/common/perception_kernels/` and guided_bot owns its own
  baked data, orchestration, tests, and trace schema.
- **No training.** No neural policies, no RL.
- **No games other than Among Them.**
- **No parity bar with deprecated modulabot.** Guided_bot owns its
  behavior. Historical modulabot behavior is not a target unless James
  explicitly asks for a comparison.
- **No LLM-per-tick.** Not even in meetings. The LLM is event-driven
  during meetings, not polled at 24 Hz.

---

## 2. Architecture at a glance

```text
                     ┌──────────────────────────────────┐
                     │        GUIDANCE LOOP             │
                     │   (worker thread, LLM-driven)    │
                     │                                  │
                     │   belief snapshot ──► LLM ──►    │
                     │                     directive    │
                     └──────────────┬───────────────────┘
                                    │
                     directive = (mode, mode_params, meta)
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────┐
│                      INNER LOOP (24 Hz)                   │
│                                                           │
│   frame ──► perceive ──► update belief ──► decide ──► act │
│                                ▲              ▲           │
│                                │              │           │
│                                │           mode registry  │
│                                │           ┌──────────┐   │
│                                │           │ mode foo │   │
│                                │           │ mode bar │   │
│                                │           │   ...    │   │
│                                │           └──────────┘   │
│                                │                          │
│                                └── current directive      │
└───────────────────────────────────────────────────────────┘
         │                                         │
         ▼                                         ▼
  persistent state:                         persistent state:
    belief store                              action layer (route,
    per-mode scratch                          edge progress, task-hold)
```

The three first-class components:

- **Inner loop** — perceive, update belief, decide, act. Deterministic
  given `(belief, directive, persistent state)`. Never blocks on the
  LLM.
- **Guidance loop** — a Nim worker thread. Periodically and on
  triggers, it reads a belief snapshot, asks the LLM, validates the
  response, and writes a directive to a shared slot.
- **Belief state** — the single shared world model. Consumed by every
  mode, serialized for the guidance loop, logged into the trace.

Two additional pieces of persistent state, both owned by the inner
loop:

- **Per-mode scratch state** — one slot per mode, reset on mode
  switch, read/written only by that mode's handler. Holds things like
  fake-task timers, investigation deadlines, kill-approach sub-state.
- **Action-layer state** — current waypoint-graph route, edge
  progress, vent traversal state, last-emitted mask, task-hold
  discipline. Owned by the action module, persisted across ticks.

The rest of this document describes these components and their
interactions.

---

## 3. The belief state

The belief state is the agent's working model of the world. It is:

- **The same structure for every mode.** Modes may look at different
  slices; they never disagree on schema.
- **The same structure the LLM sees,** after a lossy serialization
  (raw frames and patch tables don't cross the thread boundary).
- **The same structure the trace snapshots capture** (see §11).

### Conceptual layers

1. **Self.** Role (crew / imposter / ghost), alive / dead, colour,
   kill cooldown remaining (imposter), known teammate colours
   (imposter), home position, current mode, current directive,
   current phase (gameplay / interstitial / voting).
2. **Perception.** Camera lock, self world position, visible actors
   (colour + position + last-seen tick), visible bodies, visible task
   icons, radar dots, interstitial state, voting parse when
   applicable. Guided_bot owns this pipeline; shared hot kernels live
   under `among_them/common/perception_kernels/`.
3. **Memory.** Per-player summary (role [unknown / crewmate /
   imposter], alive flag, last seen tick/place, times near bodies,
   times witnessing kills, alibi evidence, vote history, ejected
   flag); per-body event; per-meeting event; sightings log. Role and
   alive fields are populated during gameplay; imposter roles are
   detected from the role-reveal interstitial via palette-colour
   scanning.
4. **Tasks.** Per-task-station state: `not_doing` / `checkout`
   (radar-dot confirmed) / `confirmed` (icon visible) / `completed`
   (hold confirmed, icon disappeared). Plus `checkout` latch,
   `iconMissCount` for negative evidence, `resolvedNotMine` flag.
   Populated by `updateTaskState` in the belief-merge stage (phase
   6.1). See `TASK_COMPLETING_DESIGN.md` §4 for the full spec.
   For ghosts: the task layer is the same; ghosts complete their own
   tasks (see §5.7).
   The static `TaskStation` record in `data.nim` carries precomputed
   `passableCX/passableCY` — the geometric centre snapped to the
   nearest walkable pixel at init time. All modes that steer toward
   task stations use these instead of computing the raw centre inline,
   so the waypoint system receives a reachable target (see §6.3 for
   the full rationale).
5. **Social.** Recent chat lines from guided_bot's voting-screen OCR,
   accusations heard, votes cast, votes received, most-recent meeting
   transcript.
6. **Directive.** Current mode, mode parameters, directive source
   (`llm` / `default`), issue tick, TTL, reasoning (debug only).
7. **Flags.** Recent "wake up" events for the guidance loop to
   notice — body seen, kill cooldown elapsed, new chat line, meeting
   started, role revealed.

### Invariants

- The belief state is updated **only** by the perceive/update phase of
  the inner loop. Modes and the guidance loop both read it; neither
  writes it (except the directive slot, written only by the guidance
  loop, atomically).
- Every field carries a `last_updated_tick` where it makes sense.
  Modes are free to treat stale fields as they wish; the belief layer
  doesn't lie.
- The belief state is cheaply snapshottable (JSON-serializable
  sub-record-by-sub-record). Snapshotting is O(state size), not O(map
  tile count).

### What's explicitly *not* in the belief state

- Raw framebuffers. Consumed, unpacked, and discarded per tick by the
  I/O layer.
- Patch-hash tables and sprite atlases. Perception machinery, not
  beliefs.
- **Per-mode scratch state.** See §5.6. Modes own their own transient
  memory. The belief captures world truth; mode scratch captures
  agent planning.
- **Action-layer state.** Current waypoint-graph route, edge progress,
  vent traversal state, and task-hold counters. Lives in the action
  module.

The belief is passed by const reference to modes. Modes cannot
invalidate any other mode's view of the world.

---

## 4. The inner loop

The inner loop is a pipeline with four stages.

```text
frame ──► perceive ──► update belief ──► decide ──► act
           (read)         (write)         (read)    (write)
```

### 4.1 Perceive

- Input: raw frame, previous belief.
- Output: a percept — the delta of what this frame says about the
  world (camera lock, visible actors/bodies/icons/radar dots,
  interstitial/voting state, new chat lines, role reveal, game-over).
- Uses guided_bot's perception pipeline. Shared hot kernels live in
  `among_them/common/perception_kernels/`; orchestration, baked data,
  and belief-facing percept types are guided_bot-owned. The percept is
  a small typed struct; merging it into belief is the next stage's job.

### 4.2 Update belief

- Input: previous belief, current percept, latest directive from the
  guidance loop's slot (atomic read).
- Output: new belief.
- Responsibilities:
  - Merge percept into perception fields.
  - Maintain memory (sightings log, per-player summaries, body /
    meeting events). Round-reset on role-reveal interstitial.
  - Task-state transitions (`not_doing` / `checkout` / `confirmed` /
    `completed`) per `TASK_COMPLETING_DESIGN.md`.
  - Update the directive slot (atomic swap in the latest LLM output
    if one is pending; expire the current directive if TTL elapsed,
    falling back to the per-role default).
  - Raise / clear flags for the guidance loop (body seen, kill
    ready, new chat, meeting started).

### 4.2a Reconcile directive

- Input: current belief (after update-belief).
- Output: potentially modified directive + mode switch.
- Runs after update-belief, before decide. Responsibilities:
  - **Ghost override** (§5.7): force `task_completing` if ghost.
  - **Evaluate reflexes** (§5.8) via `reflex.evaluateReflexes`.
    If a reflex fires, perform a mode switch (on_exit / on_enter)
    and raise `WakeReflexFired` so the guidance loop snapshots.
  - **Illegality fallback**: if the current mode is not legal for
    the current belief state, fall back to the role-appropriate
    default directive.

### 4.3 Decide

- Input: belief (with current directive, already reconciled by §4.2a).
- Output: action intent (§6).
- Responsibility: look up `belief.directive.mode` in the mode
  registry (§5.2) and call `decide(belief, mode_params, scratch)`.
  That's all it does. No strategy lives here — only routing.
- Ghost override, illegality fallback, and reflex evaluation all
  happen in the reconcile step (§4.2a) before decide runs.
- **Reflexes are not evaluated here.** They live in §4.2a because a
  reflex needs to be able to install a new directive and have *that
  mode's* decide logic run on the same tick. See §5.8.

### 4.4 Act

- Input: action intent (§6).
- Output: button mask, optional chat payload.
- Owns all persistent tactical state:
  - Current waypoint-graph route + edge progress.
  - Motion model (velocity, previous position).
  - Last emitted mask (edge detection, "only send on change").
  - Vent traversal retry state.
  - Task-hold state (currently holding A for task completion?).
- Delegates pathfinding to a precomputed waypoint graph
  (`navigation.nim`). Path-following uses baked pixel-paths between
  waypoints. No runtime A\* or jiggle.
- Translates the `discipline` hint into a movement policy:
  `normal` = momentum steering; `task_hold` = hold A only, no
  movement; `kill_strike` = direct line, press A on contact;
  `report` = direct line, press A in report range.

**Modes do not know about the waypoint graph, path edges, or button
bits.** The action layer is the single place those live.

---

## 5. Modes

A **mode** is a named strategy. It owns one conceptual behavior.
Modes are the primary extensibility surface — almost all iteration on
this bot will happen by adding or refining mode handlers.

### 5.1 The mode interface

Every mode implements:

- `decide(belief, params, scratch) -> action_intent`
- `is_legal_for(belief) -> bool`
- `on_enter(belief, params, scratch)` — initialize scratch state.
- `on_exit(belief, scratch)` — clean up (usually a no-op).
- `default_params_for(belief) -> params` — used when the mode is
  selected as a fallback default and no LLM params are available.

### 5.2 Mode registry

Modes are registered in a single table (mode-name → handler record).
The decide stage looks up by name, calls `is_legal_for`, calls
`decide`. Adding a mode is one new file + one new line in the
registry; no core-loop changes.

### 5.3 Mode parameters

Each mode takes a `mode_params` blob alongside the belief. **The LLM
picks a mode from the enum and fills in a params object conforming to
that mode's schema.** Schemas are small, structured, and validated
before the directive is published to the inner loop.

**First-pass param schemas** for the modes in §5.4. These will
change; they are starting points, not contracts.

```text
idle {
  # Stand somewhere, observe, respond to reflexes only.
  linger_at?: point        # specific spot to hold near
  near_group: bool         # prefer to be near ≥1 other player
}

task_completing {
  # Crewmate default and ghost default.
  # Phase 6.1: three-phase hold lifecycle (Navigate → Hold → Confirm)
  # with belief-layer task state, tiered target selection, and
  # icon-disappearance completion detection. Full spec in
  # TASK_COMPLETING_DESIGN.md.
  target: TaskTarget       # see below
  abandon_on_nearby_body: bool   # crew: interrupt to report (default true)
}
# TaskTarget is one of:
#   { kind: "index",             task_index: int }
#   { kind: "nearest_mandatory" }
#   { kind: "nearest_any" }
#   { kind: "specific_room",     room_id: int }

fear {
  # Stay near others, avoid empty rooms.
  min_visible_others: int     # default 2
  prefer_room?: room_id       # optional safe-zone hint
  max_distance_from_group: int
}

investigating {
  # Go gather evidence on someone or something.
  target: InvestigateTarget
  timeout_ticks: int          # bail if nothing new observed
}
# InvestigateTarget is one of:
#   { kind: "color",    color_index: int }
#   { kind: "location", x: int, y: int }     # e.g. last-known body spot
#   { kind: "room",     room_id: int }

reporting {
  # A body is known; navigate to report range, press A.
  body_location: point
}

pretending {
  # Imposter: walk task-to-task, don't actually do them.
  target: TaskTarget          # same shape as task_completing
  loiter_ticks: int           # how long to "fake-do" on arrival
  may_swap_on_witness: bool   # if a new witness appears, reroll target
}

hunting {
  # Imposter: look for a kill. Full design in HUNTING_DESIGN.md.
  preferred_target?: color_index
  max_witnesses: int
  opportunistic: bool
  cover_mode: "pretending" | "idle"
}

fleeing {
  # Imposter: a body was just seen; put distance between us and it.
  away_from: point
  min_distance: int
  duration_ticks: int
}

alibi_building {
  # Imposter: loiter visibly near a specific crew in a public room.
  companion_color: int
  room?: room_id
  min_duration_ticks: int
}

meeting {
  # Special. LLM is in direct control during this mode (§7).
  # Params are set once at meeting start; LLM drives from there.
  want_to_speak_first: bool
}

sabotage_watching {
  # Placeholder — activate only if the season enables sabotage tasks.
  station: enum              # vent, lights, comms, ...
}
```

Field names above are conceptual; the Nim implementation uses
prefixed discriminated-union fields (e.g., `huntPreferredTarget` for
hunting's `preferred_target`). See `types.nim:230-271` for exact field
names.

All `color_index`, `room_id`, `task_index`, `point` types are ints /
tuples of ints; the exact enumerations come from the game constants
(see `among_them/README.md` § Game constants).

### 5.4 Mode enumeration

Same list as v0.1. The `ghost_observing` mode is dropped — ghosts use
`task_completing` (§5.7).

**Crewmate modes** (also used by imposters pretending to be crew):
`idle`, `task_completing`, `fear`, `investigating`, `reporting`.

**Imposter modes** (alive, non-ghost):
`pretending`, `hunting`, `fleeing`, `alibi_building`,
`sabotage_watching`.

**Shared:** `meeting`.

### 5.5 Mode exclusivity

One active mode at a time. No multiplexing.

Mode switching is driven by:

- **The LLM** issuing a new directive.
- **The default fallback** kicking in when the current directive's
  TTL expires or becomes illegal.
- **Reflex interrupts** (§5.8) forcing a mode switch to a
  situationally-appropriate mode. Reflexes perform a full mode
  switch (on_exit / on_enter / scratch reset), not a single-tick
  override.

### 5.6 Per-mode scratch state

Each mode has its own scratch slot. Lifecycle:

- **Reset on mode switch.** `on_exit(old_mode)` runs (cleanup),
  `on_enter(new_mode)` runs (initialization with fresh scratch). The
  new mode starts from a clean state.
- **Preserved across directive-changes within the same mode.** If
  `pretending` is active and the LLM re-issues `pretending` with
  different params, the scratch is preserved and the mode's
  `decide()` is responsible for reconciling old scratch with new
  params (usually: reset the planning substate, keep observational
  caches).
- **Never read by another mode.** Private by convention; the registry
  only gives each mode access to its own slot.
- **Not included in snapshots to the LLM.** The LLM sees the belief
  state; it does not see the currently-active mode's internal
  planning state. (If we later find it helpful, we add an opt-in
  `summarize_for_llm(scratch) -> json` hook per mode — see §12.6.)

Scratch state examples:

- `investigating.scratch` — deadline tick, points-of-interest list.
- `hunting.scratch` — target color, last-seen position, cover patrol
  station, kill-confirmation state. See `HUNTING_DESIGN.md` §8.
- `pretending.scratch` — current fake target, loiter timer,
  fake-hold deadline, witness-swap flag.

### 5.7 Ghosts

**Ghosts complete tasks.** A crewmate who is ghosted still has their
original task list and can still contribute to the crew win condition
by ticking them off. So:

- Ghost default directive = `task_completing { target:
  nearest_mandatory, abandon_on_nearby_body: false }`.
- `task_completing` mode's handler checks `belief.self.is_ghost` and
  passes a ghost-aware hint to the action layer:
  - Ghosts can move through walls → the action layer bypasses the
    waypoint graph and uses straight-line steering.
  - Ghosts don't react to bodies, kills, or imposter threats → no
    reflex interrupts fire.
  - Ghosts don't report.
- Ghosts do not get any other mode. The LLM's directive is overridden
  to `task_completing` as soon as `is_ghost` becomes true. (One of
  the standing validation rules in §8.4.)

### 5.8 Reflex interrupts (reflex = forced mode switch)

A **reflex** is a fast-reacting mode transition that fires without
waiting for the LLM. Reflexes handle situations where the ~1-5 s LLM
round trip is too slow (body appears, kill window opens, voting
screen appears).

**A reflex does not override a single tick's action. It forces a
mode switch.** The rationale: a single tick is too little to
accomplish anything strategic; the real handling of the situation
belongs in some other mode's `decide` logic. Reflexes route into
that mode — they don't duplicate its logic.

#### Mechanics

- Reflexes are defined centrally in `reflex.nim` as a prioritized
  list. Each reflex has a condition, a target mode, and a
  params-builder function.
- Reflex evaluation happens in the **reconcile-directive stage**
  (§4.2a), after update-belief and before decide. This is important:
  reflex evaluation can install a new directive *before* decide
  reads it, so the target mode's `decide()` runs on the same tick
  as the triggering event. No one-tick bridging action is needed.
- When a reflex fires:
  1. The target params are built from the current belief (e.g.
     `reporting`'s `body_location` is set from the just-observed body).
  2. The old mode's `on_exit` runs; the new mode's `on_enter` runs;
     scratch state resets.
  3. A new directive is written to the slot with
     `source: SourceReflex`, `reflexName: <id>`.
  4. `WakeReflexFired` is raised so the guidance loop snapshots
     next cycle.
  5. The decide stage runs normally; the new mode's handler
     produces this tick's action.

#### Edge-triggered, not level-triggered

Reflex conditions fire on **transitions**, not persistent state:

- `body_newly_in_view` fires on the tick a new body first enters
  perception, not every tick while it remains visible.
- `kill_cooldown_just_elapsed` fires on the tick the timer reaches
  zero, not every tick after.
- `voting_screen_appeared` fires on the tick the interstitial
  begins, not every tick of the voting phase.

Edge-triggering is how we avoid thrashing: once a reflex has fired
and the LLM has had a chance to respond (or to re-issue the
pre-reflex mode), the reflex won't keep firing on the same
situation.

#### Anti-thrash guard

If the LLM responds to a reflex-triggered mode switch by trying to
put us back in the pre-reflex mode, and the reflex condition is
still present, we'd ping-pong without this rule:

- A reflex cannot fire again within `ReflexCooldownTicks` (96 ticks
  ≈ 4 s at 24 Hz) of its last firing, **per-reflex**. Each of the
  four reflexes tracks its own cooldown independently
  (`reflex.nim:ReflexState`).

This means the LLM is allowed to overrule the reflex and ride the
same situation through without another reflex interruption, at
least for `ReflexCooldownTicks` ticks.

#### The initial reflex set

Short on purpose. Every reflex is a mini-policy-without-an-LLM;
they add up to a shadow policy if we aren't careful.

| Mode | Condition | Switch to | Reason |
|---|---|---|---|
| `task_completing` (crew, alive, not ghost) | `body_newly_in_view` | `reporting { body_location: <body.position> }` | Let the dedicated reporting mode handle navigation + A press. Crewmate gets a fresh body → go report it, regardless of current task. |
| `hunting` (imposter, alive) | `body_newly_in_view` | `fleeing { away_from: <body.position>, min_distance: 48, duration_ticks: 240 }` | Don't hang around a corpse. See `HUNTING_DESIGN.md` §10.2 for details. |
| `pretending` (imposter, alive, not ghost) | `kill_ready AND visible_crewmates == 1` | `hunting { preferred_target: <color>, max_witnesses: 0, opportunistic: false, cover_mode: pretending }` | Route a kill opportunity into hunting mode. See `HUNTING_DESIGN.md` §10.1 for details and watchpoints. |
| any mode | `voting_screen_appeared` (edge: `prevPhase != PhaseVoting`) | `meeting { want_to_speak_first: false }` | Meetings are an LLM-driven mode; switch immediately and let meeting's decide handle it. |

The `pretending → hunting` reflex is the most aggressive — it
performs a kill without LLM approval. See `HUNTING_DESIGN.md` §10.1
for full rationale and watchpoints.

#### Reflex vs. illegality fallback

Reflexes are a different mechanism from the §4.3 illegality
fallback. Illegality fallback replaces an invalid directive with
the role-default (defensive, always safe). Reflexes replace a
*legal* directive with a situationally-better one (proactive,
strategy-shifting). They're traced separately
(`reflexes.jsonl` vs. `guidance.jsonl` → `directive_expired`).

---

## 6. The action intent

The output of every mode. A small, flat record:

- `steer_to: point | none` — destination. Action layer owns waypoint
  routing and tactical steering to get there.
- `press_a: bool`
- `press_b: bool`
- `cursor: left | right | none` — meeting-screen cursor movement.
- `chat: string | none` — meeting mode only.
- `discipline: normal | task_hold | kill_strike | report | wander | no_op`
  — hint to the action layer.

(`facing: direction | none` was in the original design for cases
where facing matters without movement. Deferred — not implemented
in phase 2.)

The action layer translates this into a button mask. The mode never
touches a button bit directly.

### 6.1. `DisciplineWander`

Added to support the idle-mode pre-localization wander. Emits raw
direction buttons without waypoint routing, walk-mask checks, or
localization gates. When `steer_valid` is true, steers toward
`steer_to` using whatever (possibly stale) self-position the bot has.
When `steer_valid` is false, cycles through cardinal directions based
on a tick-modulo phase encoded in `steer_to.x` (0=up, 1=right,
2=down, 3=left).

Purpose: the bot must physically move during the window between game
start and the first successful camera lock so the localizer sees fresh
map pixels. All other disciplines either gate on `localized` or
require waypoint routes, making them useless before the localizer
fires.

### 6.2. FFI action-index contract

The Nim FFI (`ffi/lib.nim`) maps button masks to action indices via
`TrainableMasks`. The Python harness maps those indices back to masks
via `mettagrid.bitworld.BITWORLD_ACTION_MASKS`. **These two tables
must have identical ordering.** The canonical pattern is: for each
direction group `{none, up, down, left, right, up+left, up+right,
down+left, down+right}`, emit `{bare, +A, +B}` — 9 directions × 3
modifiers = 27 actions. A compile-time assertion in `ffi/lib.nim`
enforces this; a Python unit test
(`test/test_action_table.py`) cross-checks the `mettagrid` package.

### 6.3. Hierarchical waypoint navigation

The `DisciplineNormal` path through `applyIntent` delegates navigation
to `navigation.nim`. The runtime planner uses a baked waypoint graph
(`perception/baked/nav_graph.json`) with 85 nodes and a baked path
blob (`nav_paths.bin`) containing pixel-paths between adjacent walking
waypoints.

**Strategic planning** finds the nearest waypoint to the current
self-position, the nearest waypoint to `steer_to`, then runs Dijkstra
over the waypoint graph. The graph is small enough that the simple
O(N²) implementation is effectively free at tick rate. Replans happen
when the goal changes, on a periodic drift-recovery cadence, or after
progress toward the current waypoint stalls.

**Tactical following** consumes the next edge in the strategic route.
For walking edges, the action layer looks up the precomputed
pixel-path, snaps the current position to the nearest path point,
advances monotonically along that path, selects a lookahead point, and
feeds that target to `steerButtons`. If localization drift puts the
bot off the baked edge path, the action layer first steers back to the
edge's start waypoint instead of inventing a new runtime path.

**Ghost mode** bypasses the graph. Ghosts ignore walls, so the action
layer uses straight-line greedy steering directly toward `steer_to`.

**Vent routing** is represented as conditional graph edges. Crewmates
exclude vent edges. Imposters in hunting use `VentIfSafe` (visible
witness check), and fleeing uses `VentAlways`. When the current route
contains a vent edge, the action layer walks to the entry waypoint,
presses B within the server's vent activation range, detects the
teleport by position jump / exit proximity, then resumes normal
edge-following.

**Stall recovery** is route-level, not local collision recovery. The
action state tracks the last tick that waypoint/path progress improved. If
progress times out, it replans from the current localized position.
Defensive no-op windows are reserved for baked-data errors such as a
missing edge or path.

For implementation details, data formats, and tuning constants, see
`NAVIGATION_DESIGN.md`.

---

## 7. Meeting mode — LLM in direct control

Meetings are special. They are:

- Long enough for multiple LLM calls (`voteTimerTicks = 600` ≈ 25 s
  at 24 Hz; typical LLM latency 1-5 s → 5-25 round trips in the
  limit, realistically ≈ 3-8 with prompt size).
- Action-space-minimal (move cursor, press A, emit chat text).
- Language-heavy and high-stakes — precisely the LLM's advantage.

### 7.1 Design

When the `meeting` mode activates, **the inner loop hands the LLM a
direct action channel**. Each LLM turn produces one action:

```text
meeting_action =
  | { kind: "speak",  text: string }
  | { kind: "vote",   target: color_index | "skip" }
  | { kind: "unvote" }                    # re-select before confirmation
  | { kind: "wait",   resume_on: [trigger...] }
  | { kind: "confirm_vote" }              # final, irrevocable
```

The meeting mode's `decide()` is structurally different from other
modes: instead of producing an action intent directly from the
belief, it consults a *pending-meeting-action queue* populated by
the LLM worker thread.

### 7.2 What the LLM sees during a meeting

The meeting-mode snapshot is a superset of the normal gameplay
snapshot (§8.3). It adds, critically:

- **Full speaker-attributed chat transcript of the current
  meeting**, in order. Every message, every speaker, every tick.
  Produced by guided_bot's voting-screen chat OCR + colour-pip
  speaker attribution.
- **Full meeting history from the current round** (previous meetings
  this match, with their chat, votes, and outcomes). Already in
  `belief.memory.meetings`.
- **Current vote tally** as parsed from the voting screen.
- **Who's alive, who's ejected, colour layout of the vote grid**
  (so the LLM can reason about "vote slot 3" mappings if ever
  relevant — though its output uses colour names).
- **My evidence against each remaining player**: per-player summary
  from memory (times near body, times witnessed killing, tasks seen
  doing, alibi evidence).
- **What I've already said / voted this meeting** — from the
  conversation history (§7.3).

The LLM without this context is useless in meetings. The belief
state carrying a full speaker-attributed chat log is not optional;
it's the core input.

### 7.3 Conversation history across LLM calls

**Decision:** Meeting LLM calls carry a persistent conversation
history for the duration of the meeting. Gameplay LLM calls are
stateless.

Rationale: within a meeting, the LLM needs to remember what it has
already said, how it justified its earlier votes, and what commit-
ments it made — otherwise it will contradict itself. Across
gameplay calls, each directive is a fresh decision keyed on the
current belief; no history is needed (and adding it would cost
tokens without obvious benefit).

Mechanics:

- The LLM worker thread holds an in-memory `meeting_conversation:
  seq[Message]` that persists for the current meeting.
- First meeting call: system prompt + full context + "produce your
  first meeting action".
- Subsequent calls: history so far + "this just happened: <delta>;
  produce your next action".
- Meeting end (ejection confirmed or timer expires): conversation
  is flushed. Next meeting starts fresh.
- Gameplay calls use a separate, stateless prompt each time.

### 7.4 Mechanics (turn-by-turn)

1. On entering `meeting`, the inner loop fires an immediate LLM call
   carrying full meeting context (§7.2) as the first message in the
   new conversation.
2. Each time the LLM returns an action, it goes on the meeting-
   action queue.
3. The meeting mode pops actions and executes them at game tempo:
   `speak` types the line then emits the chat send; `vote` moves
   the cursor toward the target slot; `confirm_vote` presses A.
4. Between actions, the inner loop waits (emits no-ops) unless a
   reflex fires.
5. Triggers that request a new LLM call: new chat line observed,
   vote count changed, cursor arrived at requested slot, meeting
   timer passes thresholds (e.g. < 200 ticks left, < 50 ticks
   left), action queue drained.

### 7.5 Soft-lock on confirmed votes

Once the LLM emits `confirm_vote`, the vote is in. Subsequent LLM
responses cannot unvote or re-vote for this meeting. This prevents
a stream of contradictory LLM calls from silently flipping a
confirmed vote. The LLM is told about this in its system prompt.

### 7.6 Concurrency during meetings

The LLM worker thread (§10) already exists; meeting mode just uses
it more aggressively. The inner loop never blocks. If the LLM is
late, the meeting mode sits idle until an action arrives. The
action queue is a simple `Channel[meeting_action]`.

### 7.7 Fallback

If the meeting timer reaches a safety threshold (e.g. 100 ticks
left) and **no vote has been confirmed**, the inner loop forces a
safe default:

- If the LLM has issued a `vote` but not `confirm_vote`, confirm it.
- Otherwise, move cursor to `skip` and confirm.

This fallback is not configurable by the LLM — it is a structural
backstop that ensures we always cast *some* vote. Trace event
`meeting_fallback_fired` records when this happens.

### 7.8 Chat constraints

- The game only accepts chat during the voting phase; no need to
  queue mid-gameplay.
- Chat packets are emitted one line at a time; the action layer
  rate-limits so we don't DoS the server (some small tick delay
  between consecutive lines).
- The LLM's `speak` text is passed through unchanged except for
  length-truncation to a safe limit (tbd per game constants).

---

## 8. The guidance loop

### 8.1 Responsibilities

- Read belief snapshots.
- Render a prompt and call the LLM.
- Parse and validate the response.
- Publish the validated directive to the shared slot, atomically.
- During meetings, additionally publish meeting actions to the
  meeting-action queue.
- Emit guidance-loop trace entries (prompt, response, parsed
  directive, validation result, latency, token counts).

### 8.2 Cadence and triggers

Hybrid periodic + event-driven:

- **Periodic:** every N game ticks (N ~ 50-120 ≈ 2-5 s). Unconditional
  snapshot.
- **Triggered:** the inner loop raises a flag on the belief
  (`wake_up_reason`) when something important happens — new body,
  kill cooldown elapsed, new chat, meeting started, role revealed,
  directive TTL close to expiring. The guidance thread polls the
  flag and prioritizes triggered snapshots over periodic ones.
- **Throttled:** hard cap on LLM calls per match (`LlmMaxCallsPerMatch`,
  currently 120 in `tuning.nim`) and per
  second (e.g. 1 per 500 ms). If we hit the cap, the loop stops
  calling and the inner loop rides the last directive (or the
  default, if TTL expires).

### 8.3 Snapshot format (for the LLM)

**Decision (per review note #14):** a JSON dump of a curated view of
the belief state. Structure, not prose. Initial shape:

```text
{
  "tick": int,
  "self": { "role": str, "color": str, "is_ghost": bool,
            "alive": bool, "position": [int, int],
            "kill_cooldown_remaining": int,
            "known_imposters": [color, ...] },
  "phase": "gameplay" | "voting" | "interstitial" | "game_over",
  "current_mode": { "name": str, "params": {...},
                    "source": "llm" | "default",
                    "ticks_active": int },
  "visible_now": {
    "players":  [ {"color": str, "position": [int, int],
                   "room": str | null} ],
    "bodies":   [ {"position": [int, int], "room": str | null,
                   "first_seen_tick": int} ],
    "task_icons_on_screen": [ int, ... ]  // task indices
  },
  "memory": {
    "per_player": {
      "<color>": { "role": "unknown" | "crewmate" | "imposter",
                   "alive": bool,
                   "last_seen_tick": int,
                   "last_seen_room": str | null,
                   "times_near_body": int,
                   "times_witnessed_kill": int,
                   "ejected": bool,
                   "votes_against_me": int,
                   "i_voted_for": [tick, ...] }
    },
    "bodies": [ {"tick": int, "room": str, "witnesses": [color, ...]} ],
    "meetings": [ {"start_tick": int, "end_tick": int,
                   "ejected": color | "skip" | null,
                   "chat": [ {"speaker": color, "text": str} ]} ]
  },
  "task_state": {
    "mandatory": [int, ...],  // task indices
    "completed": [int, ...],
    "in_progress": int | null
  },
  "wake_up_reasons": [str, ...],
  "recent_chat": [ {"tick": int, "speaker": color, "text": str} ]
}
```

Budget: not explicitly token-bounded (per review note #14). We'll
measure and trim if it matters.

### 8.4 Validation (before publishing a directive)

The guidance loop validates any LLM response before writing it to the
slot. **The inner loop re-validates on every tick** as defense in
depth.

Checks:

- Mode name is in the registry.
- Mode is `is_legal_for(belief)` — specifically:
  - Role-appropriate (no `hunting` for crew; no `reporting` for
    ghost; etc.).
  - Phase-appropriate (no `hunting` during voting; no `meeting`
    during gameplay).
  - Alive-state-appropriate (ghosts get `task_completing` only; dead
    non-ghost does nothing).
- Params validate against the mode's schema (types, ranges, valid
  enum values, valid color / room / task indices).
- Ghost override: `is_ghost` forces `task_completing` regardless of
  LLM output. Traced as `ghost_override_fired`.

On any failure: log the trace event, drop the directive, keep the
previous one (or the default if TTL has expired).

### 8.5 Conversation policy

Two different conversation modes depending on which phase of the
game we're in:

- **Gameplay calls are stateless.** Each call is `system_prompt +
  current_snapshot + "produce your directive"`. No history. The
  current snapshot already carries `current_mode`, `ticks_active`,
  `wake_up_reasons`, and recent events — that's the memory the LLM
  needs.
- **Meeting calls carry conversation history** for the duration of
  the current meeting (see §7.3). First call = full context;
  subsequent calls = delta. Flushed when the meeting ends.

Rationale: stateless gameplay avoids unbounded token growth across
a match; stateful meetings prevent self-contradiction across
rapidly-issued meeting actions.

Per review note #3, we are not cost-optimizing at this stage.
Conversation history in meetings is unbounded within a single
meeting; we revisit if a single meeting ever blows past a context
window (unlikely at typical meeting lengths and LLM context sizes).

### 8.6 Prompt design

**Out of scope for this document.** Prompt engineering is a separate
track: what system prompt, what examples, what role briefing, what
response format (JSON schema, tool use). The architecture in this doc
survives whatever we pick.

One structural commitment: responses are strict JSON. No free-form
"let me think..." prose in the directive. (The LLM can internally
reason however it likes; we consume only the structured output.)

---

## 9. Failure modes & fallback

The LLM is the primary strategic driver, but it can:

- Be slow (first directive arrives 100+ ticks in).
- Return invalid JSON.
- Return a legal-schema but nonsensical directive.
- Return an illegal-for-role directive.
- Time out.
- Fail the HTTP request.
- Hit the per-match call cap.

The bot must play competently in all of the above.

### 9.1 Default directives

When no usable directive is present (at startup, after TTL expiry,
after an LLM failure), the inner loop picks a per-role default:

- **Crewmate, alive, gameplay** →
  `task_completing { target: nearest_mandatory, abandon_on_nearby_body: true }`
- **Imposter, alive, gameplay** →
  `hunting { preferred_target: none, max_witnesses: 0,
             opportunistic: true, cover_mode: "pretending" }`
  See `HUNTING_DESIGN.md` §12 for rationale.
- **Ghost** →
  `task_completing { target: nearest_mandatory,
                      abandon_on_nearby_body: false }`
- **Dead, not ghost** → `idle {}` (structurally necessary default;
  dead non-ghost players have no meaningful actions)
- **Voting phase, any role** →
  `meeting { want_to_speak_first: false }` (the LLM is still the
  driver; if it's unavailable the meeting fallback in §7.3 takes
  over and votes skip)

### 9.2 Test plan

A dedicated test (per review note #24) will run a full match with
the LLM **forcibly disabled** (returns errors to every call). The
bot must:

- Play every phase without crashing.
- Cast a vote in every meeting (even if always skip).
- Have at least one non-no-op action per 10-tick window during
  gameplay. (Passes the cogames validation gate.)
- Complete at least one task as a crewmate in a representative
  match.

If we can't hit those bars on defaults, the defaults are wrong — we
fix them before shipping.

### 9.3 Validation gate

Dry-run (`cogames upload --dry-run`) is expected to pass *without*
`--skip-validation`. The default directive must emit a non-no-op
action within the first 10 ticks. Since the LLM rarely comes back
within 10 ticks of game start, this means the default directive is
what passes the gate, not the LLM.

---

## 10. Concurrency model: in-Nim LLM worker

### 10.1 Decision

After verifying both in-cogames paths work, the LLM runs **in a Nim
worker thread within the same process as the inner loop**. No Python
sidecar. Justification:

1. `bitworld/src/bitworld/ais/{claude,openai,gemini,xai}.nim` already
   exist as ~60 LOC HTTP + JSON clients using `curly` + `jsony`.
   We adapt these.
2. `bitworld/among_them/players/italkalot.nim` is existence proof of
   a Nim Among Them bot doing live LLM calls.
3. The rest of the bot is Nim. Two languages cost more than one.
4. The cogames bundle is already "Nim compiled into shared lib + thin
   Python wrapper" for guided_bot. No need to add a second Python
   subprocess lifecycle.
5. API keys flow in via `--secret-env`
   (`metta/packages/cogames/POLICY_SECRETS.md`). The Nim process
   reads `ANTHROPIC_API_KEY` (or provider-appropriate var) from its
   env. This is the same path a Python sidecar would use.

**Python sidecar remains a viable fallback** if the threading or the
libcurl dependency turns painful. Preserved as §10.4 below.

### 10.2 Threads

Each active bot has a main-thread handle plus its own guidance worker
thread:

- **Main thread.** The cogames policy entry point. Runs the inner
  loop (perceive/update/decide/act) and owns the belief + mode
  scratch + action-layer state.
- **Per-bot guidance worker thread.** Blocks on that bot's
  incoming-snapshot channel, calls the LLM synchronously via `curly`,
  parses and validates the response, and pushes a directive onto that
  bot's outgoing channel. During meetings, also pushes meeting
  actions.

The worker receives a heap-stable `GuidanceRuntime` pointer owned by
`GuidanceState`, not a pointer to `Bot` or `GuidanceState`; policy bot
arrays can resize, but the runtime pointer stays stable until
`stopGuidance`.

### 10.3 Channels

Nim's `system.Channel[T]` or a minimal equivalent, owned per
`GuidanceState`:

- `snapshotChan: Channel[Snapshot]` — this bot's main loop → this
  bot's worker. Bounded size 1 (newest wins); main drops old entries
  rather than blocking.
- `directiveChan: Channel[Directive]` — this bot's worker → this
  bot's main loop. Main non-blocking reads at the start of the
  update-belief stage; takes the latest, discards older.
- `meetingActionChan: Channel[MeetingAction]` — this bot's worker →
  this bot's main loop. FIFO; main consumes one per tick while in
  meeting mode.
- `traceEventChan: Channel[string]` — this bot's worker → this bot's
  trace writer. Carries pre-serialized JSONL events so the worker
  never touches the main thread's trace ref object.

No guidance channel or worker thread is module-global. The worker is
never on the main thread's critical path. If the worker is busy (LLM
in flight), the main thread continues unimpeded.

### 10.4 Python sidecar alternative (not chosen)

Kept as a design alternative in case the in-Nim path hits a snag we
haven't anticipated:

- Nim core spawns a Python subprocess at policy init; communicates
  via stdin/stdout JSONL (or a Unix socket).
- Python process holds the LLM client, manages prompts, returns
  directives.
- `POLICY_SECRETS.md` guarantees the tournament runner can
  `Popen(env=...)` further subprocesses (that's literally how the
  policy itself is launched).
- Adds: Python deps bundling, subprocess lifecycle, IPC framing,
  two-process debugging.
- Removes: libcurl dependency in Nim; prompt iteration happens in a
  language the team is more productive in.

We revisit if the in-Nim path turns out to cost more than it saves.

---

## 11. Trace schema

Guided_bot owns its trace schema. Earlier drafts compared it to the
deprecated local modulabot trace format, but current work should use
`trace.nim` and this section as the source of truth. Trace output is a
session directory with JSONL streams plus a manifest. Designed for
post-match replay, offline analysis, and eventually for an LLM-driven
harness that proposes refactors to mode handlers.

### 11.1 Files per round

| File | Content |
|---|---|
| `manifest.json` | Round metadata: seed, match id, role, tournament config, tuning snapshot, bot version, schema version, start/end ticks, outcome. |
| `events.jsonl` | Game events the bot observed (see §11.2). |
| `decisions.jsonl` | Per-decision log (see §11.3). Roughly per-frame but may skip frames where no decision was made (interstitials). |
| `modes.jsonl` | Mode transitions (entered, exited, reason). |
| `guidance.jsonl` | Outer-loop log: snapshots sent, LLM responses, validation results, published directives (see §11.4). |
| `reflexes.jsonl` | Reflex interrupt firings. |
| `snapshots.jsonl` | Periodic full belief-state snapshots (every N ticks and on major events). |
| `frames.bin` (optional) | Raw unpacked frames for replay. Opt-in via CLI flag; default on during local runs, off in submission. |

The manifest is written with `"closed": false` on `openTrace` and
rewritten with `"closed": true` (plus `end_tick`, `outcome`, `role`)
when `closeTrace` runs. In the FFI path, `guidedbot_destroy_policy`
iterates all bots and calls `destroyBot`, which calls `closeTrace`.
The Python `AmongThemPolicy.close()` method (or its `__del__`
fallback) invokes the FFI export. Scripts should call
`policy.close()` at end of run; the `__del__` finalizer is a
best-effort safety net only.

### 11.2 `events.jsonl` event kinds (starter set)

```text
{ "t": tick, "kind": "body_seen",        "body_id": int, "position": [x,y],
  "room": str, "is_new": bool, "witnesses": [color, ...] }
{ "t": tick, "kind": "body_reported",    "reporter": color }
{ "t": tick, "kind": "kill_witnessed",   "killer": color, "victim": color,
  "position": [x,y] }
{ "t": tick, "kind": "kill_committed",   "victim": color, "position": [x,y] }
{ "t": tick, "kind": "kill_cooldown_ready" }
{ "t": tick, "kind": "task_started",     "task_index": int,
  "station_name": str, "selection_tier": "icon" | "checkout" | "geometry" }
{ "t": tick, "kind": "task_completed",   "task_index": int,
  "station_name": str, "hold_duration_ticks": int,
  "confirm_duration_ticks": int }
{ "t": tick, "kind": "task_abandoned",   "task_index": int,
  "station_name": str,
  "reason": "confirm_timeout" | "mode_switch" | "target_invalid",
  "phase_at_abandon": "hold" | "confirm", "hold_ticks_elapsed": int }
{ "t": tick, "kind": "report_attempted", "body_x": int, "body_y": int,
  "self_x": int, "self_y": int }
{ "t": tick, "kind": "report_gave_up",
  "reason": "body_gone" | "approach_timeout" | "in_range_timeout",
  "ticks_in_mode": int, "reached_range": bool }
{ "t": tick, "kind": "meeting_started",  "reason": "report" | "button" }
{ "t": tick, "kind": "meeting_ended",    "ejected": color | "skip" | null,
  "vote_counts": {color: int} }
{ "t": tick, "kind": "chat_observed",    "speaker": color | null, "text": str }
{ "t": tick, "kind": "role_revealed",    "role": str,
  "teammate_colors": [color, ...] }
{ "t": tick, "kind": "self_ejected" }
{ "t": tick, "kind": "self_became_ghost" }
{ "t": tick, "kind": "game_over",        "outcome": "crew_wins" | "imps_win" }
```

Every event is uniquely attributable back to the frame that produced
it (`t` = game tick).

### 11.3 `decisions.jsonl` shape

One record per decision (typically per frame during gameplay):

```text
{
  "t": tick,
  "mode": str,
  "directive_source": "llm" | "default" | "reflex",
  "directive_issued_at": tick,
  "params": {...},
  "branch_id": str,           // stable ID for the branch taken in decide()
  "intent": { "steer_to": [x,y]|null, "press_a": bool, ... },
  "reason": str               // one-line human-readable
}
```

(A reflex firing this tick shows up as `directive_source: "reflex"`
with the new mode already active — per §5.8, reflexes switch mode
rather than overriding this tick's action. The corresponding
`reflexes.jsonl` entry and `modes.jsonl` `mode_entered` entry give
the full provenance.)

Branch IDs are named strings the mode handlers emit at each
decision point. Auto-generated catalogue per build; drift detection in
CI.

### 11.4 `guidance.jsonl` shape

```text
{ "t": tick, "kind": "snapshot_sent",
  "snapshot_id": str, "snapshot": {...},   // the JSON sent to LLM
  "trigger": "periodic" | "wake_up:<reason>" }
{ "t": tick, "kind": "llm_response",
  "snapshot_id": str,
  "latency_ms": int, "prompt_tokens": int, "response_tokens": int,
  "raw_response": str,        // full LLM output
  "parsed": {...} | null,
  "validation": "ok" | "schema_error" | "illegal_for_role" | ... }
{ "t": tick, "kind": "directive_published",
  "snapshot_id": str, "mode": str, "params": {...},
  "ttl_ticks": int }
{ "t": tick, "kind": "directive_activated",
  "mode": str, "source": "llm" | "default" | "reflex" }
{ "t": tick, "kind": "directive_expired",
  "mode": str, "reason": "ttl" | "illegal" | "mode_switch" | "reflex" }
{ "t": tick, "kind": "meeting_action_received",
  "action": {...} }
{ "t": tick, "kind": "llm_call_failed",
  "reason": "http_error" | "timeout" | "rate_limit" | ...,
  "detail": str }
```

Every LLM call carries a `snapshot_id` so inputs and outputs can be
paired deterministically.

### 11.5 `modes.jsonl`

```text
{ "t": tick, "kind": "mode_entered", "mode": str,
  "params": {...}, "from_mode": str | null,
  "reason": "llm_directive" | "default" | "reflex:<name>"
          | "ghost_override" | "meeting_trigger" }
{ "t": tick, "kind": "mode_exited", "mode": str,
  "duration_ticks": int }
```

Reading `modes.jsonl` alone gives a mode timeline for the whole
match.

### 11.6 `reflexes.jsonl`

```text
{ "t": tick, "kind": "reflex_fired",
  "name": str,                        // stable reflex ID
  "from_mode": str,                   // mode that owned the reflex
  "to_mode": str,                     // mode that was switched to
  "to_params": {...},                 // params computed by target_params_fn
  "trigger": {...} }                  // the observed condition (e.g. body position)
{ "t": tick, "kind": "reflex_suppressed",
  "name": str,
  "reason": "cooldown" | "ghost_override" | "mode_illegal" }
```

One row per firing and one per suppression (so we can see reflexes
that *would* have fired but were gated by the anti-thrash cooldown
or by the ghost override).

### 11.7 Schema versioning

The manifest carries a `trace_schema_version` integer. Every change
bumps it; offline tooling keys off the version. No backward-compat
adapters in v0 — we upgrade tools when we change the schema.

### 11.8 Why this shape

- **Decision branches + mode transitions + events + LLM calls +
  reflex firings** are captured separately because they're
  independently useful.
- **Every decision is triangulable to (mode, directive, params,
  branch).** We can ask "why did the bot do X" and get a concrete
  answer.
- **Every directive is triangulable to a prompt/response pair** via
  `snapshot_id`.
- **Every reflex-driven mode switch is explicitly logged** with its
  trigger, so we can spot over-aggressive or false-positive reflex
  conditions.
- Post-match we can build tables like "per mode, win rate", "per
  branch, firing frequency", "per LLM response, latency distribution",
  "per reflex, firing rate and outcome attribution" without
  re-deriving them from raw game data.

---

## 12. Open questions & pushback

### 12.1 Resolved this round

| Question | Resolution |
|---|---|
| LLM lives in sidecar vs. in-process | **In-Nim worker thread** (§10). Sidecar is fallback. |
| LLM is part of submission or optional | **Part of submission.** Secrets via `--secret-env`. |
| What the LLM sees | **JSON dump of curated belief subset** (§8.3). Token budget deferred. |
| Mode scratch state reset semantics | **Reset on mode switch, preserved across directive changes within mode** (§5.6). |
| Action layer owns navigation | **Yes.** Modes emit `steer_to`; action layer does waypoint routing and tactical steering (§4.4, §6). |
| Ghost behavior | **Ghosts use `task_completing`.** No separate `ghost_observing` mode (§5.7). |
| Imposter default directive | **`hunting`** with no specific target, opportunistic, cover via pretending (§9.1). |
| Meeting mode | **LLM in direct control** via action queue, not a single plan (§7). |
| Reflex interrupts | **Reflex = forced mode switch**, edge-triggered, per-mode declaration, evaluated in update-belief stage so target mode runs same tick. Anti-thrash cooldown. Starter list of 4 (§5.8). |
| Mode param format | **Enum + structured params per mode schema** (§5.3). Examples drafted. |
| Conversation history | **Stateful in meetings, stateless in gameplay.** Not cost-optimizing at this stage (§8.5). |
| Trace schema | **Drafted in §11.** Guided_bot-owned schema with guidance, modes, and reflexes streams. |

### 12.2 Pushback kept from v0.1

**Latency mismatch.** Inner 24 Hz, outer ≤2 Hz is a ~20-50× ratio.
Reflex interrupts (§5.8) and triggered snapshots (§8.2) mitigate
this but don't eliminate it. Any mode that needs sub-second
strategic reactivity needs a reflex baked in. Modes without
reflexes will exhibit ~1-5 s of lag to critical events. Accept
this; measure it.

**Legacy bot behavior is not a target.** We implement
`task_completing` as guided_bot-owned behavior, informed by the
known-problem list in `how_to_make_a_bot.md` (icon-area clearing,
radar-vs-mandatory separation, hold-A discipline). The deprecated
local modulabot is not a current reference unless James explicitly
asks for a comparison. One of the reasons for this architecture is to
make it easier to iterate on individual modes without touching
perception.

### 12.3 Meeting mode: multi-call risks and mitigations

The meeting-as-live-LLM-control model introduces real risks that
don't exist in the single-plan version:

- **Self-contradiction across turns.** "Said sus red, voted blue"
  scenarios. Addressed by per-meeting conversation history (§7.3).
  The LLM sees what it's already said and voted.
- **Vote flipping.** A late LLM turn could re-emit `vote` after
  `confirm_vote`. Addressed by soft-lock (§7.5): post-confirmation
  vote/unvote responses are ignored and traced as no-ops.
- **Stuck waiting.** LLM returns `wait` but no trigger ever fires.
  Addressed by the safety-net fallback (§7.7): at <100 ticks
  remaining we force a vote.

Per review note #3, we're not cost-optimizing yet — multiple calls
per meeting are fine.

### 12.4 Reflex-as-mode-switch: the `pretending → hunting` case

See `HUNTING_DESIGN.md` §10.1 for the full discussion. Summary: the
mode-switch model makes this cleaner than v0.2's inline kill-strike
(the kill decision runs in `hunting.decide()` with full context), but
the reflex still triggers without LLM approval and deserves monitoring.

### 12.5 Reflex-list growth is still constrained

Even though reflexes now switch modes instead of baking logic
inline, they're still a shadow policy: the LLM isn't in the
decision. We keep the list at 4 and grow it only with measurement.
A reflex that fires more than a couple of times per match without
improving outcomes is a bug, not a feature.

### 12.6 `summarize_for_llm` per mode (future)

§5.6 notes that mode scratch state isn't exposed to the LLM. If it
turns out a mode's internal reasoning is useful context for the LLM,
we add an optional `summarize_for_llm(scratch) -> json` hook on the
mode interface and include its output in the snapshot. Not in v0.
See `HUNTING_DESIGN.md` §14 for the hunting-specific case.

### 12.7 Non-meeting chat?

The game only accepts chat during voting. Fine. But if a future
season opens chat in gameplay, we'll need to decide whether chat
during gameplay is mode-driven or always LLM-driven. Deferred —
flagging so we don't forget.

### 12.8 Value question (carried over)

Is the LLM actually going to beat a well-tuned scripted policy?
Unresolved. The architecture supports measurement: the trace
(§11) contains every piece of data we need to compare runs with the
LLM enabled vs. runs on defaults only. After shipping, compare
those numbers.

Specifically three numbers per agent:

- Leaderboard score with LLM enabled.
- Leaderboard score with LLM forcibly disabled (defaults only).
- A current external/scripted baseline score, if one is available.

If `LLM ≈ defaults`, the LLM isn't pulling weight — we either fix
the prompting or remove the LLM cost.

---

## 13. Decisions made this round (pre-code)

Per the v0.1 checklist, decisions resolved or explicitly deferred.

| Item | Decision |
|---|---|
| Starting mode enum | §5.4: `idle`, `task_completing`, `fear`, `investigating`, `reporting`, `pretending`, `hunting`, `fleeing`, `alibi_building`, `sabotage_watching`, `meeting`. Ghost merges into `task_completing`. |
| Mode-params schemas | First pass in §5.3. Expect iteration. |
| Belief-state layout | §3. Start simple: self, perception, memory, tasks, social, directive, flags. Extend when a mode needs something. |
| Snapshot format | §8.3. JSON dump of curated subset. Not token-bounded yet. |
| Reflex interrupts | §5.8. Four to start. |
| Fallback defaults | §9.1 per role. §9.2 test plan mandatory. |
| Trace schema | §11 drafted. Guided_bot-owned schema. |
| Concurrency / LLM placement | §10: in-Nim worker thread. Python sidecar preserved as fallback. |
| Mode scratch state lifecycle | §5.6: reset on mode switch, preserved within mode across directive changes. |
| Action layer owns navigation | §4.4 + §6. Modes emit `steer_to`; action layer owns waypoint routing, edge progress, vent traversal, and task-hold discipline. |

### Items explicitly deferred

- Prompt engineering (system prompt, few-shot, response schema).
- LLM provider choice (Anthropic / OpenAI / ...). Trivial to swap;
  `claude.nim` is the starting point because we're on Claude day-to-day.
- Exact TTL values, periodic cadence, per-match call cap. Tune
  empirically.
- Token budgeting for snapshots.
- Frame-dump retention policy.
- Parity harness (we don't have a parity target here; compare against
  current external/scripted baselines when available).

---

## 14. Decisions log

| # | Topic | Resolution | Section |
|---|---|---|---|
| D1 | LLM in submission | First-class, via `--secret-env`. | §1 goal 5, §10 |
| D2 | LLM host process | In-Nim worker thread. | §10 |
| D3 | Belief state writable by | Inner-loop update stage only; directive slot writable by guidance thread. | §3 invariants |
| D4 | Mode scratch lifecycle | Reset on mode switch, persist within mode. | §5.6 |
| D5 | Action-layer owns navigation | Modes emit `steer_to`, action layer owns waypoint routing + tactical steering + discipline. | §4.4, §6 |
| D6 | Ghost behavior | Forced to `task_completing`; action layer uses straight-line steering for ghosts. | §5.7 |
| D7 | Meeting mode | LLM direct control via action queue; safety-net fallback vote skip. | §7 |
| D8 | LLM snapshot format | JSON dump of curated belief subset. | §8.3 |
| D9 | Validation | Guidance validates once; inner loop re-validates every tick. | §8.4 |
| D10 | Reflex pattern | **Reflex = forced mode switch**, edge-triggered, evaluated in update-belief, anti-thrash cooldown, starter list of 4. | §5.8 |
| D11 | Imposter default directive | `hunting` with opportunistic + cover. See `HUNTING_DESIGN.md`. | §9.1 |
| D12 | Task-completing mode | Guided_bot-owned implementation; legacy bot comparisons are historical only. | §12.2 |
| D13 | Trace schema | Guided_bot-owned schema with guidance, modes, and reflexes streams. | §11 |
| D14 | Fallback-only playability test | Required before first submission. | §9.2 |
| D15 | Meeting LLM context | Full speaker-attributed chat transcript + meeting history + vote tally + per-player evidence + self-action history via conversation history. | §7.2 |
| D16 | LLM conversation history | Stateful across a meeting's calls; stateless across gameplay calls. | §7.3, §8.5 |
| D17 | Vote soft-lock | `confirm_vote` is irrevocable; subsequent re-votes are ignored within the same meeting. | §7.5 |
| D18 | Reflex evaluation stage | Update-belief, not decide, so target mode's `decide` runs same tick. | §4.2, §5.8 |
| D19 | Phase 1 sub-plan | Port perception in 6 sub-phases (1.0 foundation → 1.6 voting). Each sub-phase is its own commit with tests. | §15 |
| D20 | Phase 1.1 asset baking | Door #1 of the §15 choice: deterministic Nim bake tool (`tools/bake_assets.nim`) emits raw `.bin` blobs into `perception/baked/`; runtime consumes them via `staticRead`. Bake tool reads the upstream `~/coding/bitworld` checkout *directly* (using the same `bitworld/aseprite` parser the live server uses) so modulabot's data dir is no longer in the trust chain. No PNG decoder dependency in the runtime, no runtime file I/O, no nimby in the runtime build. `BakeSchemaVersion` constant pins compile-time vs. baked-dir agreement. | §15, README "Regenerating baked assets" |
| D21 | Phase 1.2 kernel sharing | Followed §15's guidance: `perception/localize.nim` imports `among_them/common/perception_kernels/{sprite_match,localize}.nim` via `from "../../..." as kX import nil` (relative-path import, no leaked identifiers, qualified-only access). Avoids both code duplication and FFI/shared-library indirection. The kernels are pure Nim and covered by guided_bot fixture tests; drift fails our compile or fixture-pinned camera tests. Patch index is built in Nim; scalar one-shot, cached at module level. | §15, `perception/localize.nim` header |
| D22 | Phase 1.3 actor scan pattern | `perception/actors.nim` imports `kSpriteMatch.mb_match_actor_sprite_all` and `kSpriteMatch.mb_actor_color_index_all` via the same `from "../../..." as kSpriteMatch import nil` pattern. Guided_bot owns orchestration ordering (role → self-colour → bodies → ghosts → crewmates). Dedup is greedy raster-order within Chebyshev radius. Actor scan runs in the bot pipeline *after* localize (needs camera for future world-coord conversion) and *before* decision/action. Detected sprites are stamped into the ignore mask for phase 1.4's task-icon scanner. New `ActorScanner` struct holds reusable match/colour buffers to avoid per-frame allocation. | §15, `perception/actors.nim` header |
| D23 | Phase 1.4 task/radar scan | `perception/tasks.nim` wraps `mb_scan_task_icons` from `among_them/common/perception_kernels/actors.nim` via `from "../../..." as kActors import nil`. Task-icon scan only runs when `localized` is true and not alive imposter. Radar-dot scan is pure Nim (no kernel) — collects palette-8 (yellow) pixels in the 2-pixel periphery ring with Chebyshev-1 greedy dedup. Both produce raw perception output (`IconMatch`, `RadarDotMatch`); the higher-level task-state machine (icon→task assignment, checkout latching, icon-miss pruning) is deferred to phase 2. Task-coord cache built lazily from `referenceData.map.tasks`. | §15, `perception/tasks.nim` header |
| D24 | Phase 1.5 OCR pattern | `perception/ocr.nim` wraps `mb_best_glyph` and `mb_text_matches` from `among_them/common/perception_kernels/ocr.nim`. Font data repacked into flat arrays at module init (`PackedFont`). `findText` is pure Nim (full-frame sweep, ~12 ms). `classifyInterstitial` tries banner strings in longest-first order to avoid partial matches. | §15, `perception/ocr.nim` header |
| D25 | Phase 1.6 voting parse | `perception/voting.nim` owns guided_bot's voting parse. Strict validator: SKIP text must match, and each slot's colour must equal its index. Reuses scalar `matchesCrewmate` / `crewmateColorAt` for slot and speaker-pip parsing (not the vectorised kernel — slots are at known positions). Chat OCR uses `readRun` from `ocr.nim`. Voting parse gates `PhaseVoting` on the belief; if parse fails, falls back to banner OCR for other interstitial kinds. `VotingParse.chatLines` merged into `Belief.social.currentMeetingChat`. | §15, `perception/voting.nim` header |

Further decisions get appended here as they're made.

| D26 | Phase 3 LLM client | Adapted bitworld's `claude.nim`. Uses `curly` + `jsony` via nimby. Fresh `CurlPool` per call to avoid GC-safety issues with globals; overhead negligible at <1 Hz. | `llm.nim` |
| D27 | Phase 3 threading | `system.Channel[T]` (Nim 2.2.4), owned per `GuidanceState` through a heap-stable `GuidanceRuntime` pointer. Worker thread holds meeting conversation history as thread-local state. Main thread: non-blocking `tryRecv`. No module-global guidance channels or worker handles. | `guidance.nim` |
| D28 | Phase 3 snapshot rendering | `std/json` (not jsony) for structured, readable output. Room name lookups via `geometry.roomNameAt`. Screen→world via `visibleCrewmateWorldX/Y`. | `snapshot.nim` |
| D29 | Phase 3 wake-flag lifecycle | Flags raised during update-belief, consumed (snapshot submitted) and cleared at end of `decideNextMask`. External code (tests) cannot observe flags after `stepUnpackedFrame`. | `bot.nim` |
| D30 | Phase 3 LLM model | `claude-sonnet-4-20250514` — fast enough for ~1-5 Hz call rate, smart enough for strategic directives. Max 1024 response tokens. | `llm.nim` |
| D31 | Phase 3 meeting action queue | Actions pumped from `meetingActionChan` into `ModeScratch.meetPendingActions` in the bot pipeline, popped one-per-tick by meeting mode's `decide()`. | `bot.nim`, `modes/meeting.nim` |

---

## 15. Phase 1 sub-plan (perception port)

Phase 1 was originally scoped as a single commit for localization,
sprite matching, task-icon scanning, OCR, and voting parse. Doing it in
one commit would be rushed and poorly tested. Breaking it into
sub-phases lets each one land fully tested and documented.

Each sub-phase is a self-contained commit that extends the real
`Percept` and `PerceptionState` fields, wires new perception code
through the pipeline, and adds fixture-based tests.

| Sub | Scope | Deps | Status |
|---|---|---|---|
| **1.0** | Frame unpacking, interstitial detection (black-pixel %), dynamic-pixel ignore-mask scaffolding, pipeline wire-in (`perceive` → `updateBelief` → `PerceptionState`). Fixture tests using real frames. | none | ✅ shipped |
| **1.1** | Perception data loading — palette, player colours, sprite atlas, map/walk/wall layers, ASCII font, map.json. Baked into raw `.bin` blobs by `tools/bake_assets.nim` (reads `~/coding/bitworld` directly via the upstream `bitworld/aseprite` parser, single source of truth) and embedded into the Nim binary via `staticRead`. No PNG decoder, no nimby in the runtime. Compile-time shape asserts catch stale baked dirs. | 1.0 | ✅ shipped |
| **1.2** | Camera localization — guided_bot orchestration in `perception/{geometry,localize}.nim`. Reuses `mb_score_camera`, `mb_hash_frame_patches`, `mb_vote_camera_candidates` from `among_them/common/perception_kernels/` via `from "../../common/perception_kernels/X" as kX import nil` — keeps the kernel as the single source of truth, no FFI / shared-library indirection. Patch-index built lazily in Nim on first non-interstitial frame. Pipeline calls `updateLocation` on gameplay frames and `reseedCameraAtHome` on interstitials. Smoke benchmark guards against catastrophic regressions. | 1.1 | ✅ shipped |
| **1.3** | Actor / body / ghost scanning — wraps `mb_match_actor_sprite_all` and `mb_actor_color_index_all` from `among_them/common/perception_kernels/sprite_match.nim`. Guided_bot owns the scan orchestration (role detection → self-colour → bodies → ghosts → crewmates). Stamps actor sprite exclusions into the ignore mask. Merges results into `SelfState.role/colorIndex` and `PerceptionState.visibleCrewmates/Bodies/Ghosts`. ~2 ms per gameplay frame. | 1.2 | ✅ shipped |
| **1.4** | Task-icon scanning — wraps `mb_scan_task_icons` from `among_them/common/perception_kernels/actors.nim`. For each task station, probes a 3-bob × 7×7 neighbourhood around the expected icon screen position. Radar-dot scanning — pure Nim scan for palette-8 (yellow) pixels in the 2-pixel screen-edge periphery ring, deduped with Chebyshev-1 grouping. Stamps task-icon exclusions into the ignore mask. Merges results into `PerceptionState.visibleTaskIcons/radarDots`. ~0.1 ms per gameplay frame. | 1.2 | ✅ shipped |
| **1.5** | ASCII OCR — wraps `mb_best_glyph` and `mb_text_matches` from `among_them/common/perception_kernels/ocr.nim`. Adds `findText` (pure-Nim full-frame sweep, ~12 ms) for interstitial banner detection. `classifyInterstitial` searches for `"CREW WIN"`, `"IMPS WIN"`, `"CREWMATE"`, `"IMPS"` banners to refine `InterstitialKind`. Provides `readRun` and `readLineStrict` for chat-line OCR. Font data repacked into flat kernel format at module init. | 1.1 | ✅ shipped |
| **1.6** | Voting-screen parse — `parseVotingScreen` iterates player counts 16→1, validating each via strict slot checks (per-slot colour must match slot index). Parses cursor position, self-marker, vote dots (8-wide grid per target), SKIP text + SKIP vote dots. Chat OCR: `readRun` at each non-empty text row, speaker pips attributed via nearest crewmate sprite match above the text line. Results in `VotingParse` with slots, cursor, choices, chatLines. Voting parse gates `PhaseVoting` on the belief; failed parse falls back to banner OCR classification. | 1.5 | ✅ shipped |

### Sharing perception kernels via `among_them/common/`

`among_them/common/perception_kernels/*.nim` is pure Nim,
self-contained (no bitworld imports), stateless kernels with
active tests in guided_bot. Guided_bot consumes them directly:

- **guided_bot** (phase 1.2+) imports them directly via
  `from "../../common/perception_kernels/X" as kX import nil` — no
  FFI roundtrip, qualified-only access to keep namespaces clean.
- **modulabot** is a deprecated historical consumer only. Do not update
  its FFI/ABI or tests unless James explicitly asks for modulabot work.

Rationale:

- No code duplication in the active guided_bot pipeline.
- Guided_bot does not reach into the deprecated local modulabot tree;
  shared kernels live only under `among_them/common/`.
- A change to one of the kernels is a single diff protected by
  guided_bot tests.

Risk: if guided_bot depends on a specific kernel shape and the kernel
signature changes, guided_bot breaks silently until its tests catch it.
The phase-1 test suite in guided_bot specifically exercises every kernel
guided_bot consumes, so drift shows up immediately.

Phase 1.0 did not yet import any kernel; phase 1.2 adds the
dependency on `sprite_match.nim` + `localize.nim`. Phase 1.3 adds
the dependency on `sprite_match.nim`'s `mb_match_actor_sprite_all`
and `mb_actor_color_index_all` (imported via `perception/actors.nim`).
Phase 1.4 adds the dependency on `actors.nim`'s `mb_scan_task_icons`
(imported via `perception/tasks.nim`). Phase 1.5 adds the dependency
on `ocr.nim`'s `mb_best_glyph` and `mb_text_matches` (imported via
`perception/ocr.nim`). All four kernel files are now consumed.

See [`among_them/common/README.md`](../common/README.md) for the
shared-directory convention.
