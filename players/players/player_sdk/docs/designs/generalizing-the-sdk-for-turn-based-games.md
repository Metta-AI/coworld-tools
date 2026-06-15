# Generalizing the Player SDK for turn-based / message-driven games

**Status:** Proposal for discussion
**Date:** 2026-06-15
**Author:** Claude (with James Boggs)
**Audience:** Player SDK owners; players-repo contributors
**Origin:** The mentalist v4 design (`cue_n_woo_lab/docs/designs/mentalist-v4-sdk-rewrite.html`)
argues the SDK doesn't fit a turn-based text game and proposes (§9) several
generalizations. This report independently verifies those claims against the
SDK source as it stands on `main` and turns them into a concrete, prioritized
plan. It is part of a lifelong effort to make `players.player_sdk` genuinely
useful for **every** game we publish, not only gridworlds.

> **Framing.** "Generalize the SDK" does **not** mean retire the gridworld
> machinery. The tick runtime, modes, reflexes, and strategy runners are the
> right tool for cogsguard/crewborg and earn their keep. The goal is to make the
> grid-specific parts *opt-in modules* sitting beside a game-agnostic core, so a
> turn-based player can take the parts it needs (telemetry, conventions, a
> transport, an LLM helper) without inheriting a frame clock it has no use for.

---

## 1. Executive summary

The mentalist design is right that the SDK's *center of gravity* is tick-based
gridworlds, and right that a turn-based text game shouldn't be forced into the
tick runtime. But its key **architectural worry is already false in the current
code**, and getting that fact straight changes the priorities.

Two findings from reading the source:

1. **The telemetry layer is already grid-free.** `trace.py`, `trace_outputs.py`,
   `types.py`, `modes.py`, `strategy.py`, and `runtime.py` import **nothing**
   from mettagrid/cogames/torch. The *only* module that imports mettagrid is
   `coworld_json_bridge.py`, and `players/player_sdk/__init__.py` does **not**
   import that module. mettagrid is an **optional** dependency (the `cogames`
   extra in `pyproject.toml`), not a core one. So the design doc's claim that
   "adopting telemetry pulls in mettagrid-shaped types" is **incorrect against
   `main`** — a text player can already `from players.player_sdk import
   TraceOutputs` with zero gridworld surface. (See §3.1 for the evidence.)

2. **The real gaps are smaller and more tractable than a "the SDK doesn't fit"
   framing suggests.** They are: (a) no shared transport for non-mettagrid
   protocols, so every non-grid player hand-rolls a `websockets` loop; (b) the
   `tick: int` coordinate is hard-wired through trace/metrics even though a turn
   game thinks in phases; (c) no shared LLM-backend helper, so crewborg and
   suspectra each reimplement the same Anthropic-vs-Bedrock client; (d) no
   reusable `TraceConfig` base, so each game copies crewborg's env-driven
   filter machinery.

The highest-value, lowest-risk moves, in order:

| Priority | Move | Effort | Why now |
|---|---|---|---|
| **P1** | **Document & guarantee the telemetry-core boundary** (make the existing grid-independence a *contract*, with a test) | XS | Unblocks every non-grid player immediately; mostly ratifies reality |
| **P2** | **Extract a generic JSON-WebSocket bridge** (`run_message_bridge`) | S–M | crewborg + mentalist + suspectra all hand-roll the same loop |
| **P3** | **Promote a shared LLM-client helper** (backend select + retry + JSON extraction + fallback) | S | Duplicated *verbatim* across two players today; recurs in every LLM game |
| **P4** | **Generalize the trace time coordinate** from `tick: int` to an opaque step label | S | Turn games have phases, not frames; small, mechanical, unblocks clean traces |
| **P5** | **Reusable `TraceConfig` base** parameterized by a game's event families | M | Removes the copy-the-machinery tax for every new player |
| **P6 (defer)** | A first-class **phase/step-machine** primitive parallel to the tick runtime | L | Only worth it once ≥2 non-grid players exist and share a shape |

The throughline: **the SDK already has a clean game-agnostic core; the work is
to (a) draw the boundary explicitly, (b) lift the three things every player
re-implements just *outside* that boundary (transport, LLM client, trace
config) into reusable-but-optional helpers, and (c) loosen the one type
assumption (`tick`) that bakes the gridworld worldview into the otherwise-neutral
telemetry surface.**

