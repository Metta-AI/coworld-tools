## Belief-state construction and update (phase 0 stub).
##
## Phase 0: `initBelief` returns a sane default belief; `updateBelief` is
## a no-op. The real merging of percepts into the long-lived belief, and
## the maintenance of `memory` / `tasks` / `social`, lives here in phase
## 1+. See DESIGN.md §3 and §4.2.

import types

proc initDirective*(): Directive =
  Directive(
    mode: ModeIdle,
    params: ModeParams(mode: ModeIdle,
                       idleLingerValid: false,
                       idleNearGroup: false),
    source: SourceDefault,
    issuedAtTick: 0,
    ttlTicks: 0,
    reflexName: "",
    reasoning: ""
  )

proc initSelfState*(): SelfState =
  SelfState(
    role: RoleUnknown,
    colorIndex: -1,
    isGhost: false,
    alive: true,
    killCooldownRemaining: 0,
    knownImposterColors: @[],
    homeSet: false,
    phase: PhaseUnknown
  )

proc initPerceptionState*(): PerceptionState =
  PerceptionState(
    cameraX: 0, cameraY: 0,
    localized: false,
    selfX: 0, selfY: 0,
    visiblePlayers: @[],
    visibleBodies: @[],
    visibleTaskIcons: @[],
    interstitialText: ""
  )

proc initMemoryState*(): MemoryState =
  result.lastMeetingEndTick = 0
  # Default-constructs the PlayerSummary array.

proc initTaskState*(): TaskState =
  TaskState(slots: @[], inProgressIndex: -1)

proc initSocialState*(): SocialState =
  result.recentChat = @[]
  result.currentMeetingChat = @[]
  for i in 0 ..< PlayerColorCount:
    result.votesCast[i] = -2    ## -2 = abstain (no vote yet).

proc initBelief*(): Belief =
  Belief(
    tick: 0,
    self: initSelfState(),
    percep: initPerceptionState(),
    memory: initMemoryState(),
    tasks: initTaskState(),
    social: initSocialState(),
    directive: initDirective(),
    flags: FlagState(wakeReasons: {}, newDirectiveAvailable: false)
  )

proc updateBelief*(belief: var Belief, frame: openArray[uint8]) =
  ## Phase 0: advance the tick counter. Phase 1 wires in perception merge,
  ## memory maintenance, directive-slot read, and reflex-condition
  ## evaluation (see DESIGN.md §4.2).
  discard frame
  inc belief.tick
