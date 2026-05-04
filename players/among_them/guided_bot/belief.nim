## Belief-state construction and update.
##
## Phase 0: `initBelief` returned a default belief; `updateBelief`
## only bumped the tick. Phase 1.0 extends `updateBelief` to merge a
## `Percept` (from `perception.perceive`) into the long-lived belief,
## specifically the interstitial fields and the derived `GamePhase`.
## Phase 1.3 adds `mergeActorPercept` which copies actor-scan results
## (crewmates, bodies, ghosts, role, self-colour) into the belief.
## Phase 1.4 adds `mergeTaskPercept` which copies task-icon and
## radar-dot scan results into the belief. Phase 1.6 adds
## `mergeVotingPercept` which copies voting-screen parse results.
## See DESIGN.md §4.2 and §15.

import types
import perception
import perception/data
import perception/geometry
import tuning

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
    visibleCrewmates: @[],
    visibleBodies: @[],
    visibleGhosts: @[],
    ghostIconFrames: 0,
    killReady: false,
    visibleTaskIcons: @[],
    radarDots: @[],
    votingValid: false,
    votingCursor: -1,
    votingSelfSlot: -1,
    votingPlayerCount: 0
  )

proc initMemoryState*(): MemoryState =
  result.lastMeetingEndTick = 0
  # Default-constructs the PlayerSummary array.

proc initTaskState*(): TaskState =
  TaskState(slots: @[], inProgressIndex: -1, initialized: false)

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

proc mergeActorPercept*(belief: var Belief, actors: ActorPercept) =
  ## Merge phase-1.3 actor-scan results into the long-lived belief.
  ## Called from `bot.decideNextMask` after the actor scan completes.
  ##
  ## Copies:
  ##   - ``actors.crewmates/bodies/ghosts`` → ``percep.visible*``
  ##   - Role detection → ``self.role`` / ``self.isGhost``
  ##   - Self-colour → ``self.colorIndex``
  ##   - Ghost-icon frame counter → ``percep.ghostIconFrames``
  ##   - Kill-ready flag → ``percep.killReady``
  ##
  ## WakeReason flags: ``WakeBodySeen`` is set when newly-detected
  ## bodies appear (count increases compared to previous frame).

  # Actor lists — replace wholesale each frame.
  belief.percep.visibleCrewmates = actors.crewmates
  belief.percep.visibleBodies = actors.bodies
  belief.percep.visibleGhosts = actors.ghosts

  # Role / ghost detection.
  belief.percep.ghostIconFrames = actors.ghostIconFrames
  belief.percep.killReady = actors.killReady
  if actors.roleUpdated:
    belief.self.role = actors.newRole
  if actors.isGhost:
    belief.self.isGhost = true
    belief.self.alive = false

  # Self-colour detection.
  if actors.selfColorUpdated and actors.newSelfColor >= 0:
    belief.self.colorIndex = actors.newSelfColor

  # Wake-up flag for new bodies.
  if actors.bodies.len > 0:
    belief.flags.wakeReasons.incl WakeBodySeen

proc mergeTaskPercept*(belief: var Belief, taskPercept: TaskPercept) =
  ## Merge phase-1.4 task/radar scan results into the long-lived belief.
  ## Called from `bot.decideNextMask` after the task/radar scan completes.
  ##
  ## Copies:
  ##   - ``taskPercept.taskIcons`` → ``percep.visibleTaskIcons``
  ##   - ``taskPercept.radarDots`` → ``percep.radarDots``
  ##
  ## The higher-level task-state machine (icon→task assignment, checkout
  ## latching, icon-miss pruning) is policy-layer logic for phase 2.
  belief.percep.visibleTaskIcons = taskPercept.taskIcons
  belief.percep.radarDots = taskPercept.radarDots

proc mergeVotingPercept*(belief: var Belief, voting: VotingParse) =
  ## Merge phase-1.6 voting-screen parse results into the belief.
  ## Called from `bot.decideNextMask` after the voting parse completes.
  ##
  ## Copies chat lines into ``social.currentMeetingChat`` (replacing
  ## the previous frame's lines). Phase and interstitial-kind updates
  ## are handled directly in the bot pipeline (they need to gate
  ## voting vs. banner classification).
  if not voting.valid:
    # Clear voting fields when parse fails (frame is not a voting screen).
    belief.percep.votingValid = false
    belief.percep.votingCursor = -1
    belief.percep.votingSelfSlot = -1
    belief.percep.votingPlayerCount = 0
    return
  # Copy voting parse results into perception state.
  belief.percep.votingValid = true
  belief.percep.votingCursor = voting.cursor
  belief.percep.votingSelfSlot = voting.selfSlot
  belief.percep.votingPlayerCount = voting.playerCount
  belief.social.currentMeetingChat = @[]
  for cl in voting.chatLines:
    belief.social.currentMeetingChat.add ChatLine(
      tick: belief.tick,
      speakerColor: cl.speakerColor,
      text: cl.text)
  # Flag for the guidance loop.
  if voting.chatLines.len > 0:
    belief.flags.wakeReasons.incl WakeChatObserved

