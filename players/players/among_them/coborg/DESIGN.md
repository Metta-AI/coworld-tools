# among-them-coborg — Design

Durable architecture notes for the coborg-based BitWorld Among Them agent.
This document captures decisions, contracts, and invariants that should
outlive any single phase of work. See `PLAN.md` for the phased schedule and
short-term todos.

> **Status (P0 landed, 2026-05-19):** Idle/noop agent wired end-to-end
> through the BitWorld `bitscreen_v1` WebSocket bridge with 17 tests green.
> The architecture, contracts, and invariants below are the durable baseline
> P1+ builds on; per-phase deltas live in `PLAN.md`.

---

## 1. Architecture

```
┌───────────────────── Coworld runner (Docker, WebSocket) ──────────────────┐
│   ws://host:port/player?slot=N&token=…                                    │
│   ↓ 8192-byte 4-bit packed frames (one per tick)                          │
│   ↑ [0x00, mask] input + [0x01, ascii] chat                               │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                  coworld/policy_player.py   (async WebSocket loop)
                                │
┌───────────────────────────────▼───────────────────────────────────────────┐
│  build_runtime(trace_sink, metrics_sink) → AgentRuntime                   │
│                                                                           │
│   perceive(obs, tick) ──► update_belief(b, p) ──► IdleMode.decide ──►     │
│        resolve_action(intent, b, s) ──► AmongThemCommand                  │
│                                                                           │
│   Strategy (synchronous): RuleBasedStrategy → ModeDirective(idle)         │
│   Default directive: ModeDirective(mode="idle", source="default")         │
│   Reflexes: (none in P0)                                                  │
└───────────────────────────────────────────────────────────────────────────┘
```

### Inner-loop vs strategy-loop split

The Coworld Player SDK's [inner-loop contract][coborg-readme] is non-negotiable:

- Perception, belief update, mode decision, and action resolution all run on
  every tick, deterministically, never blocking on outer-loop computation.
- Strategy reads `BeliefSnapshot` under the shared-memory lock and publishes
  validated `ModeDirective`s; the inner loop reads the latest available
  directive without waiting.
- For P0 the strategy is `SynchronousStrategyRunner(RuleBasedStrategy)` —
  trivially equivalent to "default directive every tick." The strategy
  abstraction stays in place so P2+ swaps it out without restructuring.

[coborg-readme]: ../../player_sdk/docs/metta_cogames_framework/README.md

### LLM boundary

Out of scope for the entire P0–P4 schedule (PLAN §6 "Out of scope"). When
introduced later, the LLM strategy will sit behind `AsyncStrategyRunner` and
emit typed `ModeDirective`s — never raw actions, never per-tick calls.

---

## 2. Type contracts

| Type | Defined in | Carries | P0 content |
|---|---|---|---|
| `AmongThemObservation` | `types.py` | the raw 8192-byte packed frame + `slot` | full |
| `AmongThemPercept` | `types.py` | per-tick parsed view (tick, frame ndarray) | tick only |
| `AmongThemBelief` | `types.py` | persistent world model | `tick` counter |
| `ActionState` | `types.py` | transport-side mechanics (pending chat, routes) | `pending_chat` queue |
| `AmongThemIntent` | `types.py` | symbolic intent (`kind: noop \| input \| chat`, `mask`, `text`) | full |
| `AmongThemCommand` | `types.py` | wire packets (`tuple[bytes, ...]`) | full |

Anti-pattern guard (per Coborg "Design Invariants"): **raw frame bytes never
leave perception/belief.** The action resolver and modes consume typed
intents only.

---

## 3. Wire protocol pin

The Coworld player protocol used here matches
`packages/coworld/src/coworld/runner/runner.py` in `Metta-AI/metta` at SHA
`e791117ff1aac01a8ae220c258ab121876511aed`.

- **Inbound:** binary WebSocket message per tick, exactly 8192 bytes,
  4-bit nybble-packed 128×128 frame. Pixel value 0–15 indexes the PICO-8
  palette. Layout: `byte[i] = pixel[2i] | (pixel[2i+1] << 4)`.
