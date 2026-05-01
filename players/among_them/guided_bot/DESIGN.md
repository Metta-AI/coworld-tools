# guided_bot — Design Report (v0, abstract)

> **Status:** design-only. No code written. This document is the first
> artifact for the agent; everything below is subject to revision during
> the open-questions pass.
>
> **Audience:** future self, collaborators, and the LLM harness that will
> eventually consume this file. Implementation details (Nim syntax, file
> layouts, FFI shape, buffer sizes, trace schemas) are deliberately
> deferred. This doc is about the *shape* of the agent, not its code.
>
> **Related reading** — read these first; they are load-bearing context:
>
> - `among_them/modulabot/README.md` / `bitworld/.../modulabot/DESIGN.md`
>   — the scripted baseline whose perception layer and pipeline we can
>   reuse wholesale. This doc assumes we inherit, not reinvent,
>   perception.
> - `bitworld/.../how_to_make_a_bot.md` — the hard-won lessons about
>   localization, task states, radar, momentum, voting. All still apply.
> - `bitworld/.../modulabot/TRACING.md` — the trace schema we'll extend.

---

## 1. Goals & non-goals

### Goals

1. **A single agent with two time scales.** An inner loop that runs at
   game tick rate (~24 Hz) and an outer loop that runs at LLM-call rate
   (fractions of a Hz), cooperating through a narrow, well-defined
   interface. The inner loop is always responsive; the outer loop is
   always thinking.
2. **Modular, extensible, easy to reason about.** The primary
   extensibility axis is **modes**. Adding a new mode (a new way for the
   bot to behave) is a new file implementing one interface, with no
   changes to perception, action, or the core loop.
3. **Uniform belief state.** Every mode consumes the same structured
   belief-state object. Modes disagree about *what to do*, never about
   *what is true*.
4. **LLM-in-the-loop strategy, not LLM-in-the-loop control.** The LLM
   shapes *what the bot is trying to do* (mode + parameters) and
   occasionally speaks directly (meeting mode). It does not drive
   per-frame button masks outside of meetings.
5. **Graceful degradation.** If the LLM sidecar is slow, unavailable,
   rate-limited, or crashed, the bot keeps playing competently using
   only the most recent directive (or a safe default).
6. **Submission-ready.** The final bundle must pass `cogames`
   validation and ship through the Nim-via-ctypes pattern used by
   modulabot. The sidecar is an operational concern, not a submission
   artifact — the bot has to play acceptably with the sidecar absent.

### Non-goals (v0)

- **No new perception.** We reuse modulabot's perception modules
  (localization, sprite matching, task icons, voting parse, ASCII OCR).
  If we need to change perception to support a new mode, that's a v1
  concern.
- **No training.** No neural policies, no RL. Pure scripted inner loop
  guided by an external reasoner.
- **No new games.** Among Them only. Generalizing the architecture to
  CvC or Four Score is deferred.
- **No strategy parity bar vs. modulabot.** We expect different
  behavior; the point of this agent is to *diverge* on strategy. Parity
  applies only at the perception layer (and even there, only if we
  reuse modulabot code unchanged).
- **No LLM-per-tick.** The inner loop must be able to run for many
  frames without any outer-loop input.

---

## 2. Architecture at a glance

```
                    ┌───────────────────────────────────┐
                    │         GUIDANCE LOOP             │
                    │       (async, LLM-driven)         │
                    │                                   │
                    │   belief snapshot ──► LLM ──►     │
                    │                     directive     │
                    └──────────────┬────────────────────┘
                                   │
                    directive = (mode, mode_params, meta)
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────┐
│                      INNER LOOP (24 Hz)                  │
│                                                          │
│   frame ──► perceive ──► update belief ──► decide ──► act│
│                             ▲                  ▲         │
│                             │                  │         │
│                             └── current directive        │
│                                 selects a mode,          │
│                                 mode reads belief,       │
│                                 produces action          │
└──────────────────────────────────────────────────────────┘
```

Three distinct components:

- **Inner loop** — perceive, update belief, decide an action, emit it.
  Deterministic given `(belief, directive)`. Never blocks on the LLM.