# ---------------------------------------------------------------------------
# Task-state machine (phase 6.1)
# ---------------------------------------------------------------------------

proc ensureTaskSlotsInitialized*(belief: var Belief) =
  ## Lazily allocate ``belief.tasks.slots`` to match the map's task
  ## station count. Called once on the first gameplay frame.
  if belief.tasks.initialized:
    return
  let n = referenceData.map.tasks.len
  belief.tasks.slots = newSeq[TaskSlot](n)
  for i in 0 ..< n:
    belief.tasks.slots[i] = TaskSlot(
      state: TaskNotDoing,
      checkout: false,
      iconVisibleTick: -1,
      iconMissCount: 0,
      resolvedNotMine: false)
  belief.tasks.initialized = true

proc resetTaskSlots*(belief: var Belief) =
  ## Reset all task slots to initial state. Called on round reset
  ## (role-reveal interstitial).
  for i in 0 ..< belief.tasks.slots.len:
    belief.tasks.slots[i] = TaskSlot(
      state: TaskNotDoing,
      checkout: false,
      iconVisibleTick: -1,
      iconMissCount: 0,
      resolvedNotMine: false)
  belief.tasks.inProgressIndex = -1

proc findIconForStation(stationIdx: int, station: TaskStation,
                        icons: openArray[IconMatch],
                        camX, camY: int): bool =
  ## True if any visible task icon matches the given station. Reuses
  ## the same matching logic as ``task_completing.findTaskForIcon``:
  ## the icon's world position must fall within the station rect
  ## (16 px margin).
  const margin = 16
  for icon in icons:
    let wx = camX + icon.x + SpriteDrawOffX
    let wy = camY + icon.y + SpriteDrawOffY
    if wx >= station.x - margin and wx < station.x + station.w + margin and
       wy >= station.y - margin and wy < station.y + station.h + margin:
      return true
  false

proc updateTaskState*(belief: var Belief, tick: int,
                      holdIndex: int, confirmIndex: int) =
  ## Per-frame task-state update. Runs in the belief-merge stage
  ## (after ``mergeTaskPercept``). Implements TASK_COMPLETING_DESIGN.md
  ## §4.2 and §5 (radar checkout).
  ##
  ## ``holdIndex`` and ``confirmIndex`` are the task indices currently
  ## being held or confirmed by ``task_completing`` mode (-1 if none).
  ## These are excluded from negative-evidence pruning.
  if not belief.tasks.initialized:
    return
  if belief.percep.interstitial:
    return

  let tasks = referenceData.map.tasks
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  let localized = belief.percep.localized
  let isAliveImposter = belief.self.role == RoleImposter and
                        belief.self.alive and not belief.self.isGhost

  for i in 0 ..< tasks.len:
    if i >= belief.tasks.slots.len:
      break
    # Skip terminal states.
    if belief.tasks.slots[i].state == TaskCompleted:
      continue
    if belief.tasks.slots[i].resolvedNotMine:
      continue

    let station = tasks[i]

    # --- Icon visibility check (skip for alive imposters) ---
    if not isAliveImposter and localized:
      let iconVisible = findIconForStation(i, station,
                                           belief.percep.visibleTaskIcons,
                                           camX, camY)
      if iconVisible:
        belief.tasks.slots[i].state = TaskConfirmed
        belief.tasks.slots[i].iconVisibleTick = tick
        belief.tasks.slots[i].iconMissCount = 0
      else:
        # Only count misses when the icon area is fully on-screen.
        if taskIconOnScreen(station, camX, camY, TaskClearScreenMargin):
          belief.tasks.slots[i].iconMissCount += 1
          # Negative evidence: 24 frames of clear sight, no icon.
          if belief.tasks.slots[i].iconMissCount >= TaskIconMissResolveFrames and
             i != holdIndex and i != confirmIndex:
            belief.tasks.slots[i].resolvedNotMine = true
            belief.tasks.slots[i].checkout = false
            belief.tasks.slots[i].state = TaskNotDoing
        # else: off-screen or near edge — don't count.

    # --- Radar-dot checkout (needs camera for projection) ---
    if localized:
      let (projX, projY) = projectedRadarDot(station, camX, camY)
      var matched = false
      for dot in belief.percep.radarDots:
        if abs(dot.x - projX) <= RadarMatchTolerance and
           abs(dot.y - projY) <= RadarMatchTolerance:
          matched = true
          break
      if matched:
        belief.tasks.slots[i].checkout = true
        if belief.tasks.slots[i].state == TaskNotDoing:
          belief.tasks.slots[i].state = TaskCheckout
