# guided_bot — Design Report (v0.3, abstract)

> **Status:** design-only. No code written. This is v0.3, incorporating
> the second review pass (reflex-as-mode-switch, meeting LLM context,
> conversation history).
>
> **Audience:** future self, collaborators, and the LLM harness that will
> eventually consume this file. Implementation details (Nim syntax, file
> layouts, FFI shape, buffer sizes, exact trace struct definitions) are
> deferred. This doc describes the *shape* of the agent and the
> decisions already made; it is not a code outline.
>
> **Related reading** — load-bearing context:
>
> - `among_them/modulabot/README.md` and
>   `bitworld/among_them/players/modulabot/DESIGN.md` — the scripted
>   baseline whose perception layer we reuse.
> - `bitworld/among_them/players/how_to_make_a_bot.md` — the hard-won
>   lessons about localization, task states, radar, momentum, voting.
>   Still all applicable.
> - `bitworld/among_them/players/modulabot/TRACING.md` — the trace
>   schema we extend.
> - `bitworld/src/bitworld/ais/{claude,openai}.nim` — existing Nim HTTP
>   LLM clients (`curly` + `jsony`, ~60 LOC each). We adapt these.
> - `bitworld/among_them/players/italkalot.nim` — existence proof of a
>   Nim-native Among Them bot making live LLM calls.
> - `metta/packages/cogames/POLICY_SECRETS.md` — how API keys reach the
>   policy subprocess in the tournament (env-var injection via
>   `--secret-env`). The LLM is a first-class submission citizen.

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
   and validation gate all follow the modulabot pattern. LLM keys flow
   in via `--secret-env` (cogames' documented mechanism).

### Non-goals (v0)

- **No new perception.** Reuse modulabot's perception modules
  (localization, sprite matching, task icons, voting parse, ASCII OCR).
- **No training.** No neural policies, no RL.
- **No games other than Among Them.**
- **No parity bar with modulabot.** We expect different behavior.
  modulabot's scripted crewmate policy is a reference, **not a
  verbatim starting point** — it has known jank; we take inspiration
  but rebuild per-mode.
- **No LLM-per-tick.** Not even in meetings. The LLM is event-driven
  during meetings, not polled at 24 Hz.

---

## 2. Architecture at a glance

```
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
    belief store                              action layer (A*, motion,
    per-mode scratch                          jiggle, last-mask, task-hold)
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
- **Action-layer state** — the motion model, current A\* path and its
  goal, jiggle counters, last-emitted mask, task-hold discipline.
  Owned by the action module, persisted across ticks.

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
   applicable. Everything modulabot's perception layer already
   produces.
3. **Memory.** Per-player summary (last seen tick/place, times near
   bodies, times witnessing kills, alibi evidence, vote history,
   ejected flag); per-body event; per-meeting event; sightings log.
   Pattern from `modulabot/memory.nim`.
4. **Tasks.** Per-task state (`not_doing` / `maybe` / `mandatory` /
   `completed`), last icon sighting, assumed-assigned set. For
   ghosts: the task layer is the same; ghosts complete their own
   tasks (see §5.7).
5. **Social.** Recent chat lines (speaker-attributed per modulabot's
   voting-screen OCR), accusations heard, votes cast, votes received,
   most-recent meeting transcript.
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
- **Action-layer state.** Current A\* path, motion model, jiggle
  counters. Lives in the action module.

The belief is passed by const reference to modes. Modes cannot
invalidate any other mode's view of the world.

---

## 4. The inner loop

The inner loop is a pipeline with four stages.

```
frame ──► perceive ──► update belief ──► decide ──► act
           (read)         (write)         (read)    (write)
```

### 4.1 Perceive

- Input: raw frame, previous belief.
- Output: a percept — the delta of what this frame says about the
  world (camera lock, visible actors/bodies/icons/radar dots,
  interstitial/voting state, new chat lines, role reveal, game-over).
- Reuses modulabot's perception layer verbatim. The percept is a
  small typed struct; merging it into belief is the next stage's job.

### 4.2 Update belief

- Input: previous belief, current percept, latest directive from the
  guidance loop's slot (atomic read).
- Output: new belief.
- Responsibilities:
  - Merge percept into perception fields.
  - Maintain memory (sightings log, per-player summaries, body /
    meeting events). Round-reset on role-reveal interstitial.
  - Task-state transitions (`mandatory ↔ completed` per modulabot's
    icon-area rules).
  - Update the directive slot (atomic swap in the latest LLM output
    if one is pending; expire the current directive if TTL elapsed,
    falling back to the per-role default).
  - **Evaluate reflexes for the active mode.** If any reflex fires,
    synthesize a new directive (new mode + params) and install it in
    the slot before decide runs. See §5.8. Raise
    `wake_up_reasons: ["reflex:<name>"]` so the guidance loop knows
    to snapshot.
  - Raise / clear other flags for the guidance loop (body seen, kill
    ready, new chat, meeting started).

### 4.3 Decide

- Input: belief (with current directive, already possibly reflex-
  overridden by §4.2).
- Output: action intent (§6).
- Responsibility: look up `belief.directive.mode` in the mode
  registry (§5.2), check `is_legal_for(belief)`, and call
  `decide(belief, mode_params, scratch)`. That's all it does. No
  strategy lives here — only routing.
- If the mode is illegal (e.g. LLM said `hunting` but we're a ghost),
  the decide stage falls back to the role-appropriate default
  directive for this tick and emits a trace event.
- **Reflexes are not evaluated here.** They live in §4.2 because a
  reflex needs to be able to install a new directive and have *that
  mode's* decide logic run on the same tick. See §5.8.

### 4.4 Act

- Input: action intent (§6).
- Output: button mask, optional chat payload.
- Owns all persistent tactical state:
  - Current A\* path + goal (for invalidation).
  - Motion model (velocity, previous position).
  - Jiggle/stuck counters.
  - Last emitted mask (edge detection, "only send on change").
  - Task-hold state (currently holding A for task completion?).
- Recomputes A\* only when `steer_to` changes or the current path is
  invalidated (per tick cost is therefore bounded; long paths are
  amortized).
- Translates the `discipline` hint into a movement policy:
  `normal` = momentum steering; `task_hold` = hold A only, no
  movement; `kill_strike` = direct line, press A on contact;
  `report` = direct line, press A in report range.

**Modes do not know about A\*, jiggle, or button edges.** The action
layer is the single place those live.

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

```
idle {
  # Stand somewhere, observe, respond to reflexes only.
  linger_at?: point        # specific spot to hold near
  near_group: bool         # prefer to be near ≥1 other player
}

task_completing {
  # Crewmate default and ghost default.
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
  # Imposter: look for a kill.
  preferred_target?: color_index
  max_witnesses: int          # refuse kill if > N non-imp others visible
  opportunistic: bool         # if no target, still take any isolated crew
  cover_mode: "pretending" | "idle"   # behavior while not closing
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
- **Reflex interrupts** (§5.8) overriding the active mode's output
  for a single tick, without actually switching mode.

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
- `hunting.scratch` — current stalking target, approach path index,
  last-seen target location.
- `pretending.scratch` — current fake target, loiter timer, last
  swap tick.

### 5.7 Ghosts

**Ghosts complete tasks.** A crewmate who is ghosted still has their
original task list and can still contribute to the crew win condition
by ticking them off. So:

- Ghost default directive = `task_completing { target:
  nearest_mandatory, abandon_on_nearby_body: false }`.
- `task_completing` mode's handler checks `belief.self.is_ghost` and
  passes a ghost-aware hint to the action layer:
  - Ghosts can move through walls → the action layer's A\* uses a
    different passability mask (or no mask at all — straight-line
    steering).
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

- Each mode declares a list of reflex rules:
  `(condition_fn, target_mode, target_params_fn)`.
- Reflex evaluation happens in the **update-belief stage** (§4.2),
  not in decide. This is important: reflex evaluation can install a
  new directive in the slot *before* decide reads it, so the target
  mode's `decide()` runs on the same tick as the triggering event.
  No one-tick bridging action is needed.
- When a reflex fires:
  1. The target mode's `target_params_fn(belief)` builds params from
     current belief (e.g. `reporting`'s `body_location` is set from
     the just-observed body).
  2. The old mode's `on_exit` runs; the new mode's `on_enter` runs;
     scratch state resets.
  3. A new directive is written to the slot with
     `source: "reflex"`, `ttl_ticks: <short>`, `reflex_name: <id>`.
  4. `wake_up_reasons: ["reflex:<name>"]` is raised so the guidance
     loop snapshots next cycle.
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

- A reflex cannot fire again within `N` ticks of its last firing,
  per-mode. (`N` ≈ a couple of seconds of ticks. Tuning knob.)

This means the LLM is allowed to overrule the reflex and ride the
same situation through without another reflex interruption, at
least for `N` ticks.

#### The initial reflex set

Short on purpose. Every reflex is a mini-policy-without-an-LLM;
they add up to a shadow policy if we aren't careful.

| Mode | Condition | Switch to | Reason |
|---|---|---|---|
| `task_completing` (crew, alive) | `body_newly_in_view` | `reporting { body_location: <body.position> }` | Let the dedicated reporting mode handle navigation + A press. Crewmate gets a fresh body → go report it, regardless of current task. |
| `hunting` | `body_newly_in_view` (and I didn't kill them) | `fleeing { away_from: <body.position>, min_distance: ..., duration_ticks: ... }` | Don't hang around a corpse we didn't create. |
| `pretending` | `lone_crew_in_kill_range AND kill_cooldown == 0 AND witnesses_visible == 0` | `hunting { preferred_target: <color>, max_witnesses: 0, opportunistic: false, cover_mode: pretending }` | Route a kill opportunity into the mode whose `decide` actually knows how to close and strike. |
| any mode | `voting_screen_appeared` | `meeting { want_to_speak_first: false }` | Meetings are an LLM-driven mode; switch immediately and let meeting's decide handle it. |

The `pretending → hunting` reflex is noticeably more aggressive than
the others — it performs a game-changing action (a kill, via the
hunting mode's logic) without LLM approval. Under the mode-switch
model this is cleaner than v0.2's "inline canned kill-strike"
because the actual kill decision happens in `hunting.decide()`,
which can reconsider (e.g. it might decide the target's moved out
of range by the time it runs). Still worth watching: if this reflex
fires and causes a bad kill that the LLM would've vetoed, we
reconsider.

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

- `steer_to: point | none` — destination. Action layer owns A\* and
  momentum steering to get there.
- `press_a: bool`
- `press_b: bool`
- `cursor: left | right | none` — meeting-screen cursor movement.
- `chat: string | none` — meeting mode only.
- `facing: direction | none` — rare; for cases where facing matters
  without movement.
- `discipline: normal | task_hold | kill_strike | report | no_op`
  — hint to the action layer.

The action layer translates this into a button mask. The mode never
touches a button bit directly.

---

## 7. Meeting mode — LLM in direct control

Meetings are special. They are:

- Long enough for multiple LLM calls (`voteTimerTicks = 1200` ≈ 50 s
  at 24 Hz; typical LLM latency 1-5 s → 10-50 round trips in the
  limit, realistically ≈ 5-15 with prompt size).
- Action-space-minimal (move cursor, press A, emit chat text).
- Language-heavy and high-stakes — precisely the LLM's advantage.

### 7.1 Design

When the `meeting` mode activates, **the inner loop hands the LLM a
direct action channel**. Each LLM turn produces one action:

```
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
  Produced by modulabot's voting-screen chat OCR + colour-pip
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
- **Throttled:** hard cap on LLM calls per match (e.g. 60) and per
  second (e.g. 1 per 500 ms). If we hit the cap, the loop stops
  calling and the inner loop rides the last directive (or the
  default, if TTL expires).

### 8.3 Snapshot format (for the LLM)

**Decision (per review note #14):** a JSON dump of a curated view of
the belief state. Structure, not prose. Initial shape:

```
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
      "<color>": { "last_seen_tick": int,
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
  `hunting { preferred_target: none, max_witnesses: 1,
             opportunistic: true, cover_mode: "pretending" }`
- **Ghost** →
  `task_completing { target: nearest_mandatory,
                      abandon_on_nearby_body: false }`
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
   Python wrapper" (modulabot pattern). No need to add a second
   Python subprocess lifecycle.
5. API keys flow in via `--secret-env`
   (`metta/packages/cogames/POLICY_SECRETS.md`). The Nim process
   reads `ANTHROPIC_API_KEY` (or provider-appropriate var) from its
   env. This is the same path a Python sidecar would use.

**Python sidecar remains a viable fallback** if the threading or the
libcurl dependency turns painful. Preserved as §10.4 below.

### 10.2 Threads

Two threads inside the Nim process:

- **Main thread.** The cogames policy entry point. Runs the inner
  loop (perceive/update/decide/act) and owns the belief + mode
  scratch + action-layer state.
- **Guidance worker thread.** Blocks on an incoming-snapshot
  channel, calls the LLM synchronously via `curly`, parses and
  validates the response, and pushes a directive onto the outgoing
  channel. During meetings, also pushes meeting actions.

### 10.3 Channels

Nim's `system.Channel[T]` or a minimal equivalent:

- `snapshotChan: Channel[Snapshot]` — main → worker. Bounded size 1
  (newest wins); main drops old entries rather than blocking.
- `directiveChan: Channel[Directive]` — worker → main. Main
  non-blocking reads at the start of the update-belief stage; takes
  the latest, discards older.
- `meetingActionChan: Channel[MeetingAction]` — worker → main.
  FIFO; main consumes one per tick while in meeting mode.

The worker is never on the main thread's critical path. If the
worker is busy (LLM in flight), the main thread continues unimpeded.

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

We extend the modulabot schema (see its `TRACING.md`). Trace output
is a session directory with one subdirectory per round, each
containing JSONL streams plus a manifest. Designed for post-match
replay, offline analysis, and eventually for an LLM-driven harness
that proposes refactors to mode handlers.

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

### 11.2 `events.jsonl` event kinds (starter set)

```
{ "t": tick, "kind": "body_seen",        "body_id": int, "position": [x,y],
  "room": str, "is_new": bool, "witnesses": [color, ...] }
{ "t": tick, "kind": "body_reported",    "reporter": color }
{ "t": tick, "kind": "kill_witnessed",   "killer": color, "victim": color,
  "position": [x,y] }
{ "t": tick, "kind": "kill_committed",   "victim": color, "position": [x,y] }
{ "t": tick, "kind": "kill_cooldown_ready" }
{ "t": tick, "kind": "task_started",     "task_index": int }
{ "t": tick, "kind": "task_completed",   "task_index": int }
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

```
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
decision point, following modulabot's `BRANCH_IDS.md` convention.
Auto-generated catalogue per build; drift detection in CI.

### 11.4 `guidance.jsonl` shape

```
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

```
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

```
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
| Action layer owns A\* and motion | **Yes.** Modes emit `steer_to`; action layer does pathing and momentum (§4.4, §6). |
| Ghost behavior | **Ghosts use `task_completing`.** No separate `ghost_observing` mode (§5.7). |
| Imposter default directive | **`hunting`** with no specific target, opportunistic, cover via pretending (§9.1). |
| Meeting mode | **LLM in direct control** via action queue, not a single plan (§7). |
| Reflex interrupts | **Reflex = forced mode switch**, edge-triggered, per-mode declaration, evaluated in update-belief stage so target mode runs same tick. Anti-thrash cooldown. Starter list of 4 (§5.8). |
| Mode param format | **Enum + structured params per mode schema** (§5.3). Examples drafted. |
| Conversation history | **Stateful in meetings, stateless in gameplay.** Not cost-optimizing at this stage (§8.5). |
| Trace schema | **Drafted in §11.** Extends modulabot schema with guidance, modes, and reflexes streams. |

### 12.2 Pushback kept from v0.1

**Latency mismatch.** Inner 24 Hz, outer ≤2 Hz is a ~20-50× ratio.
Reflex interrupts (§5.8) and triggered snapshots (§8.2) mitigate
this but don't eliminate it. Any mode that needs sub-second
strategic reactivity needs a reflex baked in. Modes without
reflexes will exhibit ~1-5 s of lag to critical events. Accept
this; measure it.

**Modulabot as reference, not ancestor.** Per review note #6, the
modulabot crewmate policy is known janky. We implement
`task_completing` fresh, informed by modulabot's code and by the
known-problem list in `how_to_make_a_bot.md` (icon-area clearing,
radar-vs-mandatory separation, hold-A discipline), but we do not
copy it verbatim. One of the reasons for this architecture is to
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

### 12.4 Reflex-as-mode-switch: cleaner, but the `pretending →
hunting` case still deserves watching

The v0.2 concern about the "aggressive kill-strike reflex" is
materially reduced by the mode-switch model: the kill decision now
runs inside `hunting.decide()`, which has access to the full
belief, full scratch, and the `is_legal_for` gate. That's a real
decision-making context, not a single-frame override.

That said, this reflex still triggers a kill without LLM approval,
and it's the one the LLM is most likely to want to veto (e.g.
during `alibi_building` where a kill blows the alibi). Watch it:
if `pretending → hunting` via reflex correlates with bad outcomes
more than direct LLM-issued `hunting`, we demote it (require LLM
approval, or gate it on an LLM-set `permit_opportunistic_kill`
field in `pretending.params`).

### 12.5 Reflex-list growth is still constrained

Even though reflexes now switch modes instead of baking logic
inline, they're still a shadow policy: the LLM isn't in the
decision. We keep the list at 4 and grow it only with measurement.
A reflex that fires more than a couple of times per match without
improving outcomes is a bug, not a feature.

### 12.6 `summarize_for_llm` per mode (future)

§5.6 notes that mode scratch state isn't exposed to the LLM. If it
turns out a mode's internal reasoning is useful context for the LLM
(e.g. `hunting`'s "I've been stalking red for 200 ticks"), we add an
optional `summarize_for_llm(scratch) -> json` hook on the mode
interface and include its output in the snapshot. Not in v0.

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
- Modulabot leaderboard score.

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
| Trace schema | §11 drafted. Extends modulabot schema. |
| Concurrency / LLM placement | §10: in-Nim worker thread. Python sidecar preserved as fallback. |
| Mode scratch state lifecycle | §5.6: reset on mode switch, preserved within mode across directive changes. |
| Action layer owns navigation | §4.4 + §6. Modes emit `steer_to`; action layer owns A\*, motion, jiggle, task-hold discipline. |

### Items explicitly deferred

- Prompt engineering (system prompt, few-shot, response schema).
- LLM provider choice (Anthropic / OpenAI / ...). Trivial to swap;
  `claude.nim` is the starting point because we're on Claude day-to-day.
- Exact TTL values, periodic cadence, per-match call cap. Tune
  empirically.
- Token budgeting for snapshots.
- Frame-dump retention policy.
- Parity harness (we don't have a parity target here; the baseline
  is modulabot on the leaderboard, not modulabot's mask stream).

---

## 14. Decisions log

| # | Topic | Resolution | Section |
|---|---|---|---|
| D1 | LLM in submission | First-class, via `--secret-env`. | §1 goal 5, §10 |
| D2 | LLM host process | In-Nim worker thread. | §10 |
| D3 | Belief state writable by | Inner-loop update stage only; directive slot writable by guidance thread. | §3 invariants |
| D4 | Mode scratch lifecycle | Reset on mode switch, persist within mode. | §5.6 |
| D5 | Action-layer owns A\* | Modes emit `steer_to`, action layer owns pathing + motion + discipline. | §4.4, §6 |
| D6 | Ghost behavior | Forced to `task_completing`; ghost-aware A\* mask. | §5.7 |
| D7 | Meeting mode | LLM direct control via action queue; safety-net fallback vote skip. | §7 |
| D8 | LLM snapshot format | JSON dump of curated belief subset. | §8.3 |
| D9 | Validation | Guidance validates once; inner loop re-validates every tick. | §8.4 |
| D10 | Reflex pattern | **Reflex = forced mode switch**, edge-triggered, evaluated in update-belief, anti-thrash cooldown, starter list of 4. | §5.8 |
| D11 | Imposter default directive | `hunting` with opportunistic + cover. | §9.1 |
| D12 | Task-completing mode | Fresh implementation, informed by modulabot's code but not copied. | §12.2 |
| D13 | Trace schema | Extends modulabot's: adds guidance, modes, reflexes streams. | §11 |
| D14 | Fallback-only playability test | Required before first submission. | §9.2 |
| D15 | Meeting LLM context | Full speaker-attributed chat transcript + meeting history + vote tally + per-player evidence + self-action history via conversation history. | §7.2 |
| D16 | LLM conversation history | Stateful across a meeting's calls; stateless across gameplay calls. | §7.3, §8.5 |
| D17 | Vote soft-lock | `confirm_vote` is irrevocable; subsequent re-votes are ignored within the same meeting. | §7.5 |
| D18 | Reflex evaluation stage | Update-belief, not decide, so target mode's `decide` runs same tick. | §4.2, §5.8 |
| D19 | Phase 1 sub-plan | Port perception in 6 sub-phases (1.0 foundation → 1.6 voting). Each sub-phase is its own commit with tests. | §15 |
| D20 | Phase 1.1 asset baking | Door #1 of the §15 choice: deterministic Nim bake tool (`tools/bake_assets.nim`) emits raw `.bin` blobs into `perception/baked/`; runtime consumes them via `staticRead`. Bake tool reads the upstream `~/coding/bitworld` checkout *directly* (using the same `bitworld/aseprite` parser the live server uses) so modulabot's data dir is no longer in the trust chain. No PNG decoder dependency in the runtime, no runtime file I/O, no nimby in the runtime build. `BakeSchemaVersion` constant pins compile-time vs. baked-dir agreement. | §15, README "Regenerating baked assets" |
| D21 | Phase 1.2 kernel sharing | Followed §15's guidance: `perception/localize.nim` imports `among_them/common/perception_kernels/{sprite_match,localize}.nim` via `from "../../..." as kX import nil` (relative-path import, no leaked identifiers, qualified-only access). Avoids both code duplication and FFI/shared-library indirection. The kernels are pure Nim, parity-pinned by modulabot's test suite; drift on either side fails our compile or our fixture-pinned camera tests. Patch index is built in Nim (modulabot built it in numpy); scalar one-shot, cached at module level. | §15, `perception/localize.nim` header |
| D22 | Phase 1.3 actor scan pattern | `perception/actors.nim` imports `kSpriteMatch.mb_match_actor_sprite_all` and `kSpriteMatch.mb_actor_color_index_all` via the same `from "../../..." as kSpriteMatch import nil` pattern. Orchestration mirrors modulabot's `actors.py::scan_all` ordering (role → self-colour → bodies → ghosts → crewmates). Dedup is greedy raster-order within Chebyshev radius, matching the Python `_dedup_anchors`. Actor scan runs in the bot pipeline *after* localize (needs camera for future world-coord conversion) and *before* decision/action. Detected sprites are stamped into the ignore mask for phase 1.4's task-icon scanner. New `ActorScanner` struct holds reusable match/colour buffers to avoid per-frame allocation. | §15, `perception/actors.nim` header |

Further decisions get appended here as they're made.

---

## 15. Phase 1 sub-plan (perception port)

Phase 1 was originally scoped as a single commit: "wire in modulabot's
localize / sprite / task / voting parse." That's ~4.5 kLOC of Python
(or ~2.8 kLOC of Nim in `bitworld/among_them/players/modulabot/`).
Doing it in one commit would be rushed and poorly tested. Breaking
it into sub-phases lets each one land fully tested and documented.

Each sub-phase is a self-contained commit that extends the real
`Percept` and `PerceptionState` fields, wires new perception code
through the pipeline, and adds fixture-based tests.

| Sub | Scope | Deps | Status |
|---|---|---|---|
| **1.0** | Frame unpacking, interstitial detection (black-pixel %), dynamic-pixel ignore-mask scaffolding, pipeline wire-in (`perceive` → `updateBelief` → `PerceptionState`). Fixture tests using real frames. | none | ✅ shipped |
| **1.1** | Perception data loading — palette, player colours, sprite atlas, map/walk/wall layers, ASCII font, map.json. Baked into raw `.bin` blobs by `tools/bake_assets.nim` (reads `~/coding/bitworld` directly via the upstream `bitworld/aseprite` parser, single source of truth) and embedded into the Nim binary via `staticRead`. No PNG decoder, no nimby in the runtime. Compile-time shape asserts catch stale baked dirs. | 1.0 | ✅ shipped |
| **1.2** | Camera localization — port of `modulabot/localize.py`'s orchestration in `perception/{geometry,localize}.nim`. Reuses `mb_score_camera`, `mb_hash_frame_patches`, `mb_vote_camera_candidates` from `among_them/common/perception_kernels/` via `from "../../common/perception_kernels/X" as kX import nil` — keeps the kernel as the single source of truth, no FFI / shared-library indirection (DESIGN.md §15 "Sharing nim_perception"). Patch-index built lazily in Nim on first non-interstitial frame. Pipeline calls `updateLocation` on gameplay frames and `reseedCameraAtHome` on interstitials. Camera-lock fixtures pinned against modulabot ground truth; smoke benchmark guards against catastrophic regressions. | 1.1 | ✅ shipped |
| **1.3** | Actor / body / ghost scanning — wraps `mb_match_actor_sprite_all` and `mb_actor_color_index_all` from `among_them/common/perception_kernels/sprite_match.nim`. Ports modulabot's `scan_all` ordering (role detection → self-colour → bodies → ghosts → crewmates). Stamps actor sprite exclusions into the ignore mask. Merges results into `SelfState.role/colorIndex` and `PerceptionState.visibleCrewmates/Bodies/Ghosts`. ~2 ms per gameplay frame. | 1.2 | ✅ shipped |
| 1.4 | Task icon + radar dot scanning — wrap `mb_scan_task_icons`. Populates `PerceptionState.visibleTaskIcons` and the task-state machine in `Belief.tasks`. | 1.2 | |
| 1.5 | ASCII OCR — wrap `mb_best_glyph` and `mb_text_matches`. Classifies interstitial text (`CREWMATE`, `IMPS`, `CREW WINS`, `IMPS WIN`) and chat lines. | 1.1 | |
| 1.6 | Voting-screen parse — port `voting.py`'s grid layout, slot / cursor / self-marker / vote-dot parsing, chat OCR, speaker pips. Populates `SocialState.currentMeetingChat`, `VotingState` (TBD if needed as a separate sub-record). | 1.5 | |

### Sharing perception kernels via `among_them/common/`

`among_them/common/perception_kernels/*.nim` is pure Nim,
self-contained (no bitworld imports), stateless kernels with
parity-pinned numpy fallbacks. Both modulabot and guided_bot consume
them directly:

- **modulabot** wires them into its FFI surface via
  [`modulabot/nim_perception/lib.nim`](../modulabot/nim_perception/lib.nim)
  + a Python ctypes loader; modulabot's
  [`build.py`](../modulabot/nim_perception/build.py) compiles the
  dylib with `--path:` set to the shared directory.
- **guided_bot** (phase 1.2+) imports them directly via
  `from "../../common/perception_kernels/X" as kX import nil` — no
  FFI roundtrip, qualified-only access to keep namespaces clean.

Rationale:

- No code duplication between agents.
- Neither agent reaches into the other's tree; the shared dir is the
  *only* place these kernels live.
- A change to one of the kernels is a single diff that benefits both
  agents simultaneously, and the parity tests live with the kernels'
  one canonical implementation (modulabot owns the parity oracle
  because it has the numpy fallback).

Risk: the kernels evolve under modulabot's parity tests. If guided_bot
depends on a specific kernel shape and the kernel signature changes,
guided_bot breaks silently until its tests catch it. The
phase-1 test suite in guided_bot specifically exercises every
kernel guided_bot consumes, so drift shows up immediately.

Phase 1.0 did not yet import any kernel; phase 1.2 adds the
dependency on `sprite_match.nim` + `localize.nim`. Phase 1.3 adds
the dependency on `sprite_match.nim`'s `mb_match_actor_sprite_all`
and `mb_actor_color_index_all` (imported via `perception/actors.nim`).
Phase 1.5 will add the dependency on `ocr.nim`.

See [`among_them/common/README.md`](../common/README.md) for the
shared-directory convention.

