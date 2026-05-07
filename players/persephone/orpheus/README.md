# Orpheus

Agent *framework* for Persephone's Escape. Orpheus is not an agent itself —
it provides the infrastructure that particular agents plug into.

See [DESIGN.md](DESIGN.md) for the full specification.

## Architecture

Two asynchronous loops connected by consume-on-read buffers:

```
          Inner loop (per-tick, symbolic)         Outer loop (async)
         ┌─────────────────────────────┐        ┌──────────────────┐
         │ perception                   │        │                  │
         │ belief_update                │──push──▶ belief buffer    │
         │ [consume mode buffer]        ◀──pop───│                  │
         │ decide (mode.select_task)    │        │ meta_decide()    │
         │ act (task.select_action)     │        │                  │
         └─────────────────────────────┘        └──────────────────┘
```

The inner loop never blocks on the outer loop. The outer loop blocks until
a new belief state is available, then runs `meta_decide` (agent-defined;
may call an LLM, a rule system, or a hybrid).

## Framework-provided modules

| Module | Responsibility |
|--------|----------------|
| **Perception** | Pixel frames → structured symbolic state (`orpheus/perception/`) |
| **Belief state** | Fixed-schema + flexible dict, updated each tick from perception |
| **Tasks** | 24 pre-built task types (movement, view management, whisper lifecycle, info exchange, leadership, hostage selection, communication, idle) |
| **Hook system** | Typed pre/post callbacks at every phase boundary |
| **Outer loop** | Async mode selection via dual consume-on-read buffers |

## What an agent defines

To build a concrete agent on Orpheus, you supply:

1. **A set of modes** — each mode implements `select_task`, `mode_enter`,
   and `mode_switch_cleanup`.
2. **A `meta_decide` function** — the outer loop's decision logic (may use
   an LLM, rules, or both).
3. **Inter-stage hooks** (optional) — typed callbacks at `pre_perception`,
   `post_perception`, `pre_belief_update`, `post_belief_update`,
   `pre_decide`, `post_decide`, `pre_act`, `post_act`, and `mode_switch`.

## Status

Stages 0-9 are implemented (see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
for the staged build, and `git log -- orpheus/` for the per-stage commits).
The `perception/` module is incorporated. The reference Orpheus-based agent
lives at [`agents/orpheus_test/`](../agents/orpheus_test/).

Known follow-ups (Stage 2 perception gaps, Stage 4 task `select_action`
approximations, Stage 7 outer-loop staleness, Stage 8 verbose log
categories) are tracked in [`TODO.md`](../TODO.md) and marked
inline in source with `# TODO Stage N follow-up:` /
`# TODO Stage N perception gap:` comments.