---

## 2. What the SDK is and where its grain runs

`players.player_sdk` is the "Cyborg" two-loop framework
(`docs/metta_cogames_framework/`): a fast symbolic inner loop
(`perceive → update_belief → mode.decide → resolve_action`, once per **tick**)
and a slower strategy loop (`BeliefSnapshot → Strategy.decide → ModeDirective`)
connected through typed directives and lock-protected shared memory.

Concretely, the package exposes three separable layers:

- **Runtime layer** — `AgentRuntime`, `Mode`/`ModeRegistry`, `Reflex`,
  `StrategyRunner` (sync/threaded/async/manual), `SharedMemory`. This is the
  per-frame control machinery. It is *generic* in its type parameters (it knows
  nothing about grids directly) but its **shape assumes a monotonic per-tick
  clock** and an every-frame decision cadence.
- **Telemetry layer** — `TraceEvent`/`TraceSink`, `MetricSample`/`MetricsSink`,
  the concrete sinks (`Null`/`List`/`Logging`/`Wandb`), `EventEmitter`, and
  `TraceOutputs` (env-driven sink construction, fan-out, format/destination
  parsing, artifact-zip bundling + upload). This is **fully game-agnostic** and
  is the part with universal value.
- **Transport layer** — `coworld_json_bridge.py`: a websocket loop that speaks
  the mettagrid `coworld.player.v1` token protocol. This is the **only**
  grid/mettagrid-coupled module.

The grain runs through the runtime layer: it's built for continuous gridworlds
where an agent observes and acts every frame (cogsguard, crewborg). A turn-based
text game (Cue n Woo: `state → ask/propose/answer`, ~4 phases, ~7 actions per
episode) has no every-frame reflex to model. The mentalist design's instinct to
**not** wrap that in a tick loop is sound. The question this report answers is:
*which pieces of the SDK should a non-grid player be able to reuse, and what's in
the way?*

---

## 3. Findings, verified against source

### 3.1 The telemetry core is already independent of gridworld code

This is the single most important correction to the originating design doc.

Evidence (all on `main`):

- `grep` for `mettagrid|cogames|torch` across `players/player_sdk/*.py` matches
  **only** `coworld_json_bridge.py` (six imports, all `mettagrid.*`).
- `players/player_sdk/__init__.py` re-exports the runtime, modes, strategy,
  types, and telemetry symbols. It does **not** import `coworld_json_bridge`.
  Importing the package therefore never imports mettagrid.
- `pyproject.toml` lists `mettagrid` only under the optional `cogames` /
  `cogsguard` extras. Core deps are `anthropic`, `numpy`, `pydantic`,
  `websockets`. (`numpy` is the only heavy core dep, and the telemetry layer
  doesn't use it.)
- crewborg already consumes exactly this slice: `policy_player.py` does
  `from players.player_sdk import TraceOutputs` and hand-rolls its own websocket
  loop. It uses the runtime too, but the telemetry import stands alone.

**Implication.** A turn-based player can adopt SDK telemetry *today* with no
gridworld baggage. The design doc treats "telemetry sub-package with no
gridworld dependency" as work to be done (§9, row 4); in fact it's **already
true and just needs to be made a documented, tested guarantee** so future
contributors don't accidentally break it (e.g. by importing the bridge from
`__init__`, or adding a mettagrid-typed convenience to `trace.py`). That demotes
it from "build a new sub-package" to "ratify and protect a boundary" — far
cheaper, and the right P1.

### 3.2 The transport loop is the genuine duplication

Three players hand-roll near-identical async websocket loops because none of
their protocols are the mettagrid token protocol that `coworld_json_bridge`
hard-codes:

- `coworld_json_bridge.run_bridge` — mettagrid `coworld.player.v1` (tokens).
- `crewborg/coworld/policy_player.run_bridge` — Crewrift Sprite-v1 (binary).
- mentalist v4 (planned) — Cue n Woo JSON (`state`/`ask`/`propose`/`answer`).

The common skeleton is identical and protocol-independent:

```
connect(url) → for each inbound message → decode → dispatch to a handler →
optionally send reply(ies) → clean-exit on socket close → guarantee teardown.
```