- **Guidance loop** — an asynchronous consumer of belief snapshots and
  producer of directives. Runs in a Python sidecar (see §10) and talks
  to the Nim core over a narrow channel.
- **Belief state** — the single shared data structure. Consumed by
  every mode, serialised for the guidance loop, logged for the trace.

The rest of this document is about the interfaces between these three
components, and what goes inside each.

---

## 3. The belief state

The belief state is the agent's working model of the world. It is:

- **The same structure for every mode.** Mode A and mode B look at the
  same fields; they may emphasise different slices, but they never
  disagree about schema.
- **The same structure the LLM sees** (after a lossy serialisation step
  — raw pixel buffers and full patch tables don't go over the wire).
- **The same structure that ends up in the trace.** Snapshots for the
  offline harness come from here.

### Conceptual layers

1. **Self.** Role (crew / imposter / ghost), colour, alive/dead, kill
   cooldown remaining, known teammate colours (imposter), last known
   home, this-round meeting count, current mode and directive.
2. **Perception.** Camera lock, self world position, visible actors
   (colour + position + last-seen tick), visible bodies, visible task
   icons, radar dots, interstitial state, voting parse when applicable.
   Everything modulabot's perception layer already produces.
3. **Memory.** Per-player summary (last seen tick/place, times near
   bodies, times witnessing kills, alibis, vote history, ejected
   flag); per-body event; per-meeting event; sightings log. Pattern
   from `modulabot/memory.nim`.
4. **Tasks.** Per-task state (`not_doing` / `maybe` / `mandatory` /
   `completed`), last icon sighting, assumed assigned set, progress
   counters. Crewmates only; imposters carry a parallel "fake task
   plan" in mode params.
5. **Social / strategic.** Recent chat lines (speaker-attributed),
   accusations heard, votes cast, votes received. Meeting transcript.
6. **Goal / directive.** The current mode, mode parameters, directive
   source (LLM-supplied vs. default-fallback), directive timestamp,
   directive TTL.

### Invariants

- The belief state is updated **only** by the perceive/update phase of
  the inner loop. Modes and the guidance loop both read it; neither
  writes it.
- The directive block is the one exception: the guidance loop writes
  it (atomically, see §10), the inner loop reads it, and modes never
  write it (they write their own *outputs* — actions — not the
  directive).
- Every field has a "confidence" or "last-updated-tick" where
  applicable. A mode consulting a stale belief is the mode's problem to
  handle; the belief layer doesn't lie.
- The belief state is cheaply snapshottable. Serialising it for the
  sidecar or for a trace should not require walking the whole
  perception pipeline again.

### What's explicitly *not* in the belief state

- Raw framebuffers. They live in the I/O layer and are consumed,
  unpacked, and discarded per tick.
- Patch-hash tables and sprite atlases. They're perception machinery,
  not beliefs about the world.
- Per-mode scratch state. Each mode owns its transient data (A\* path,
  fake-task countdown, kill approach sub-state). The belief layer does
  not accumulate per-mode cruft.

---

## 4. The inner loop

The inner loop is a pipeline with four stages. Each stage is a pure
function of its inputs, with exactly one side effect at the boundary.

```
frame ──► perceive ──► update belief ──► decide ──► act
           (read)         (write)         (read)    (write)
```

### 4.1 Perceive

- Input: raw frame, previous belief.
- Output: a "percept" — the delta of what this frame tells us (camera
  lock, visible actors, task icons, radar dots, interstitial/voting
  state, new chat lines, role reveal, game over).
- Reuses modulabot's perception layer verbatim where possible. The
  percept is a small, stringly-typed struct; the update stage is what
  merges it into the long-lived belief.

### 4.2 Update belief

- Input: previous belief, current percept.
- Output: new belief.
- Responsible for: memory maintenance (sightings log, per-player
  summaries), task state transitions (`mandatory ↔ completed` with the
  modulabot icon-area rules), meeting boundaries (round reset hooks),
  directive TTL bookkeeping (expire stale LLM directives if they haven't
  been renewed in N ticks).
- **This is also where the directive slot is read** from the channel
  coming back from the guidance loop. Reading is atomic; if a new
  directive has landed, the belief's `directive` field is swapped in.

### 4.3 Decide

- Input: current belief (including current directive).
- Output: an **action intent** (see §6 for the structure).
- Responsibility: route to the correct mode handler, invoke it, return
  its output.
- The decide stage is dumb: it contains no strategy. It reads
  `belief.directive.mode`, looks up the handler from a registry, and
  calls it. That's the whole method. This is the single extension
  point for adding behavior.

### 4.4 Act

- Input: action intent.
- Output: button mask + (optionally) chat payload.
- Responsibility: the only place in the agent that speaks the game's
  wire protocol. Translates intents into the 7-bit button mask, handles
  "only send on mask change", and emits chat packets (meeting mode
  only). All momentum-aware steering, A\* step extraction, jiggle, and
  button-edge handling live here.

Keeping this stage separate from the modes is deliberate: it means
every mode produces the same kind of output (an intent), and the action
layer is the single place where "how do we actually turn an intent into
bytes" lives. Modes don't know about edge-triggered cursor buttons or
the "don't hold A while moving during a task" rule — those are action-
layer details.

---

## 5. Modes

A **mode** is a named strategy. It owns a chunk of the decision tree
for one conceptual behavior (completing tasks, pretending to, hunting
kills, hiding, participating in a meeting). Modes are the primary
extensibility surface.

### 5.1 The mode interface (abstract)

Every mode implements the same contract:

- `decide(belief, params) -> action_intent`
- `is_legal_for(belief) -> bool` (role, phase, alive/dead gates)
- optional `on_enter(belief, params)` / `on_exit(belief)` hooks for
  mode transitions (e.g. freeing an A\* plan, resetting a fake-task
  timer).

That's the entire interface. No shared mutable state between modes;
all communication with the rest of the agent goes through
`action_intent` out and `belief` in.

### 5.2 Mode registry

Modes are registered in a single place (one file, one table: mode-name
→ handler). The decide stage looks up the handler by name, asserts
`is_legal_for(belief)`, and calls `decide`.

Adding a mode is: create a new file, implement the interface, add an
entry to the registry. No other file changes.

### 5.3 Mode parameters

Each mode takes a `mode_params` blob in addition to the belief. This is
the LLM's slot for "but do this, specifically". The shape of
`mode_params` is per-mode — the registry knows the schema for each mode
— but it's always a small, serialisable, structured object (not free
text). Examples that motivated the design:

- `task_completing { task_index: int }` — "complete task #3".
- `task_completing { task_index: nearest_mandatory }` — "complete
  whatever the closest mandatory task is". (Sentinels get named
  explicitly in the schema; modes don't parse magic strings.)
- `fear { min_visible_others: int, safe_zone_hint?: point }` — "get
  and stay near ≥2 others, preferably in the cafeteria".
- `hunting { target_color?: int, opportunistic: bool }` — "go for
  <color> when isolated, or take opportunistic kills".
- `pretending { fake_task_index: int, loiter_ticks: int }`.

**Key invariant:** a mode must be able to do something sensible with
*only* its params and the belief. No hidden communication channel from
LLM to mode.

### 5.4 Mode enumeration (tentative)

The LLM picks from a known, finite enum. Not free-text. The enum is the
design's strategic vocabulary.

Crewmate (and alive-imposter-pretending):

- `idle` — safe default: stand somewhere reasonable, observe.
- `task_completing` — the modulabot crewmate policy, essentially.
- `fear` — stay with groups, avoid being alone.
- `investigating` — move toward a specific suspect or last-known body
  location, gather evidence.
- `reporting` — a body is known; navigate to report range and press A.

Imposter (not ghost):

- `pretending` — walk task-to-task without doing them.
- `hunting` — pursue a kill opportunity.
- `fleeing` — body seen; get far away from it fast.
- `sabotage_watching` — (placeholder for sabotage support if seasons
  enable it).
- `alibi_building` — loiter near a visible crewmate in a public room.

Shared:

- `meeting` — voting interstitial is active; LLM takes direct control.
  See §7.
- `ghost_observing` — dead, no actions affect the game; used to keep
  the trace honest.

This list is a starting point, not a contract. The registry is the
source of truth; this doc tracks the intent.