- **Outbound:**
  - `bytes([0x00, mask])` — 2-byte input packet. Bits: Up=1, Down=2, Left=4,
    Right=8, Select=16, A=32, B=64. Bit 7 is reserved.
  - `bytes([0x01]) + ascii_bytes` — chat packet. Text must be 7-bit ASCII
    and non-empty after stripping; the resolver drops non-compliant payloads.
- **Connection:** `COGAMES_ENGINE_WS_URL` env var carries the full
  `ws://host:port/player?slot=N&token=…` URL. Token validation happens at
  HTTP upgrade time.
- **Lifecycle:** WebSocket close ⇒ game end. No explicit start/end messages.

The bridge always sends exactly one input packet per inbound frame; chat
packets append after the input packet when the mode requests speech.

---

## 4. Logging and tracing

Per PLAN §8 and decision D3:

- All logs go to **stderr**. Stdout is reserved as a protocol channel even
  though the WebSocket connects out — the discipline avoids regressions when
  third-party dependencies print uninvited.
- The runtime uses `LoggingTraceSink` + `LoggingMetricsSink` (structured
  records via the stdlib `logging` module) plus a thin `JsonStderrTraceSink`
  (one JSON line per `TraceEvent`) for downstream parsers.
- `configure_stderr_logging()` is idempotent (clears existing root handlers)
  so test runs and the bridge can call it freely.

---

## 5. P0 scope and known limitations

- Perception is a no-op; the frame bytes are not unpacked or parsed in P0.
  As of S2.1 the 4-bpp unpacker lives at `perception.frame.unpack4bpp`;
  the bridge will start invoking it once `perceive()` wires the percept
  fields in S5.
- Belief carries only a tick counter. P1 introduces the
  self/world/entities/tasks/social/inferences sections per PLAN §4.
- The bridge speaks `bitscreen_v1` binary only. Among Them never serves the
  JSON `coworld.player.v1` protocol, so there is no JSON fallback path; if
  the runner ever sends a non-binary first message the bridge logs it at
  debug level and the smoke run will time out. Treat that as a runner-side
  misconfiguration rather than something to handle here.
- Reflexes, fallbacks, mode TTLs, and `apply_inferences` are unused in P0
  (the only registered mode is `idle`, which is always legal).

---

## 6. State-vector taps

Reserved section (PLAN D9 / R5). When P1+ adds belief fields that are easier
to source from the structured state vector than from pixels (e.g.
`task_progress`), each tap is recorded here:

| Belief field | Reason for tap | Sourced from |
|---|---|---|
| _(none yet)_ | | |

---

## 7. Trace event vocabulary

Inherited from the Coworld Player SDK canonical set (still labelled
"Cyborg framework" in the underlying architecture docs at
`players/player_sdk/docs/metta_cogames_framework/`):

`perception`, `belief_updated`, `mode_entered`, `mode_exited`,
`mode_completed`, `mode_stalled`, `reflex_evaluated`, `reflex_fired`,
`action_intent`, `act_command`, `snapshot_submitted`, `strategy_evaluated`,
`strategy_inferences`, `directive_rejected`, `directive_reaffirmed`,
`fallback_activated`.

Game-specific extensions reserved for later phases:

`phase_change`, `body_sighted`, `task_started`, `task_completed`,
`kill_attempted`, `vote_cast`, `chat_received`, `chat_sent`.

---

## 8. Open design questions

(See PLAN §12 for the unconfirmed decisions.)

- **D8** — numpy-first / numba-fallback perception. Adopted by default; will
  revisit after P1 perf measurement.
- **D9** — state-vector taps. Adopted by default; document each tap in §6
  when it lands.
- **Parity ground truth** — Nim CLI inside `perception/parity/` (preferred)
  vs instrumenting `guided_bot` directly. Decision deferred to P1 kickoff.