What differs is purely: text-vs-binary frames, the message-type discriminator,
how a reply is encoded, and what "clean exit" means (crewborg notably must
swallow a code-1006 abrupt close and exit 0, or the Coworld runner fails the
whole episode — a sharp edge every player needs to get right and currently
re-derives). That last point is the strongest argument for extraction: the
non-obvious "exit 0 on unclean close" rule is **operational knowledge that
belongs in the SDK**, not re-discovered per player.

This matches the design doc's top recommendation (§9, row 1) and I agree it's
the highest-leverage *code* extraction.

### 3.3 The `tick: int` assumption leaks the gridworld worldview into telemetry

`TraceEvent.tick: int` (`trace.py`), `EventEmitter(tick=…)`, and
`RuntimeContext.tick`/`StepContext.tick` all assume a monotonic integer frame
clock. For the tick runtime that's correct. But the telemetry layer is supposed
to be game-agnostic, and a turn game's natural time coordinate is a **phase or
turn label** (`"interview:2"`, `"propose"`, `"answer"`), not a frame index.

Today a text player must invent a synthetic integer tick to satisfy
`TraceEvent`. That's a small wart, but it's exactly the kind of grid assumption
that, multiplied across a schema, makes the telemetry feel grid-shaped when it
doesn't need to. The design doc (§9, row 2) calls for an opaque step/sequence
label; I agree, with a compatibility-preserving approach (see §4.4) so existing
grid traces and the viewer keep working unchanged.

### 3.4 The LLM-backend helper is duplicated verbatim

crewborg (`strategy/meeting/llm.py`) and suspectra (`suspectra/llm_meeting.py`)
each independently implement the same pattern:

- choose `AnthropicBedrock` vs `Anthropic` from env flags
  (`USE_BEDROCK`/`CLAUDE_CODE_USE_BEDROCK`/… + `ANTHROPIC_API_KEY` presence),
- pick a model id (Bedrock inference-profile id vs bare model name),
- set a timeout, call `messages.create`,
- extract the first `{…}` JSON object from the text response
  (`_extract_json` / `_extract_json_object` — byte-for-byte the same idea),
- pull `usage`/text out of the response object defensively,
- fall back gracefully when disabled or on error.

This is real, recurring duplication, and it will recur in **every** LLM-driven
Coworld player (mentalist v4 makes three). It's a clean candidate for a small
shared helper. Note the *prompt*, *response schema*, and *decision semantics*
are game-specific and must stay in the game — only the **client plumbing** is
shared. (See §4.3 for the proposed seam.)

### 3.5 The `TraceConfig` filter machinery is re-invented per game

crewborg's `trace.py` is ~215 lines of genuinely reusable machinery —
env-driven include/exclude patterns, named event groups, `fnmatch` matching, a
"lean vs debug vs viewer" level model, a default hosted-log filter — wrapped
around a crewborg-specific *event taxonomy* (`TRACE_GROUP_PATTERNS`,
`NOISY_DOMAIN_EVENTS`). The machinery/taxonomy split is already clean inside
crewborg; the machinery half just isn't shared. mentalist will copy it. This is
the design doc's §9 row 6, and it's a fair P5: lower urgency than transport/LLM,
but a clear "stop copying this" once a second game needs it.

---

## 4. Proposed generalizations (prioritized)

### P1 — Make the telemetry/grid boundary an explicit, tested contract  *(XS)*

The work is mostly to *protect and document* what's already true:

- Add a short section to `docs/` (and the framework README) stating: **the
  telemetry layer (`trace`, `trace_outputs`) and the core types/runtime/modes/
  strategy import nothing from mettagrid/cogames; only `coworld_json_bridge`
  does, and it is never imported from `__init__`.** Non-grid players may depend
  on `players.player_sdk` for telemetry and conventions without the `cogames`
  extra.
- Add a guard test (e.g. `test_no_grid_import_in_core`) that imports
  `players.player_sdk` in a subprocess with mettagrid uninstalled / blocked and
  asserts success, and asserts `coworld_json_bridge` is the sole module that
  imports mettagrid. This makes the boundary load-bearing rather than incidental.
- Optionally expose a documented `players.player_sdk.telemetry` namespace (even
  if it just re-exports the existing symbols) so the boundary is nameable.

**Why P1:** near-zero risk, immediately unblocks mentalist v4 and any future
text player, and prevents silent regressions of the property the whole
generalization story rests on.

### P2 — Extract a generic message-driven bridge  *(S–M)*

Add to the SDK a protocol-agnostic loop, roughly:

```python
async def run_message_bridge(
    url: str,
    handler: MessageHandler,
    *,
    trace_outputs: TraceOutputs | None = None,
    connect=websockets.connect,
    on_close: ClosePolicy = exit_zero_on_unclean_close,
) -> None: ...
```

where `handler` decodes an inbound frame (text or binary) and yields zero or
more outbound frames, and `on_close` encodes the Coworld "exit 0 even on a
code-1006 abrupt close" rule as the **default**. The bridge owns: connect,
iterate, dispatch, send, guaranteed teardown (`finally: runtime.close()`-style
hook), and the close-handling that crewborg learned the hard way.

Keep `coworld_json_bridge` as a *thin specialization* over this loop (it adds
the mettagrid token decode + policy resolution). crewborg's Sprite-v1 bridge and
mentalist's JSON bridge become handlers, not bespoke loops. This is the most
valuable code extraction because it also **captures operational knowledge** (the
unclean-close rule) that is currently tribal.

**Risk/Caveat:** binary vs text framing and per-game "send only on change"
logic (crewborg sends an input packet only when the held mask changes) must stay
expressible in the handler. Design the handler return type to allow "no reply
this message" cleanly. Don't over-fit to request/response — crewborg sends
opportunistically (chat during Voting), not strictly one-reply-per-inbound.

### P3 — Shared LLM-client helper  *(S)*

Promote a small, **optional** (behind the existing `anthropic` core dep)
helper — e.g. `players.player_sdk.llm` — providing:

- `select_client(*, use_bedrock, timeout) -> Anthropic | AnthropicBedrock` with
  the standard env-flag resolution and the Bedrock-vs-direct **model-id mapping**
  helper,
- `extract_json_object(text) -> str` (the shared `{…}` slice),
- `response_text(response)` and `usage_dict(response)` defensive extractors,
- a thin `call_json(client, *, model, system, user, schema_hint, …)` that
  times the call and returns text + usage + latency, leaving parsing/validation
  to the caller.

Explicitly **out of scope** for the helper: prompts, the response schema, and
decision semantics — those are the game's. crewborg's `MeetingDecision`
validation and suspectra's `_validate_decision` stay put. The helper removes
~80 lines of identical plumbing from each and gives mentalist v4 the pattern for
free.

**Note:** bedrock support requires `boto3` (the `bedrock` extra), so the helper
must degrade/raise cleanly when asked for Bedrock without it — mirror crewborg's
lazy import inside the branch.

### P4 — Generalize the trace time coordinate  *(S)*

Loosen `TraceEvent.tick: int` to an opaque step label while preserving backward
compatibility:

- Option A (least churn): keep `tick: int` for the runtime path, **add** an
  optional `step: str | int | None = None` field to `TraceEvent` and let
  `EventEmitter` carry either. The tick runtime keeps writing `tick`; a turn
  player writes `step="propose"`. The CSV/JSON writers already serialize
  whatever's present.
- Option B (cleaner, more churn): rename the coordinate to `seq`/`step` of type
  `int | str` and have the runtime pass its tick as the value; update the viewer
  and crewborg's `TraceConfig` consumers. Migrate `tick` → deprecated alias.

I recommend **Option A** first: it's additive, unblocks clean turn-keyed traces
immediately, and defers the breaking rename until a second consumer justifies
it. Whichever path, the viewer and crewborg trace tooling must be checked — they
read `event.tick` today.

### P5 — Reusable `TraceConfig` base  *(M)*

Lift crewborg's filter *machinery* into the SDK as a parameterizable base:
env-driven include/exclude, named groups, `fnmatch` matching, a level model, and
a pluggable default filter. A game subclasses/configures it with its own event
families and env-var prefix:

```python
config = TraceConfig(
    env_prefix="MENTALIST",
    groups={...},          # game's event taxonomy
    default_filter=lean_filter,
)
```

crewborg's `trace.py` shrinks to just its taxonomy + a `lean_trace_filter`.
mentalist defines its taxonomy and gets the machinery free. Moderate effort
because the env-var prefixing and the "lean/debug/viewer" level semantics need a
clean generic form, and crewborg must be migrated onto it to prove the base
(and avoid a third copy).

### P6 — A phase/step-machine primitive  *(L, defer)*

