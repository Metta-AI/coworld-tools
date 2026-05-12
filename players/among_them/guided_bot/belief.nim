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
import navigation
import perception
import perception/data
import perception/geometry
import tuning

const RecentChatLimit = 24

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
    failedKillCounts: [0, 0, 0, 0, 0, 0, 0, 0],
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
    killIconFrames: 0,
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
    result.perPlayer[i].lastSeenTick = -1000000
    result.perPlayer[i].lastNearBodyTick = -1000000
    result.perPlayer[i].lastNearBodyDistance = -1
    result.perPlayer[i].closestNearBodyDistance = -1
    result.perPlayer[i].lastVentTick = -1000000
    result.perPlayer[i].lastNearVentTick = -1000000
    result.perPlayer[i].lastNearVentDistance = -1
    result.perPlayer[i].lastSoloWithSelfTick = -1

proc initTaskState*(): TaskState =
  TaskState(slots: @[],
            inProgressIndex: -1,
            initialized: false,
            pipGraceTicks: 0,
            prevRadarDotCount: 0)

proc initSocialState*(): SocialState =
  result.recentChat = @[]
  result.currentMeetingChat = @[]
  result.pendingChatObserved = @[]
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

proc nearBodyEvidenceStrength(dist: int): int =
  ## Body proximity is ambiguous evidence, but closeness matters. A player
  ## standing on the body is more suspicious than one near the edge of the
  ## same screen.
  if dist >= MeetingBodyEvidenceRadius:
    return 1
  1 + ((MeetingBodyEvidenceRadius - dist) *
       (MeetingBodyEvidenceMaxStrength - 1)) div MeetingBodyEvidenceRadius

proc playerSpriteAtWorldFullyOnScreen(cameraX, cameraY, x, y: int): bool =
  let sx = x - cameraX - SpriteDrawOffX
  let sy = y - cameraY - SpriteDrawOffY
  sx >= VentWitnessViewMargin and
    sx <= ScreenWidth - SpriteSize - VentWitnessViewMargin and
    sy >= VentWitnessViewMargin and
    sy <= ScreenHeight - SpriteSize - VentWitnessViewMargin

proc nearestVentAt(
    x, y, maxRadius: int): tuple[found: bool, vent: Waypoint, dist: int] =
  let graph = navGraph()[]
  var bestDist = high(int)
  var bestVent: Waypoint
  for wp in graph.waypoints:
    if wp.kind != WpVent:
      continue
    let dist = max(abs(x - wp.x), abs(y - wp.y))
    if dist < bestDist:
      bestDist = dist
      bestVent = wp
  if bestDist <= maxRadius:
    (true, bestVent, bestDist)
  else:
    (false, bestVent, bestDist)

proc previousFrameHadPlayerOnVent(belief: Belief, vent: Waypoint): bool =
  for cm in belief.percep.visibleCrewmates:
    let px = visibleCrewmateWorldX(belief.percep.lastCameraX, cm.x)
    let py = visibleCrewmateWorldY(belief.percep.lastCameraY, cm.y)
    if max(abs(px - vent.x), abs(py - vent.y)) <= VentWitnessRadius:
      return true
  false

proc recentlySeenNearVent(belief: Belief, color: int, vent: Waypoint): bool =
  if color < 0 or color >= PlayerColorCount:
    return false
  let ps = belief.memory.perPlayer[color]
  let age = belief.tick - ps.lastSeenTick
  if age < 0 or age > VentWitnessRecentSeenTicks:
    return false
  max(abs(ps.lastSeenX - vent.x), abs(ps.lastSeenY - vent.y)) <=
    VentWitnessRecentSeenRadius

proc recentlyRecordedVentWitness(
    belief: Belief, color: int, vent: Waypoint): bool =
  if color < 0 or color >= PlayerColorCount:
    return false
  let ps = belief.memory.perPlayer[color]
  let age = belief.tick - ps.lastVentTick
  if age < 0 or age > VentWitnessRepeatCooldownTicks:
    return false
  ps.lastVentLabel == vent.label

proc recentlyRecordedVentSuspicion(
    belief: Belief, color: int, vent: Waypoint): bool =
  if color < 0 or color >= PlayerColorCount:
    return false
  let ps = belief.memory.perPlayer[color]
  let age = belief.tick - ps.lastNearVentTick
  if age < 0 or age > VentSuspicionRepeatCooldownTicks:
    return false
  ps.lastNearVentLabel == vent.label

