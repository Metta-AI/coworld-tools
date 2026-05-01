## Reflex evaluation — forced mode switches that fire without waiting
## for the LLM. See DESIGN.md §5.8.
##
## Reflexes are edge-triggered (fire on transitions, not persistent
## state) and subject to a per-reflex cooldown to prevent thrashing.
## They are evaluated in the update-belief stage so the target mode's
## `decide()` runs on the same tick as the triggering event.
##
## The initial reflex set (DESIGN.md §5.8):
##   1. task_completing (crew, alive) + body_newly_in_view → reporting
##   2. hunting + body_newly_in_view (didn't kill) → fleeing
##   3. pretending + lone_crew_in_kill_range → hunting
##   4. any mode + voting_screen_appeared → meeting

import types
import tuning
import perception/geometry

# ---------------------------------------------------------------------------
# Reflex state — tracks cooldowns and edge-trigger memory
# ---------------------------------------------------------------------------

type
  ReflexState* = object
    ## Per-reflex cooldown timers (tick of last firing).
    lastBodyReportTick*: int
    lastBodyFleeTick*: int
    lastOpportunisticKillTick*: int
    lastVotingTick*: int
    ## Edge-trigger memory: previous frame's values.
    prevBodyCount*: int
    prevPhase*: GamePhase

proc initReflexState*(): ReflexState =
  ReflexState(
    lastBodyReportTick: -1000,
    lastBodyFleeTick: -1000,
    lastOpportunisticKillTick: -1000,
    lastVotingTick: -1000,
    prevBodyCount: 0,
    prevPhase: PhaseUnknown
  )

# ---------------------------------------------------------------------------
# Reflex evaluation
# ---------------------------------------------------------------------------

type
  ReflexResult* = object
    ## If `fired` is true, the caller should install `newDirective`
    ## and perform a mode switch.
    fired*: bool
    newDirective*: Directive
    reflexName*: string

proc evaluateReflexes*(belief: Belief, reflexState: var ReflexState): ReflexResult =
  ## Check all reflex conditions against the current belief. Returns
  ## the highest-priority reflex that fires, or `fired = false`.
  ## Called from `bot.nim:reconcileDirective` after `updateBelief`
  ## completes, before the decide step runs.
  let tick = belief.tick
  let mode = belief.directive.mode
  result.fired = false

  # --- Reflex 4: voting_screen_appeared → meeting ---
  # Highest priority — always fires regardless of current mode.
  let votingAppeared = belief.self.phase == PhaseVoting and
                       reflexState.prevPhase != PhaseVoting
  if votingAppeared and
     tick - reflexState.lastVotingTick > ReflexCooldownTicks:
    reflexState.lastVotingTick = tick
    result.fired = true
    result.reflexName = "voting_screen_appeared"
    result.newDirective = Directive(
      mode: ModeMeeting,
      params: ModeParams(mode: ModeMeeting, meetWantToSpeakFirst: false),
      source: SourceReflex,
      issuedAtTick: tick,
      ttlTicks: 0,  # Meetings last until the phase ends.
      reflexName: "voting_screen_appeared",
      reasoning: ""
    )
    # Update edge state before returning.
    reflexState.prevBodyCount = belief.percep.visibleBodies.len
    reflexState.prevPhase = belief.self.phase
    return

  # Edge detection: did a new body appear this frame?
  let newBodySeen = belief.percep.visibleBodies.len > reflexState.prevBodyCount

  # --- Reflex 1: task_completing (crew, alive) + body → reporting ---
  if mode == ModeTaskCompleting and
     belief.self.role == RoleCrewmate and
     belief.self.alive and
     not belief.self.isGhost and
     newBodySeen and
     tick - reflexState.lastBodyReportTick > ReflexCooldownTicks:
    # Compute body world position for the reporting mode's target.
    let body = belief.percep.visibleBodies[0]
    let bodyWX = visibleCrewmateWorldX(belief.percep.cameraX, body.x)
    let bodyWY = visibleCrewmateWorldY(belief.percep.cameraY, body.y)
    reflexState.lastBodyReportTick = tick
    result.fired = true
    result.reflexName = "body_newly_in_view_report"
    result.newDirective = Directive(
      mode: ModeReporting,
      params: ModeParams(mode: ModeReporting,
                         repBodyLocation: Point(x: bodyWX, y: bodyWY)),
      source: SourceReflex,
      issuedAtTick: tick,
      ttlTicks: 480,  # ~20s timeout.
      reflexName: "body_newly_in_view_report",
      reasoning: ""
    )
    reflexState.prevBodyCount = belief.percep.visibleBodies.len
    reflexState.prevPhase = belief.self.phase
    return

  # --- Reflex 2: hunting + body_newly_in_view (not ours) → fleeing ---
  if mode == ModeHunting and
     belief.self.role == RoleImposter and
     belief.self.alive and
     newBodySeen and
     tick - reflexState.lastBodyFleeTick > ReflexCooldownTicks:
    let body = belief.percep.visibleBodies[0]
    let bodyWX = visibleCrewmateWorldX(belief.percep.cameraX, body.x)
    let bodyWY = visibleCrewmateWorldY(belief.percep.cameraY, body.y)
    reflexState.lastBodyFleeTick = tick
    result.fired = true
    result.reflexName = "body_newly_in_view_flee"
    result.newDirective = Directive(
      mode: ModeFleeing,
      params: ModeParams(mode: ModeFleeing,
                         fleeAwayFrom: Point(x: bodyWX, y: bodyWY),
                         fleeMinDistance: 48,
                         fleeDurationTicks: 240),
      source: SourceReflex,
      issuedAtTick: tick,
      ttlTicks: 240,
      reflexName: "body_newly_in_view_flee",
      reasoning: ""
    )
    reflexState.prevBodyCount = belief.percep.visibleBodies.len
    reflexState.prevPhase = belief.self.phase
    return

  # --- Reflex 3: pretending + lone crew in kill range → hunting ---
  if mode == ModePretending and
     belief.self.role == RoleImposter and
     belief.self.alive and
     not belief.self.isGhost and
     belief.percep.killReady and
     belief.percep.visibleCrewmates.len == 1 and
     tick - reflexState.lastOpportunisticKillTick > ReflexCooldownTicks:
    # Check that no other non-imposter is visible (max_witnesses = 0).
    # With only 1 visible crewmate and no others, this is a clean kill.
    let target = belief.percep.visibleCrewmates[0]
    reflexState.lastOpportunisticKillTick = tick
    result.fired = true
    result.reflexName = "lone_crew_kill_opportunity"
    result.newDirective = Directive(
      mode: ModeHunting,
      params: ModeParams(mode: ModeHunting,
                         hunPreferredTarget: target.colorIndex,
                         hunMaxWitnesses: 0,
                         hunOpportunistic: false,
                         hunCoverMode: ModePretending),
      source: SourceReflex,
      issuedAtTick: tick,
      ttlTicks: 120,  # ~5s.
      reflexName: "lone_crew_kill_opportunity",
      reasoning: ""
    )
    reflexState.prevBodyCount = belief.percep.visibleBodies.len
    reflexState.prevPhase = belief.self.phase
    return

  # No reflex fired — update edge-trigger memory.
  reflexState.prevBodyCount = belief.percep.visibleBodies.len
  reflexState.prevPhase = belief.self.phase