The design doc proposes a first-class "short sequence of discrete decisions"
primitive parallel to the tick runtime. I'd **defer** this. Reasons:

- A turn game's logic *is* a small state machine; mentalist's own plan puts that
  in a plain, transport-free `PhaseEngine` class with no SDK primitive needed.
  Plain code is the right amount of structure for ~7 actions across 4 phases.
- Building a shared abstraction from a sample size of one risks baking in
  mentalist's specific shape. The right time is *after* a second non-grid player
  (auction? negotiation?) exists and we can see the genuinely common shape.
- The other five items deliver most of the value (telemetry, transport, LLM,
  trace config) without it.

If/when it's built, the design principle is: **same trace/metrics integration as
the tick runtime, driven by discrete domain events rather than a frame clock** —
which P4 (opaque step label) is a prerequisite for.

---

## 5. Sequencing and the "forcing function" discipline

The mentalist v4 build is the ideal forcing function: build the text player
*against* the SDK, and let each point of friction nominate an extraction with
concrete before/after. I'd run it as:

1. **Now, independent of mentalist:** P1 (boundary contract + guard test). It's
   cheap, it's a prerequisite mindset for everything else, and it stands on its
   own as SDK hygiene.
2. **During mentalist v4 build:** implement mentalist's hand-rolled bridge,
   LLM client, and `TraceConfig` *first* (as the design plans), then **extract**
   P2/P3/P5 from the now-three-way duplication — with crewborg and suspectra as
   the second/third callers that prove the abstraction. Don't pre-emptively
   refactor the SDK before the second real consumer exists; the design doc's
   "we won't pre-emptively refactor" instinct is correct.
3. **Opportunistically:** P4 (opaque step label, Option A) lands cleanly
   whenever mentalist wants phase-keyed traces; it's additive.
4. **Deferred:** P6 until a second non-grid game exists.

Each extraction should ship as its own reviewable unit (the lab's operating
model / Graphite-stack discipline), with crewborg migrated onto the shared
helper in the same change that introduces it — otherwise the SDK grows a second
copy instead of removing one.

---

## 6. Corrections to the originating design doc

For the record, so the mentalist v4 doc can be updated:

| Design-doc claim (§2, §9) | Verified reality on `main` |
|---|---|
| "Adopting telemetry pulls in mettagrid-shaped types." | **False.** Telemetry/core import no mettagrid; only `coworld_json_bridge` does, and it's not imported by `__init__`. mettagrid is an optional extra. The work is to *document/protect* the boundary, not create it. |
| "Telemetry is bundled with the runtime [so adoption pulls in grid types]." | Bundled in the same *package*, yes — but not coupled in *imports*. A `players.player_sdk` import is grid-free. |
| "crewborg hand-rolls its own loop because its protocol differs" | **Confirmed.** Sprite-v1 binary ≠ mettagrid tokens. Supports P2. |
| "mentalist + suspectra duplicate the dual-backend LLM pattern" | **Confirmed** (and crewborg makes three). Supports P3. |
| "`tick` conflates frame with decision point" | **Confirmed** — `TraceEvent.tick: int` is hard-wired. Supports P4. |
| "Generic JSON bridge is the top extraction" | **Agreed**, with the added insight that the *unclean-close → exit 0* rule is the most valuable thing to centralize. |

The net effect of the §3.1 correction is **good news for the rewrite**: mentalist
v4 can lean on SDK telemetry today with less risk than the doc assumes, and the
generalization backlog is smaller and more concrete than "the SDK doesn't fit."

---

## 7. Open questions for the SDK owners

1. **Packaging:** is a documented `players.player_sdk.telemetry` namespace (or a
   separately-installable telemetry distribution) wanted, or is "core imports are
   grid-free, guaranteed by test" sufficient? The latter is cheaper and may be
   enough.
2. **Bridge ownership:** should the generic bridge live in `player_sdk` proper,
   given it adds a hard `websockets` dependency to the core? (`websockets` is
   already a core dep, so this seems fine — worth confirming.)
3. **LLM helper scope:** Anthropic-only (matching today's two players), or a
   provider-neutral seam from the start? Recommendation: Anthropic-only now;
   don't speculate a multi-provider abstraction before we have a non-Anthropic
   player.
4. **`tick` migration appetite:** Option A (additive `step` field) vs Option B
   (rename, deprecate `tick`)? Affects the viewer and crewborg trace tooling.
