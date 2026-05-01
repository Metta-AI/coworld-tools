## Action layer (phase 0 stub).
##
## Translates `ActionIntent` values from modes into the game-protocol
## button mask. Owns the persistent tactical state (`ActionState`) that
## survives across ticks: current A* path, motion model, jiggle counters,
## last emitted mask, task-hold discipline. See DESIGN.md §4.4 and §6.
##
## Phase 0: `applyIntent` returns 0 (no-op) regardless of input, and does
## not update `ActionState`. Phase 2 wires in A*, momentum-aware steering,
## jiggle, and edge-triggered cursor/button handling. The signature here
## is final; mode handlers can already produce real intents without the
## action layer being done.

import types
# `constants` is pulled in transitively via `types` (it re-exports it).
# Phase 2 uses `ButtonUp`/`ButtonDown`/etc. here directly.

proc initActionState*(): ActionState =
  ActionState(
    currentPath: @[],
    currentGoalValid: false,
    lastEmittedMask: 0'u8,
    lastVelocityX: 0, lastVelocityY: 0,
    stuckFrames: 0,
    jiggleTicks: 0,
    taskHoldTicks: 0
  )

proc initActionIntent*(): ActionIntent =
  ActionIntent(
    steerValid: false,
    pressA: false,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineNoOp
  )

proc noOpIntent*(): ActionIntent = initActionIntent()

proc applyIntent*(
    state: var ActionState,
    belief: Belief,
    intent: ActionIntent): uint8 =
  ## Phase 0: always no-op. Phase 2 does the real work:
  ##   - `DisciplineTaskHold`  -> hold ButtonA alone, zero motion.
  ##   - `DisciplineKillStrike`-> drive toward intent.steerTo + ButtonA on
  ##                              contact.
  ##   - `DisciplineReport`    -> drive toward intent.steerTo + ButtonA in
  ##                              report range.
  ##   - `DisciplineNormal`    -> A* + momentum steering toward steerTo.
  ##   - `DisciplineNoOp`      -> hold mask 0.
  ## Meeting-mode cursor movement and chat emission also funnel through
  ## here (DESIGN.md §7).
  discard belief
  discard intent
  state.lastEmittedMask = 0'u8
  0'u8

proc emitChat*(state: var ActionState, text: string): bool =
  ## Phase 0: drops the chat line. Phase 2: queues it for emission once
  ## the voting phase begins, rate-limited by `MeetingChatLineGapTicks`.
  discard state
  discard text
  false
