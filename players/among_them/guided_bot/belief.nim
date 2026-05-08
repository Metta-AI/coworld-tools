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
  # Initialize all players as alive with unknown role.
  for i in 0 ..< PlayerColorCount:
    result.perPlayer[i].alive = true
    result.perPlayer[i].role = RoleUnknown

proc initTaskState*(): TaskState =
  TaskState(slots: @[],
            inProgressIndex: -1,
            initialized: false,
            pipGraceTicks: 0,
            prevRadarDotCount: 0)

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
  ##   - Per-player memory updates (last seen, alive status)
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

  # --- Per-player memory maintenance ---
  # Update last-seen positions from visible crewmates (requires localization).
  if belief.percep.localized:
    let camX = belief.percep.cameraX
    let camY = belief.percep.cameraY
    for cm in actors.crewmates:
      let ci = cm.colorIndex
      if ci >= 0 and ci < PlayerColorCount:
        belief.memory.perPlayer[ci].lastSeenTick = belief.tick
        belief.memory.perPlayer[ci].lastSeenX =
          visibleCrewmateWorldX(camX, cm.x)
        belief.memory.perPlayer[ci].lastSeenY =
          visibleCrewmateWorldY(camY, cm.y)

  # Mark players dead when their body is spotted.
  for body in actors.bodies:
    let ci = body.colorIndex
    if ci >= 0 and ci < PlayerColorCount:
      belief.memory.perPlayer[ci].alive = false

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

const CheckoutDecayFrames* = 8

proc updateCheckoutDecay(slot: var TaskSlot) =
  if slot.radarRayExcluded:
    slot.radarExcludedStreak += 1
    if slot.radarExcludedStreak >= CheckoutDecayFrames and slot.checkout:
      slot.checkout = false
      if slot.state == TaskCheckout:
        slot.state = TaskNotDoing
  else:
    slot.radarExcludedStreak = 0

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
      resolvedNotMine: false,
      radarRayExcluded: false,
      radarExcludedStreak: 0)
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
      resolvedNotMine: false,
      radarRayExcluded: false,
      radarExcludedStreak: 0)
  belief.tasks.inProgressIndex = -1
  belief.tasks.pipGraceTicks = 0
  belief.tasks.prevRadarDotCount = 0

proc findIconForStation(stationIdx: int, station: TaskStation,
                        icons: openArray[IconMatch],
                        camX, camY: int): bool =
  ## True if any visible task icon matches the given station.
  ## Task icons render at a fixed screen-space offset from the station
  ## rect; match that exact expected top-left rather than an expanded
  ## station rect, because nearby task-station rects can overlap.
  const tolerance = 2
  let expectedX = station.x + station.w div 2 - SpriteSize div 2 - camX
  let expectedY = station.y - SpriteSize - 2 - camY
  for icon in icons:
    if abs(icon.x - expectedX) <= tolerance and
       abs(icon.y - expectedY) <= tolerance:
      return true
  false

proc updateTaskState*(belief: var Belief, tick: int,
                      holdIndex: int, confirmIndex: int) =
  ## Per-frame task-state update. Runs in the belief-merge stage
  ## (after ``mergeTaskPercept``). Implements TASK_COMPLETING_DESIGN.md
  ## §4.2 and §5 (radar checkout).
  ##
  ## ``holdIndex`` and ``confirmIndex`` are optional task indices to
  ## exclude from negative-evidence pruning (-1 if none). The live
  ## ``task_completing`` pipeline intentionally passes -1 for Hold so
  ## missing icons during the A-press can prune wrong targets; Confirm
  ## stays shielded because icon absence is the completion signal.
  if not belief.tasks.initialized:
    return
  if belief.percep.interstitial:
    return

  let currentRadarDotCount = belief.percep.radarDots.len
  if belief.tasks.pipGraceTicks > 0:
    belief.tasks.pipGraceTicks -= 1
  if currentRadarDotCount < belief.tasks.prevRadarDotCount and
     currentRadarDotCount == 0:
    belief.tasks.pipGraceTicks = PipDisappearGraceTicks
  belief.tasks.prevRadarDotCount = currentRadarDotCount

  let tasks = referenceData.map.tasks
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  let localized = belief.percep.localized
  let isAliveImposter = belief.self.role == RoleImposter and
                        belief.self.alive and not belief.self.isGhost

  for i in 0 ..< tasks.len:
    if i >= belief.tasks.slots.len:
      break
    belief.tasks.slots[i].radarRayExcluded = false
    # Skip terminal states.
    if belief.tasks.slots[i].state == TaskCompleted:
      belief.tasks.slots[i].radarExcludedStreak = 0
      continue
    if belief.tasks.slots[i].resolvedNotMine:
      belief.tasks.slots[i].radarExcludedStreak = 0
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
        if taskIconOnScreen(station, camX, camY, TaskClearScreenMargin) and
           belief.tasks.pipGraceTicks <= 0:
          belief.tasks.slots[i].iconMissCount += 1
          # Negative evidence: enough clear-sight frames with no icon.
          if belief.tasks.slots[i].iconMissCount >= TaskIconMissResolveFrames and
             i != holdIndex and i != confirmIndex:
            belief.tasks.slots[i].resolvedNotMine = true
            belief.tasks.slots[i].checkout = false
            belief.tasks.slots[i].state = TaskNotDoing
        # else: off-screen or near edge — don't count.

    if localized:
      let selfX = belief.percep.selfX
      let selfY = belief.percep.selfY

      # --- Per-frame radar-ray exclusion ---
      # Cast rays from player through each pip; flag off-screen tasks
      # whose icon AABB is not intersected by any ray.
      if not isAliveImposter:
        let offScreen = not taskIconOnScreen(station, camX, camY, 0)
        if offScreen and belief.percep.radarDots.len >= RadarRayMinPips:
          var hitByAnyRay = false
          let playerSx = selfX - camX
          let playerSy = selfY - camY
          for dot in belief.percep.radarDots:
            let dirX = dot.x - playerSx
            let dirY = dot.y - playerSy
            if rayIntersectsIconAABB(selfX, selfY, dirX, dirY,
                                     station, RadarRayIconPadding):
              hitByAnyRay = true
              break
          belief.tasks.slots[i].radarRayExcluded = not hitByAnyRay
        else:
          belief.tasks.slots[i].radarRayExcluded = false
      else:
        belief.tasks.slots[i].radarRayExcluded = false

      updateCheckoutDecay(belief.tasks.slots[i])

      # --- Radar-dot checkout (needs camera for projection) ---
      let (projX, projY) = projectedRadarDot(station, camX, camY,
                                             selfX, selfY)
      var matched = false
      for dot in belief.percep.radarDots:
        if abs(dot.x - projX) <= RadarMatchTolerance and
           abs(dot.y - projY) <= RadarMatchTolerance:
          matched = true
          break
      if matched and not belief.tasks.slots[i].radarRayExcluded:
        belief.tasks.slots[i].checkout = true
        belief.tasks.slots[i].radarExcludedStreak = 0
        if belief.tasks.slots[i].state == TaskNotDoing:
          belief.tasks.slots[i].state = TaskCheckout
    else:
      belief.tasks.slots[i].radarRayExcluded = false
      updateCheckoutDecay(belief.tasks.slots[i])