proc ventSuspicionProbabilityPct(dist: int, selfOccluded: bool): int =
  let clampedDist = max(0, min(dist, VentSuspicionRadius))
  result = VentSuspicionMinProbabilityPct +
    ((VentSuspicionRadius - clampedDist) *
     (VentSuspicionMaxProbabilityPct - VentSuspicionMinProbabilityPct)) div
      VentSuspicionRadius
  if selfOccluded:
    result = max(VentSuspicionMinProbabilityPct, result div 2)

proc rememberKnownImposterColor*(belief: var Belief, color: int): bool

proc recordVentWitness(belief: var Belief, color: int, vent: Waypoint) =
  if color < 0 or color >= PlayerColorCount:
    return
  if belief.self.colorIndex >= 0 and color == belief.self.colorIndex:
    return
  inc belief.memory.perPlayer[color].timesWitnessedVent
  belief.memory.perPlayer[color].lastVentTick = belief.tick
  belief.memory.perPlayer[color].lastVentX = vent.x
  belief.memory.perPlayer[color].lastVentY = vent.y
  belief.memory.perPlayer[color].lastVentLabel = vent.label
  discard rememberKnownImposterColor(belief, color)

proc recordVentSuspicion(
    belief: var Belief, color: int, vent: Waypoint, dist: int,
    probabilityPct: int) =
  if color < 0 or color >= PlayerColorCount:
    return
  if belief.self.colorIndex >= 0 and color == belief.self.colorIndex:
    return
  inc belief.memory.perPlayer[color].timesNearVentAppearance
  belief.memory.perPlayer[color].nearVentEvidenceScore +=
    max(1, probabilityPct div 10)
  belief.memory.perPlayer[color].lastNearVentTick = belief.tick
  belief.memory.perPlayer[color].lastNearVentX = vent.x
  belief.memory.perPlayer[color].lastNearVentY = vent.y
  belief.memory.perPlayer[color].lastNearVentDistance = dist
  belief.memory.perPlayer[color].lastNearVentProbabilityPct = probabilityPct
  belief.memory.perPlayer[color].lastNearVentLabel = vent.label

proc updateVentWitnessEvidence(belief: var Belief, actors: ActorPercept) =
  ## Venting is hard role evidence only when the previous frame had a clear,
  ## empty view and the current frame shows the player directly on the vent.
  ## Looser first sightings near a vent become probabilistic suspicion.
  if belief.self.role == RoleImposter:
    return
  if not belief.percep.localized:
    return
  let currentCamX = belief.percep.cameraX
  let currentCamY = belief.percep.cameraY
  let previousCamX = belief.percep.lastCameraX
  let previousCamY = belief.percep.lastCameraY
  for cm in actors.crewmates:
    let ci = cm.colorIndex
    if ci < 0 or ci >= PlayerColorCount:
      continue
    if ci == belief.self.colorIndex:
      continue
    if belief.memory.perPlayer[ci].lastSeenTick == belief.tick - 1:
      continue
    let px = visibleCrewmateWorldX(currentCamX, cm.x)
    let py = visibleCrewmateWorldY(currentCamY, cm.y)
    let ventHit = nearestVentAt(px, py, VentSuspicionRadius)
    if not ventHit.found:
      continue
    if previousFrameHadPlayerOnVent(belief, ventHit.vent):
      continue
    if recentlySeenNearVent(belief, ci, ventHit.vent):
      continue

    let selfOccluded =
      max(abs(px - belief.percep.selfX), abs(py - belief.percep.selfY)) <
        VentWitnessMinSelfDistance
    let previousClear =
      playerSpriteAtWorldFullyOnScreen(previousCamX, previousCamY, px, py)
    let currentClear =
      playerSpriteAtWorldFullyOnScreen(currentCamX, currentCamY, px, py)
    let hardWitness =
      ventHit.dist <= VentWitnessRadius and previousClear and currentClear and
      not selfOccluded and not recentlyRecordedVentWitness(belief, ci, ventHit.vent)
    if hardWitness:
      recordVentWitness(belief, ci, ventHit.vent)
      continue

    if recentlyRecordedVentSuspicion(belief, ci, ventHit.vent):
      continue
    recordVentSuspicion(
      belief, ci, ventHit.vent, ventHit.dist,
      ventSuspicionProbabilityPct(ventHit.dist, selfOccluded))