### 5.5 Mode exclusivity

One active mode at a time. If a situation demands "pretending while
keeping an eye out for an opportunistic kill", that's the LLM's job to
express either as a compound mode or as rapid directive switching. The
inner loop does not multiplex modes.

However, **cross-cutting observers** do exist (passive belief-updaters
that watch for critical events regardless of mode): "a body appeared
in view", "kill cooldown just elapsed", "the voting interstitial
triggered". These raise flags on the belief; modes choose whether to
react. They are **not** modes.

---

## 6. The action intent

The output of every mode is a structured action intent, not a raw
button mask. Shape (abstract):

- `steer_to: point | none` — go here. Action layer picks A\* + momentum
  steering.
- `press_a: bool` — hold/tap A (with the "don't mix with movement"
  rule for tasks enforced by the action layer when the mode says so).
- `press_b: bool` — generally unused, kept for completeness.
- `cursor: {left, right, none}` — meeting mode only.
- `chat: string | none` — meeting mode only.
- `facing: direction | none` — for cases where facing matters but
  movement does not.
- `discipline: enum { normal, task_hold, kill_strike, report }` —
  hint to the action layer about which movement discipline applies
  (e.g. `task_hold` overrides any steering and holds only A).

The action layer owns every tactical detail that doesn't belong in
strategy. Modes stay high-level.

---

## 7. Meeting mode (special case)

Meetings are the one place where the LLM needs to act within a short,
bounded window and needs to produce actual game output (a vote, a line
of chat). The inner-loop-only-consumes-directives model breaks down.

### 7.1 What makes meetings different

- They are short (hundreds of ticks at most).
- The only actions are: move a cursor, press A to confirm a vote, and
  emit chat strings.
- The outputs are high-value: one bad vote loses the round.
- The information surface is rich and verbal (chat transcript, vote
  tally) — exactly the LLM's comparative advantage.

### 7.2 Proposed model

When the belief detects a voting interstitial, the inner loop switches
into `meeting` mode, which:

1. Immediately asks the guidance loop for a **meeting plan**: a
   structured object like
   `{ chat: [line1, line2, ...], vote: color | skip | "abstain" }`.
2. While waiting, the meeting mode's inner policy emits cursor-rest /
   no-op actions and does not spam. (It can type nothing, or type a
   pre-canned "thinking…" line — tbd.)
3. When the plan lands, the meeting mode executes it: types chat lines
   one at a time (respecting game chat constraints), navigates the
   cursor to the chosen vote, presses A.
4. If no plan lands before the voting timer is about to expire, fall
   back to a safe default: vote skip, say nothing. This fallback is
   how meeting mode degrades gracefully when the LLM is down.

So the LLM does not drive per-tick actions during meetings either — it
drives a *meeting plan* which the inner loop executes. The "LLM takes
direct control" framing in the original spec is softened here; the
actual locus of control is still the inner loop, but it's executing a
richer set of instructions. See §12 for alternatives if we change our
minds.

### 7.3 Mid-meeting replanning

If the LLM wants to change its mind after new chat arrives, a second
plan can land and override the first. The meeting mode uses
"most-recent plan wins". Already-typed chat lines can't be unsent.

---

## 8. The guidance loop

### 8.1 Responsibilities

- Periodically (or on belief-driven triggers) read a snapshot of the
  belief state.
- Summarise it for the LLM (token budget, selective detail).
- Call the LLM.
- Validate the response (schema-legal mode? legal for role? params in
  range?).
- Publish the validated directive to the shared directive slot read by
  the inner loop.
- Emit a structured outer-loop trace entry (prompt, response, chosen
  directive, latency, token counts).

### 8.2 Cadence & triggers

The loop is a hybrid of periodic and event-driven:

- **Periodic:** every N ticks (configurable; probably ~2-5s of game
  time), unconditionally submit a snapshot.
- **Triggered:** the inner loop can set a "wake up" flag on the belief
  when something important happens (body appeared, kill cooldown
  elapsed, meeting started, new chat from another player, role
  revealed). The guidance loop polls this flag and prioritises high-
  trigger snapshots.
