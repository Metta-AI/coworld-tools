## Belief-state construction and update.
##
## Phase 0: `initBelief` returned a default belief; `updateBelief`
## only bumped the tick. Phase 1.0 extends `updateBelief` to merge a
## `Percept` (from `perception.perceive`) into the long-lived belief,
## specifically the interstitial fields and the derived `GamePhase`.
## Later sub-phases merge more: camera/self-position (1.2), visible
## actors (1.3), task state (1.4), voting/chat (1.6). See DESIGN.md
## §4.2 and §15.

import types
import perception

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
    phase: PhaseUnknown
  )

proc initPerceptionState*(): PerceptionState =
  PerceptionState(
    cameraX: 0, cameraY: 0,
    lastCameraX: 0, lastCameraY: 0,
    cameraScore: 0,
    cameraLock: NoLock,
    localized: false,
    lastLocalizedTick: -1,
    selfX: 0, selfY: 0,
    homeX: 0, homeY: 0,
    homeSet: false,
    gameStarted: false,
    interstitial: false,
    interstitialKind: NotInterstitial,
    blackPixelCount: 0,
    interstitialText: "",
    visiblePlayers: @[],
    visibleBodies: @[],
    visibleTaskIcons: @[]
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

proc mergePercept*(belief: var Belief, percept: Percept) =
  ## Merge a freshly-observed percept into the long-lived belief.
  ## Phase 1.0 merges:
  ##   - Interstitial observation → `percep.interstitial{,Kind}`,
  ##     `percep.blackPixelCount`.
  ##   - Derived `GamePhase` → `self.phase` (via
  ##     `interstitial.phaseFromInterstitial` so voting-phase
  ##     persistence works once phase 1.5 lets us enter voting).
  ##   - `WakeMeetingStarted` flag when we cross from non-voting into
  ##     a voting interstitial. Phase 1.5 tightens this by only
  ##     firing on the actual voting-screen kind, not just any black
  ##     interstitial; for phase 1.0 every interstitial-start sets the
  ##     flag and the LLM sees the ambiguity.
  belief.percep.interstitial      = percept.interstitial.isInterstitial
  belief.percep.interstitialKind  = percept.interstitial.kind
  belief.percep.blackPixelCount   = percept.interstitial.blackPixelCount

  let newPhase = phaseFromInterstitial(belief.self.phase, percept.interstitial)
  let enteringInterstitial =
    newPhase == PhaseInterstitial and belief.self.phase != PhaseInterstitial
  belief.self.phase = newPhase

  if enteringInterstitial:
    belief.flags.wakeReasons.incl WakeMeetingStarted

proc updateBelief*(belief: var Belief, percept: Percept) =
  ## Advance the belief by one tick by consuming a fresh percept.
  ##
  ## The caller is expected to have already bumped `percept.tick`
  ## (typically from `bot.frameTick`) — we adopt that value as
  ## `belief.tick` so there is a single source of tick truth in the
  ## bot.
  ##
  ## Phase 1.0: set tick, merge interstitial observation. Later
  ## sub-phases add memory maintenance (sightings / body / meeting
  ## logs — phase 1.3+), task-state transitions (phase 1.4), directive-
  ## slot reads from the guidance channel (phase 3), and reflex
  ## evaluation (phase 2).
  belief.tick = percept.tick
  mergePercept(belief, percept)