proc updateSoloTrust(belief: var Belief, actors: ActorPercept) =
  ## If a crewmate spends time alone with exactly one visible player and
  ## survives, that becomes direct trust evidence for that player. The
  ## current streak resets aggressively when the scene stops being a clean
  ## one-on-one; the total remains as cross-meeting memory.
  var soleOther = -1
  var otherCount = 0
  if belief.self.role != RoleImposter and
     belief.self.alive and
     not belief.self.isGhost and
     belief.self.phase == PhaseGameplay and
     belief.percep.localized and
     actors.bodies.len == 0:
    for cm in actors.crewmates:
      let ci = cm.colorIndex
      if ci < 0 or ci >= PlayerColorCount:
        continue
      if ci == belief.self.colorIndex:
        continue
      if not belief.memory.perPlayer[ci].alive:
        continue
      soleOther = ci
      inc otherCount

  if otherCount == 1 and soleOther >= 0:
    for i in 0 ..< PlayerColorCount:
      if i != soleOther:
        belief.memory.perPlayer[i].currentSoloWithSelfTicks = 0
    let gap =
      if belief.memory.perPlayer[soleOther].lastSoloWithSelfTick >= 0:
        belief.tick - belief.memory.perPlayer[soleOther].lastSoloWithSelfTick
      else:
        1
    let delta = max(1, min(gap, 3))
    if belief.memory.perPlayer[soleOther].lastSoloWithSelfTick >= 0 and
       gap <= 3:
      belief.memory.perPlayer[soleOther].currentSoloWithSelfTicks += delta
    else:
      belief.memory.perPlayer[soleOther].currentSoloWithSelfTicks = delta
    belief.memory.perPlayer[soleOther].soloWithSelfTicks += delta
    belief.memory.perPlayer[soleOther].lastSoloWithSelfTick = belief.tick
  else:
    for i in 0 ..< PlayerColorCount:
      belief.memory.perPlayer[i].currentSoloWithSelfTicks = 0

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

  # Role / ghost detection.
  belief.percep.ghostIconFrames = actors.ghostIconFrames
  belief.percep.killIconFrames = actors.killIconFrames
  belief.percep.killReady = actors.killReady
  if actors.roleUpdated:
    belief.self.role = actors.newRole
  if actors.isGhost:
    belief.self.isGhost = true
    belief.self.alive = false

  # Self-colour detection.
  if actors.selfColorUpdated and actors.newSelfColor >= 0:
    if belief.self.colorIndex < 0 or belief.self.colorIndex == actors.newSelfColor:
      belief.self.colorIndex = actors.newSelfColor

  # Must run before visibleCrewmates is replaced: it compares the current
  # actor scan against the previous frame's visible actors.
  updateVentWitnessEvidence(belief, actors)

  # Actor lists — replace wholesale each frame.
  belief.percep.visibleCrewmates = actors.crewmates
  belief.percep.visibleBodies = actors.bodies
  belief.percep.visibleGhosts = actors.ghosts

  updateSoloTrust(belief, actors)

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

  # Suspicion evidence: visible players repeatedly near visible bodies.
  # Cooldown keeps a single lingering frame sequence from becoming many
  # independent "times".
  if belief.percep.localized and actors.bodies.len > 0 and actors.crewmates.len > 0:
    let camX = belief.percep.cameraX
    let camY = belief.percep.cameraY
    for body in actors.bodies:
      let bx = visibleCrewmateWorldX(camX, body.x)
      let by = visibleCrewmateWorldY(camY, body.y)
      for cm in actors.crewmates:
        let ci = cm.colorIndex
        if ci < 0 or ci >= PlayerColorCount:
          continue
        if ci == belief.self.colorIndex or ci == body.colorIndex:
          continue
        let px = visibleCrewmateWorldX(camX, cm.x)
        let py = visibleCrewmateWorldY(camY, cm.y)
        let dist = abs(px - bx) + abs(py - by)
        if dist <= MeetingBodyEvidenceRadius and
           belief.tick - belief.memory.perPlayer[ci].lastNearBodyTick >=
             MeetingBodyEvidenceCooldownTicks:
          inc belief.memory.perPlayer[ci].timesNearBody
          belief.memory.perPlayer[ci].lastNearBodyTick = belief.tick
          belief.memory.perPlayer[ci].lastNearBodyDistance = dist
          if belief.memory.perPlayer[ci].closestNearBodyDistance < 0 or
             dist < belief.memory.perPlayer[ci].closestNearBodyDistance:
            belief.memory.perPlayer[ci].closestNearBodyDistance = dist
          belief.memory.perPlayer[ci].nearBodyEvidenceScore +=
            nearBodyEvidenceStrength(dist)