- **Throttled:** hard cap on LLM calls per second (and per match) to
  keep costs bounded and to avoid rate-limit storms.

### 8.3 The directive slot

One slot, atomically written. Contents:

- `mode` (enum member)
- `mode_params` (per-mode schema)
- `issued_at_tick`
- `ttl_ticks` — after this many inner ticks without a refresh, the
  inner loop downgrades to a safe default (see §9). Gives the agent a
  dead-man switch.
- `reasoning` (free text, for trace / debugging only; inner loop
  ignores).
- `source` — `"llm"` or `"default"`.

Only the latest directive matters. Stale ones are discarded.

### 8.4 Validation

The guidance loop is **not** trusted to produce legal directives. The
inner loop's decide stage rechecks `is_legal_for(belief)` on the active
mode every tick and falls back to default if the mode is now illegal
(e.g. LLM said "hunting" but we're now a ghost, or "task_completing"
but we're an imposter). This is a defence-in-depth move — the sidecar
should also validate, but we don't rely on it.

### 8.5 Prompt engineering is not in this doc

How we prompt the LLM, what context window we give it, what model we
pick, whether we use tools/function-calling — all deferred. They are
crucial to success but orthogonal to the architecture described here.

---

## 9. Failure modes & fallback

The bot must play competently when:

- The sidecar is not running.
- The sidecar is running but the LLM is slow (first directive arrives
  hundreds of ticks in).
- The LLM returns garbage (invalid JSON, unknown mode, illegal mode).
- The sidecar crashes mid-game.
- The network to the LLM provider is down.
- Rate limits trip.

### 9.1 The "default directive"

At any moment, if no usable LLM directive is present, the inner loop
uses a **default directive** derived from role and phase:

- Crewmate, alive, in gameplay: `task_completing { task_index:
  nearest_mandatory }`.
- Imposter, alive, in gameplay: `pretending { fake_task_index: random
  from task list, loiter_ticks: default }`.
- Voting phase, any role: `meeting { plan: "skip_no_chat" }` — the
  bulletproof default meeting plan.
- Ghost: `ghost_observing`.

This means: even with the sidecar completely absent, the bot plays a
roughly-modulabot-equivalent scripted game. The guidance loop makes it
smarter; it doesn't make it functional.

### 9.2 Validation gate

Submission dry-runs must pass with the sidecar absent, because the
cogames tournament image may not have our sidecar available. That's an
explicit constraint on the design: the Nim bot is the submission
artifact; the sidecar is an opt-in enhancement.

---

## 10. Concurrency & IPC (sidecar model)

Given the answer to leave strategy open but assume **Python sidecar**:

- The Nim core runs the inner loop, owns the game WebSocket, owns the
  belief state, owns the directive slot.
- A separate Python process runs the guidance loop and the LLM client.
- The two processes talk over a small, framed channel — likely a Unix
  domain socket or a localhost TCP socket. The wire format is JSON
  (for now; msgpack or protobuf if we ever measure a cost).
- Protocol: two messages.
  - Nim → sidecar: `snapshot { tick, belief_summary, triggers }`.
  - sidecar → Nim: `directive { mode, mode_params, ttl_ticks, ... }`.
- Ordering: the sidecar always replies to the latest snapshot only;
  older in-flight snapshots are dropped.
- Lifetime: the sidecar is spawned by the Nim bot at startup (or by
  the test harness) and torn down at shutdown. It's not a long-lived
  shared service.

Thread model on the Nim side:

- Main thread: inner loop (game I/O + perceive/update/decide/act).
- One reader thread: blocks on the sidecar socket, deposits the latest
  directive into the shared slot with a single atomic swap.
- One writer thread (or the main thread at end-of-tick): serialises
  belief snapshots and pushes them to the sidecar.

The inner loop *never* blocks on the sidecar. Reads are non-blocking
(check the slot), writes are best-effort (drop if the pipe is full).

### 10.1 Sidecar restart & re-attach

If the sidecar dies, the Nim core keeps running on the default
directive. A lightweight "restart sidecar" supervisor in the Nim
process can respawn the sidecar if it detects the socket went silent
for too long. Whether this is worth the complexity is an open
question — the simpler default is "if it dies, you lose guidance for
the rest of the match".

---

## 11. Tracing & observability

Extend the modulabot trace schema (see its `TRACING.md`) with
outer-loop entries. New event kinds:

- `guidance_snapshot_sent` — the belief summary we sent.
- `guidance_directive_received` — the LLM's full response + parsed
  directive + validation result.
- `directive_activated` — inner loop picked up a new directive.
- `directive_fell_back` — inner loop downgraded to default because
  TTL expired / mode became illegal / validation failed.
- `mode_transition` — which mode is active, since when.

Goal: a post-game replay can show the full dialogue between inner and
outer loops, attribute every action to a directive, and attribute every
directive to a prompt/response pair. This is how we'll debug and iterate
on the LLM policy.

---

## 12. Open questions & pushback

### 12.1 Underspecified in the original description

1. **Mode + mode_goal is too narrow.** A single scalar "mode_goal"
   doesn't capture realistic directives. Resolved in this doc by
   making params per-mode structured objects (§5.3), but this adds
   schema management burden. Worth doing.
2. **What does the LLM actually see?** The brief says "LLM-driven
   guidance" but not what context it has. This doc punts that to §8.5
   as a separate problem, but it's actually where most of the
   intelligence lives. A bot with a perfect inner loop and a
   misinformed LLM will lose.
3. **What are the actual modes?** §5.4 lists a tentative set. The real
   list will come from playing games, noticing behaviours we want to
   name, and carving them out. Expect churn.
4. **Meeting mode cadence.** Does the LLM get one shot per meeting, or
   can it replan mid-meeting as new chat arrives? §7.3 says
   "most-recent plan wins", but this interacts with LLM latency: if
   the typical LLM call takes 2s and a meeting lasts 25s, that's maybe
   3 plans per meeting in the best case — not many. Needs measurement.
5. **Is `ghost_observing` worth the mode slot?** Ghosts can't do
   anything that affects the outcome, but we probably want a mode so
   the trace stays honest and we can study ghost behaviour. Cheap
   mode; keep it.

### 12.2 Pushback on the "two loops" framing

The biggest risk: **latency mismatch.** Inner loop at 24 Hz, outer at
maybe 0.5-2 Hz. That's a ratio of ~20-50. A directive lives for dozens
of frames without refresh. During those frames:

- The bot may see a body, witness a kill, lose track of itself, or
  walk into a different room.
- The active mode may suddenly be a bad choice, but the LLM doesn't
  know yet.

Mitigations in this doc:

- Triggered snapshots (§8.2): on a "big event", we force a snapshot
  send.
- Cross-cutting observers (§5.5): the belief layer can still react to
  critical events independent of the current mode.
- TTL + default fallback (§8.3, §9.1): a stale directive expires to
  "safe default" rather than being executed blindly.

But none of these make the LLM faster. If the right strategic call is
"flee NOW", the LLM is not going to make it in time. This means the
inner loop needs **its own fast reflexes** for a small number of life-
or-death situations:

- If a body appears and I'm an imposter, the inner loop must flee
  regardless of what the current directive says.
- If my kill cooldown just elapsed and a lone crewmate is in front of
  me and the current directive is `hunting`, the inner loop must act
  immediately, not wait for a directive refresh.
- Crewmates in `task_completing` should interrupt the task if a body
  appears in view and navigate to report, regardless of the directive.

These are **reflexes**, and the design must carve out space for them
without reintroducing mode-multiplexing. Proposed approach: each mode
declares a small list of "interrupt conditions" that, if tripped,
override its own decision this tick with a specific canned action
(e.g. `task_completing` interrupts to `reporting` when a new body is
in view). This keeps reflexes local to modes but doesn't require the
LLM to react.

Worth discussing before coding.

### 12.3 Pushback on "the LLM sets mode + mode_goal"

The original description implies the LLM picks from a finite
vocabulary. This is the right default (tight control, easy to
validate, easy to trace), but it also means the LLM can't do the
thing LLMs are best at — generating arbitrary language, including
arbitrary chat lines and arbitrary accusations. The meeting-plan
escape hatch (§7) is the only place where free text flows from LLM to
game.

Decision: **keep the mode enum.** If we want richer LLM output, we add
structured fields inside `mode_params` (e.g. `pretending { cover_story:
string }` for future use in chat). We do not let the LLM free-form
over the action space.

### 12.4 Pushback on "same structure across all modes"

This is aspirational. In practice, modes will want fields that no
other mode needs (`pretending` needs fake-task-plan state; `hunting`
needs kill-approach sub-state). Two options:

- Every field is in the belief state, most are unused by most modes.
  Pro: uniform. Con: bloated belief.
- Modes own their own scratch state; the belief only holds *world*
  state, not *agent* state.

This doc picks **option B** (§3, "Per-mode scratch state"). The
belief state is about what's true in the game. Mode-specific planning
state lives in the mode. This is a deviation from the brief; flagging
it explicitly.

### 12.5 The sidecar is not part of the submission

Spelled out in §9.2: the sidecar is not shipped to the tournament. The
submitted bot is the Nim core playing on default directives, and
passes `cogames` validation as such. This is a real constraint — it
means **every mode must have a useful default**, and the LLM is
strictly an accelerant. We cannot have modes that *require* LLM
guidance to do anything sensible.

An alternative worth considering: ship the sidecar too, as a secret-
env-backed subprocess started by the policy's `setup_script`. The
cogames CLI supports `--secret-env` for API keys (see `COGAMES.md`
§ Secrets). This is a larger lift (packaging Python deps, ensuring the
tournament image can spawn subprocesses, cold-start latency during the
10-step validation gate). Deferred unless we decide offline guidance
is insufficient.

### 12.6 Am I sure we even want this?

Honest question for the record: modulabot is a known-good scripted
bot. The marginal value of LLM guidance depends on (a) how much
strategic variance there is in Among Them beyond the scripted baseline,
and (b) whether the LLM's strategic reasoning beats a well-tuned
heuristic at the 24 Hz tempo of this game. I suspect yes for meetings
(language-heavy, low-tempo, high stakes) and maybe-yes for high-level
mode selection. I'm less sure the LLM will reliably out-pick a
scripted imposter hunting policy in real time.

Recommendation: build it, but **instrument it so we can measure the
marginal contribution of the LLM**. The trace (§11) already contains
everything needed — mode distribution, directive latency, per-mode
win rate, meeting outcome attribution. After the first handful of
games, we should be able to say "modulabot scored X, guided_bot with
LLM scored Y, guided_bot on defaults only scored Z". If Y ≈ Z, we
know the LLM isn't pulling weight and we can cut it.

---

## 13. What to decide before writing any code

A short checklist of decisions whose answers shape the first commit,
in rough order:

1. **Starting mode enum.** Finalise the tentative list in §5.4. The
   registry is the first non-trivial code and churns painfully if the
   enum changes.
2. **Mode-params schemas.** For each mode in the enum, decide the
   exact fields. They become the contract between the LLM and the
   bot.
3. **Belief-state layout.** At least at the sub-record level (self,
   perception, memory, tasks, social, directive). Field-level detail
   can follow modulabot's types almost verbatim.
4. **Snapshot format.** The subset of belief shipped to the sidecar,
   and its serialisation. Budget a token count per snapshot.
5. **Reflex interrupts.** Which critical events interrupt which modes,
   and with what canned action. §12.2's list is the starting point.
6. **Fallback defaults.** Verify the bot plays a full round on default
   directives only. This is the submission-path smoke test.
7. **Trace schema extensions.** What fields, what JSON shapes, what
   versioning story. Extend modulabot's schema, don't fork it.
8. **Sidecar protocol.** Message shapes, socket type, framing,
   version handshake.

Once those are decided, the code falls out of the design almost
mechanically: a core inner-loop file, one file per mode, an action
module, a belief-update module (thin wrapper over modulabot's
perception + memory), a sidecar-channel module, and a Python sidecar.

---

## 14. Decisions log (to be filled in as we go)

Empty on purpose. Every decision made during review of this doc, or
during the first implementation pass, gets a row here with a pointer
back to the relevant section. Follows the pattern from
`modulabot/DESIGN.md` §10.