proc rememberKnownImposterColor*(belief: var Belief, color: int): bool =
  ## Add one imposter colour to long-lived belief and per-player memory.
  ## Returns true only when the public known-imposter list grew.
  if color < 0 or color >= PlayerColorCount:
    return false
  belief.memory.perPlayer[color].role = RoleImposter
  if belief.self.colorIndex >= 0 and color == belief.self.colorIndex:
    return false
  if color in belief.self.knownImposterColors:
    return false
  belief.self.knownImposterColors.add color
  true

proc recordFailedKillSuspect*(belief: var Belief, color: int):
    tuple[count: int, promoted: bool] =
  ## A close-range strike that leaves killReady lit and produces no body is
  ## evidence that the target is a teammate. Promote after repeated evidence.
  if color < 0 or color >= PlayerColorCount:
    return (0, false)
  if belief.self.colorIndex >= 0 and color == belief.self.colorIndex:
    return (0, false)
  inc belief.self.failedKillCounts[color]
  result.count = belief.self.failedKillCounts[color]
  if result.count >= FailedKillImposterConfirmStrikes:
    result.promoted = rememberKnownImposterColor(belief, color)

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
  ## the previous frame's lines) and appends newly-observed lines to
  ## ``social.recentChat`` / ``social.pendingChatObserved``. Phase and
  ## interstitial-kind updates are handled directly in the bot pipeline
  ## (they need to gate voting vs. banner classification).
  belief.social.pendingChatObserved = @[]
  if not voting.valid:
    # Clear voting fields when parse fails (frame is not a voting screen).
    belief.percep.votingValid = false
    belief.percep.votingCursor = -1
    belief.percep.votingSelfSlot = -1
    belief.percep.votingPlayerCount = 0
    belief.social.currentMeetingChat = @[]
    return
  # Copy voting parse results into perception state.
  belief.percep.votingValid = true
  belief.percep.votingCursor = voting.cursor
  belief.percep.votingSelfSlot = voting.selfSlot
  belief.percep.votingPlayerCount = voting.playerCount
  for i in 0 ..< voting.playerCount:
    let ci = voting.slots[i].colorIndex
    if ci >= 0 and ci < PlayerColorCount:
      belief.memory.perPlayer[ci].alive = voting.slots[i].alive
  for voter in 0 ..< PlayerColorCount:
    let choice = voting.choices[voter]
    if choice == voting.playerCount:
      belief.social.votesCast[voter] = -1
    elif choice >= 0 and choice < voting.playerCount:
      let targetColor = voting.slots[choice].colorIndex
      if targetColor >= 0 and targetColor < PlayerColorCount:
        belief.social.votesCast[voter] = targetColor
  if voting.selfSlot >= 0 and voting.selfSlot < voting.playerCount:
    let selfColor = voting.slots[voting.selfSlot].colorIndex
    if selfColor >= 0 and selfColor < PlayerColorCount and
       (belief.self.colorIndex < 0 or belief.self.colorIndex == selfColor):
      belief.self.colorIndex = selfColor
      belief.self.alive = voting.slots[voting.selfSlot].alive
  belief.social.currentMeetingChat = @[]
  for cl in voting.chatLines:
    let line = ChatLine(
      tick: belief.tick,
      speakerColor: cl.speakerColor,
      text: cl.text)
    belief.social.currentMeetingChat.add line
    var alreadyKnown = false
    let start = max(0, belief.social.recentChat.len - RecentChatLimit)
    for i in start ..< belief.social.recentChat.len:
      let old = belief.social.recentChat[i]
      if old.speakerColor == line.speakerColor and old.text == line.text:
        alreadyKnown = true
        break
    if not alreadyKnown:
      belief.social.recentChat.add line
      if belief.social.recentChat.len > RecentChatLimit:
        belief.social.recentChat.delete(0)
      belief.social.pendingChatObserved.add line
  # Flag for the guidance loop.
  if belief.social.pendingChatObserved.len > 0:
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
