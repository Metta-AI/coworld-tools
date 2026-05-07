## guided_bot type definitions.
##
## Phase 0: every type the rest of the skeleton refers to by name. No
## procs, no business logic — those live in the per-concern modules.
##
## Design reference: DESIGN.md §3 (belief state), §5 (modes), §5.3 (mode
## parameters), §6 (action intent), §7 (meeting actions). Names here
## match that doc when possible.
##
## Sub-record conventions, copied from `modulabot/DESIGN.md §3`:
##   - `Bot` is a thin envelope of sub-records plus a few cross-cutting
##     scalars (`frameTick`, top-level state that every layer reads).
##   - Field names inside a sub-record drop the prefix the sub-record
##     name implies. e.g. `bot.belief.directive.mode` not
##     `bot.beliefDirectiveMode`.

import constants
export constants

# ---------------------------------------------------------------------------
# Role / phase / mode enums
# ---------------------------------------------------------------------------

type
  BotRole* = enum
    RoleUnknown
    RoleCrewmate
    RoleImposter

  GamePhase* = enum
    PhaseUnknown
    PhaseLobby
    PhaseGameplay
    PhaseInterstitial   ## Role reveal / game-over text / generic black gap.
    PhaseVoting
    PhaseGameOver

  InterstitialKind* = enum
    ## Which specific interstitial we're looking at. Phase 1.0 detects
    ## only the black/not-black split and parks everything non-black
    ## under `NotInterstitial`; phase 1.5 (OCR) classifies the text
    ## content into the remaining variants.
    NotInterstitial
    InterstitialUnknown   ## Is black enough to be an interstitial; text unread.
    InterstitialRoleReveal          ## Generic (kept for backward compat).
    InterstitialRoleRevealCrewmate  ## "CREWMATE" banner detected.
    InterstitialRoleRevealImposter  ## "IMPS" banner detected.
    InterstitialVoting
    InterstitialVoteResult
    InterstitialGameOver

  CameraLock* = enum
    ## Quality / source of the most recent camera lock. Mirrors the
    ## ``CameraLock`` enum in ``modulabot/state.py``. Phase 1.2
    ## populates this; downstream consumers use it to gauge how much
    ## to trust ``camera_x`` / ``camera_y`` (e.g. local-frame locks
    ## are tighter than spiral-fallback global locks).
    NoLock
    LocalFrameMapLock      ## Cheap local refit succeeded.
    FrameMapLock           ## Patch-search or spiral-fallback succeeded.

  ModeName* = enum
    ## The full mode enum. See DESIGN.md §5.4.
    ##
    ## Ordering is stable: the integer value is logged in traces and
    ## used to index static dispatch tables. Appending is fine; reordering
    ## is a schema break.
    ModeIdle
    ModeTaskCompleting
    ModeFear
    ModeInvestigating
    ModeReporting
    ModePretending
    ModeHunting
    ModeFleeing
    ModeAlibiBuilding
    ModeSabotageWatching
    ModeMeeting

  DirectiveSource* = enum
    SourceDefault
    SourceLlm
    SourceReflex

  ActionDiscipline* = enum
    ## Hint to the action layer about the tactical shape of this tick's
    ## intent. See DESIGN.md §6.
    DisciplineNoOp
    DisciplineNormal
    DisciplineTaskHold
    DisciplineKillStrike
    DisciplineReport
    DisciplineWander  ## Emit raw direction buttons toward steerTo without
                      ## A* or localization. Used by idle mode to move
                      ## before the localizer has locked.

  MeetingActionKind* = enum
    MeetingActNone
    MeetingActSpeak
    MeetingActVote
    MeetingActUnvote
    MeetingActConfirmVote
    MeetingActWait

  CursorDir* = enum
    CursorNone
    CursorLeft
    CursorRight

  TaskPhase* = enum
    ## Sub-phase within `task_completing` mode's hold lifecycle.
    ## See TASK_COMPLETING_DESIGN.md §3.
    TpNavigate       ## Walking toward the target station.
    TpHold           ## At the station, pressing A for TaskHoldTicks.
    TpConfirm        ## A-hold finished, watching for icon disappearance.

  TaskSlotState* = enum
    ## Per-station state in `belief.tasks`. Populated by the belief-
    ## merge stage, consumed by `task_completing` and the LLM snapshot.
    ## See TASK_COMPLETING_DESIGN.md §4.
    TaskNotDoing     ## No evidence this task is ours.
    TaskCheckout     ## Radar dot matched — probably assigned.
    TaskConfirmed    ## Icon visible at this station — definitely assigned.
    TaskCompleted    ## Hold confirmed — icon disappeared after A-hold.

  TaskSelectionTier* = enum
    ## Which tier of evidence selected the current target.
    ## Logged in trace events.
    TierIcon         ## Icon visible on screen.
    TierCheckout     ## Radar-dot checkout latch.
    TierGeometry     ## Nearest unresolved station (weakest).

# ---------------------------------------------------------------------------
# Small point and action-intent types
# ---------------------------------------------------------------------------

type
  Point* = object
    x*, y*: int

  ## Phase 1.3 actor-scan result records. Match modulabot's
  ## ``CrewmateMatch``, ``BodyMatch``, ``GhostMatch`` in
  ## ``modulabot/state.py``. Stored in ``PerceptionState.visible*``
  ## seqs; cleared and rebuilt every frame by ``perception/actors.nim``.

  CrewmateMatch* = object
    ## One detected crewmate sprite. Screen coordinates ``(x, y)`` are
    ## the sprite's top-left anchor (not the collision-box centre).
    ## ``colorIndex`` is the dominant-tint index into ``PlayerColors``
    ## (``-1`` if no tint pixels voted). ``flipH`` records the
    ## orientation that matched (false = facing right).
    x*, y*: int
    colorIndex*: int
    flipH*: bool

  BodyMatch* = object
    ## One detected body (dead crewmate) sprite. Bodies don't flip in
    ## the game, so no ``flipH`` field.
    x*, y*: int
    colorIndex*: int

  GhostMatch* = object
    ## One detected ghost sprite. Ghosts are translucent, so no
    ## reliable colour extraction; only anchor + flip.
    x*, y*: int
    flipH*: bool

  ## Phase 1.4 task-icon and radar-dot result records. Match
  ## modulabot's ``IconMatch`` and ``RadarDotMatch`` in
  ## ``modulabot/state.py``. Stored in ``PerceptionState.visible*``
  ## seqs; cleared and rebuilt every frame by ``perception/tasks.nim``.

  IconMatch* = object
    ## One detected task-icon sprite. Screen coordinates ``(x, y)``
    ## are the sprite's top-left anchor.
    x*, y*: int

  RadarDotMatch* = object
    ## One deduped yellow radar dot in the screen-edge periphery ring.
    x*, y*: int

  ActionIntent* = object
    ## What a mode wants to happen this tick. The action layer translates
    ## this into a button mask. See DESIGN.md §6.
    steerTo*: Point        ## `valid = false` via the sentinel below.
    steerValid*: bool
    pressA*: bool
    pressB*: bool
    cursor*: CursorDir
    chat*: string          ## Empty string = no chat this tick.
    discipline*: ActionDiscipline

  MeetingAction* = object
    kind*: MeetingActionKind
    text*: string          ## MeetingActSpeak
    target*: int           ## MeetingActVote: color index or -1 for skip.

# ---------------------------------------------------------------------------
# Mode parameters
# ---------------------------------------------------------------------------
#
# First-pass schemas per DESIGN.md §5.3. Phase 0 uses a discriminated-union
# (`case` object) so the registry can carry a single `ModeParams` value
# regardless of which mode is active. Every mode has a default-constructed
# variant.

type
  TaskTargetKind* = enum
    TgtIndex
    TgtNearestMandatory
    TgtNearestAny
    TgtSpecificRoom

  TaskTarget* = object
    kind*: TaskTargetKind
    taskIndex*: int        ## TgtIndex
    roomId*: int           ## TgtSpecificRoom

  InvestigateKind* = enum
    InvestColor
    InvestLocation
    InvestRoom

  InvestigateTarget* = object
    kind*: InvestigateKind
    colorIndex*: int       ## InvestColor
    location*: Point       ## InvestLocation
    roomId*: int           ## InvestRoom

  ModeParams* = object
    ## Discriminated union keyed on the active mode name. Default-
    ## constructed instances of every variant are valid sentinels.
    case mode*: ModeName
    of ModeIdle:
      idleLingerAt*: Point
      idleLingerValid*: bool
      idleNearGroup*: bool
    of ModeTaskCompleting:
      tcTarget*: TaskTarget
      tcAbandonOnNearbyBody*: bool
    of ModeFear:
      fearMinVisibleOthers*: int
      fearPreferRoomId*: int     ## -1 = no hint.
      fearMaxDistance*: int
    of ModeInvestigating:
      invTarget*: InvestigateTarget
      invTimeoutTicks*: int
    of ModeReporting:
      repBodyLocation*: Point
    of ModePretending:
      preTarget*: TaskTarget
      preLoiterTicks*: int
      preMaySwapOnWitness*: bool
    of ModeHunting:
      huntPreferredTarget*: int     ## -1 = opportunistic.
      huntMaxWitnesses*: int
      huntOpportunistic*: bool
      huntCoverMode*: ModeName      ## ModePretending or ModeIdle.
    of ModeFleeing:
      fleeAwayFrom*: Point
      fleeMinDistance*: int
      fleeDurationTicks*: int
    of ModeAlibiBuilding:
      aliCompanionColor*: int
      aliRoomId*: int              ## -1 = any.
      aliMinDurationTicks*: int
    of ModeSabotageWatching:
      sabStationId*: int           ## Placeholder; depends on season.
    of ModeMeeting:
      meetWantToSpeakFirst*: bool

  Directive* = object
    mode*: ModeName
    params*: ModeParams
    source*: DirectiveSource
    issuedAtTick*: int
    ttlTicks*: int           ## <=0 means no TTL (default).
    reflexName*: string      ## Non-empty iff source == SourceReflex.
    reasoning*: string       ## LLM free-text, trace only.

# ---------------------------------------------------------------------------
# Belief state
# ---------------------------------------------------------------------------
#
# Phase 0: every sub-record is declared but mostly empty. Perception data
# is populated by the phase-1 perception layer; memory by a later phase.
# The ordering here matches DESIGN.md §3's conceptual layers.

type
  SelfState* = object
    role*: BotRole
    colorIndex*: int         ## -1 until observed.
    isGhost*: bool
    alive*: bool
    killCooldownRemaining*: int
    knownImposterColors*: seq[int]
    phase*: GamePhase
    ## Note: home position lives on PerceptionState (phase 1.2). See
    ## ``PerceptionState.homeX/homeY/homeSet``. Keeping it on the
    ## perception side mirrors modulabot's split — the home memory is
    ## a *camera* concept, not a role / alive concept, and it gets
    ## reseeded by ``localize.reseedCameraAtHome`` after interstitials.

  PerceptionState* = object
    ## Phase 1 fills this in incrementally across sub-phases. Phase
    ## 1.0 populates the interstitial fields. Phase 1.2 populates
    ## camera-lock fields (`cameraX`/`cameraY`, `localized`,
    ## `cameraScore`, `cameraLock`, `selfX`/`selfY`, plus the home /
    ## seeded helpers below). Later sub-phases add visible actors,
    ## task icons, voting-screen parse. See DESIGN.md §15 for the
    ## phase breakdown.
    ##
    ## Camera-lock fields (phase 1.2):
    cameraX*, cameraY*: int
    lastCameraX*, lastCameraY*: int  ## Previous-frame camera, used as
                                      ## the local-refit seed.
    cameraScore*: int        ## Most recent camera score (Python ordering).
    cameraLock*: CameraLock  ## Quality / source of the current lock.
    localized*: bool
    lastLocalizedTick*: int  ## Tick of the most recent successful lock.
    selfX*, selfY*: int      ## Inferred player world position when
                              ## `localized` is true.
    ## Camera-seed memory (phase 1.2). Populated on the first lock so
    ## post-interstitial reseeds start from a known-good camera.
    homeX*, homeY*: int
    homeSet*: bool
    gameStarted*: bool       ## False until the first successful lock;
                              ## forces spiral fallback to start at the
                              ## button rather than at stale state.
    ## Interstitial fields (phase 1.0).
    interstitial*: bool
    interstitialKind*: InterstitialKind
    blackPixelCount*: int    ## Cheap cache for the black-pixel detector.
    interstitialText*: string
    ## Phase 1.3 actor-scan results. Populated by
    ## ``perception/actors.scanAll``; cleared each frame.
    visibleCrewmates*: seq[CrewmateMatch]
    visibleBodies*: seq[BodyMatch]
    visibleGhosts*: seq[GhostMatch]
    ## Role / self-colour detection (phase 1.3). Updated by
    ## ``actors.updateRole`` / ``actors.updateSelfColor``.
    ghostIconFrames*: int  ## Consecutive frames with the ghost icon.
    killReady*: bool       ## Kill button is lit (imposter only).
    ## Phase 1.4 task-icon + radar-dot scan results. Populated by
    ## ``perception/tasks.scanTasksAndRadar``; cleared each frame.
    visibleTaskIcons*: seq[IconMatch]
    radarDots*: seq[RadarDotMatch]
    ## Phase 1.6 / 6.3 voting-screen parse results. Populated by
    ## ``mergeVotingPercept``; cleared on non-voting frames.
    votingValid*: bool       ## True when the current frame has a valid parse.
    votingCursor*: int       ## Current cursor slot, playerCount=SKIP, -1=unknown.
    votingSelfSlot*: int     ## Our slot index, -1=unknown.
    votingPlayerCount*: int  ## Number of players in the grid.

  PlayerSummary* = object
    role*: BotRole             ## RoleUnknown until evidence (role reveal, deduction).
    alive*: bool               ## Assumed true; set false on body sighting or ejection.
    lastSeenTick*: int
    lastSeenX*, lastSeenY*: int
    timesNearBody*: int
    timesWitnessedKill*: int
    ejected*: bool

  MemoryState* = object
    perPlayer*: array[PlayerColorCount, PlayerSummary]
    lastMeetingEndTick*: int

  TaskSlot* = object
    ## Per-task-station state in the belief. Updated by
    ## ``updateTaskState`` in the belief-merge stage.
    ## See TASK_COMPLETING_DESIGN.md §4.
    state*: TaskSlotState
    checkout*: bool          ## Radar-dot latch (persists across frames).
    iconVisibleTick*: int    ## Last tick an icon was seen at this station.
    iconMissCount*: int      ## Consecutive icon-absent frames while on-screen.
    resolvedNotMine*: bool   ## Negative evidence: inspected, no icon.

  TaskState* = object
    slots*: seq[TaskSlot]
    inProgressIndex*: int    ## -1 if none. Set by task_completing mode.
    initialized*: bool       ## True once slots have been allocated.

  ChatLine* = object
    tick*: int
    speakerColor*: int       ## -1 if unknown.
    text*: string

  SocialState* = object
    recentChat*: seq[ChatLine]
    currentMeetingChat*: seq[ChatLine]
    votesCast*: array[PlayerColorCount, int]  ## -1 skip, -2 abstain, color otherwise.

  WakeReason* = enum
    WakePeriodic
    WakeBodySeen
    WakeKillCooldownReady
    WakeChatObserved
    WakeMeetingStarted
    WakeRoleRevealed
    WakeReflexFired
    WakeDirectiveExpiringSoon

  FlagState* = object
    wakeReasons*: set[WakeReason]
    newDirectiveAvailable*: bool

  Belief* = object
    tick*: int
    self*: SelfState
    percep*: PerceptionState
    memory*: MemoryState
    tasks*: TaskState
    social*: SocialState
    directive*: Directive
    flags*: FlagState

# ---------------------------------------------------------------------------
# Navigation graph types (NAVIGATION_DESIGN.md §5)
# ---------------------------------------------------------------------------

type
  WaypointKind* = enum
    WpDoorway
    WpIntersection
    WpTask
    WpVent
    WpButton
    WpHome
    WpPoi

  Waypoint* = object
    id*: int
    x*, y*: int
    kind*: WaypointKind
    room*: string
    label*: string
    ventGroup*: char       ## '\0' if not a vent.
    ventIndex*: int        ## 0 if not a vent.

  NavEdge* = object
    src*, dst*: int        ## Waypoint IDs.
    cost*: int             ## Precomputed walk distance (pixels).
    isVent*: bool
    ventGroup*: char

  NavPath* = object
    ## Precomputed pixel-path for one walking edge. Points go from
    ## src waypoint toward dst waypoint (exclusive of src, inclusive
    ## of dst). Simplified via Douglas-Peucker at bake time.
    src*, dst*: int                ## Waypoint IDs from the baked path record.
    points*: seq[Point]

  NavGraph* = object
    waypoints*: seq[Waypoint]
    edges*: seq[NavEdge]
    paths*: seq[NavPath]          ## Indexed same as edges (walking only).
    ## Acceleration structures built at load time:
    adjacency*: seq[seq[int]]     ## waypoint index -> list of edge indices.
    idToIndex*: seq[int]          ## waypoint ID -> waypoint index, -1 if absent.
    edgeToPathIndex*: seq[int]    ## edge index -> paths index, -1 for vent edges.
    waypointCount*: int

  VentPolicy* = enum
    VentNever              ## Exclude vent edges (crewmate default).
    VentIfSafe             ## Include only if no witnesses visible.
    VentAlways             ## Always include (flee/emergency).

# ---------------------------------------------------------------------------
# Action-layer persistent state (navigation)
# ---------------------------------------------------------------------------

type
  ActionState* = object
    ## Navigation state for the hierarchical waypoint system.
    ## Extends waypoint routing with tactical motion control state.
    ## See NAVIGATION_DESIGN.md §5.2.
    currentGoal*: Point
    currentGoalValid*: bool
    strategicPath*: seq[int]       ## Waypoint indices; head = next target.
    currentEdgeIdx*: int           ## Index into NavGraph.edges (-1 = none).
    currentEdgeFrom*: int          ## Waypoint index departed from (-1 = none).
    currentEdgeTo*: int            ## Waypoint index being targeted (-1 = none).
    ventPolicy*: VentPolicy
    pathProgress*: int             ## Index into current edge's NavPath.points.
    lastSelfX*, lastSelfY*: int   ## For drift detection.
    lastPlanTick*: int             ## Last tick a strategic path was planned.
    lastProgressTick*: int         ## Last tick path/waypoint progress advanced.
    lastWaypointDistance*: int     ## Last distance to current waypoint.
    arrivedAtWaypoint*: bool       ## True on the tick a waypoint is consumed.
    navNoopUntilTick*: int         ## Defensive pause window after nav data errors.
    navErrorReason*: string        ## Last defensive navigation error.
    ventAttemptTicks*: int         ## Consecutive ButtonB ticks on a vent edge.
    lastEmittedMask*: uint8
    ## Momentum-aware steering state. Updated every tick by updateMotionState.
    haveMotionSample*: bool       ## True after first valid position sample.
    previousSelfX*: int           ## Last-frame world X (for velocity calculation).
    previousSelfY*: int           ## Last-frame world Y (for velocity calculation).
    velocityX*: int               ## Estimated velocity: pixels/frame, X axis.
    velocityY*: int               ## Estimated velocity: pixels/frame, Y axis.
    stuckFrames*: int             ## Consecutive frames of zero movement while pressing direction.
    jiggleTicks*: int             ## Remaining frames of perpendicular jiggle.
    jiggleSide*: int              ## 0 or 1; alternates each stuck event.
    taskHoldTicks*: int            ## Counter for TaskHold discipline.
    lastLookahead*: Point          ## World-space pixel target from selectLookahead.
    lastLookaheadValid*: bool      ## True when lastLookahead was set this tick.

# ---------------------------------------------------------------------------
# Mode scratch state
# ---------------------------------------------------------------------------
#
# Per DESIGN.md §5.6: each mode owns its own scratch, reset on mode switch,
# preserved across directive changes within the same mode. Phase 0 uses a
# discriminated union keyed on ModeName so the Bot envelope carries a
# single slot. Handlers access their own variant.

type
  ModeScratch* = object
    case mode*: ModeName
    of ModeIdle:
      idleEnterTick*: int
    of ModeTaskCompleting:
      tcLockedTaskIndex*: int       ## -1 if no target locked.
      tcEnterTick*: int             ## Tick when mode was entered.
      tcPhase*: TaskPhase           ## Navigate / Hold / Confirm.
      tcHoldRemaining*: int         ## Ticks left in Hold phase.
      tcHoldStartTick*: int         ## Tick when Hold began (for trace).
      tcConfirmDeadlineTick*: int   ## Tick when Confirm times out.
      tcConfirmMissCount*: int      ## Consecutive icon-absent frames in Confirm.
      tcCompletedTaskIndex*: int    ## Set on completion; bot.nim applies to belief.
      tcLockTick*: int              ## Tick when target was locked (hysteresis).
      tcLastReEvalTick*: int        ## Last periodic target re-evaluation tick.
      tcLockedTier*: TaskSelectionTier  ## Tier recorded when the current target was locked.
      tcSelectionTier*: TaskSelectionTier  ## Tier that selected the current target.
    of ModeFear:
      fearEnterTick*: int
    of ModeInvestigating:
      invDeadlineTick*: int
    of ModeReporting:
      repEnterTick*: int             ## Tick when mode was entered.
      repBodyMissCount*: int         ## Consecutive frames without body match.
      repReachedRange*: bool         ## True once dist <= ReportRange.
      repInRangeTicks*: int          ## Ticks spent in range without meeting.
      repGaveUp*: bool               ## Set when any give-up check fires.
      repGaveUpReason*: string       ## "body_gone" / "approach_timeout" / "in_range_timeout".
    of ModePretending:
      preFakeTargetIndex*: int
      preLoiterUntilTick*: int
      preEnterTick*: int
      preFakeHoldUntilTick*: int   ## Fake-hold sub-phase deadline.
      preWitnessSwapped*: bool     ## Whether witness swap fired this loiter.
    of ModeHunting:
      huntTargetColor*: int              ## Color of pursuit target.
      huntLastSightingTick*: int         ## Tick target was last seen.
      huntEnterTick*: int                ## Tick mode was entered.
      huntLastSeenX*: int                ## World X of last sighting.
      huntLastSeenY*: int                ## World Y of last sighting.
      huntCoverTargetIndex*: int         ## Station index for cover patrol (-1 = none).
      huntCoverLoiterUntilTick*: int     ## Loiter deadline at cover station.
      huntStrikeTick*: int               ## Tick when kill-strike A was first pressed (-1 = none).
      huntStrikeTargetX*: int            ## World X of target at strike time.
      huntStrikeTargetY*: int            ## World Y of target at strike time.
      huntPreStrikeBodyCount*: int       ## Visible body count before strike.
      huntPreStrikeKillReady*: bool      ## killReady state before strike.
      huntKillConfirmed*: bool           ## Set true on kill confirmation (for trace).
    of ModeFleeing:
      fleeUntilTick*: int
      fleeCoverTargetX*: int       ## Post-flee cover station world X.
      fleeCoverTargetY*: int       ## Post-flee cover station world Y.
      fleeCoverSet*: bool          ## Whether cover target has been picked.
    of ModeAlibiBuilding:
      aliEnterTick*: int
    of ModeSabotageWatching:
      sabEnterTick*: int
    of ModeMeeting:
      meetEnterTick*: int
      meetVoteConfirmed*: bool
      meetPendingActions*: seq[MeetingAction]
      meetVoteTarget*: int         ## Target slot for cursor nav, -1 = none.
      meetCursorMoveTicks*: int    ## Ticks remaining on current cursor hold.
      meetCursorDir*: CursorDir    ## Direction being held.
      meetLastLlmActionTick*: int  ## Tick of last LLM action received.
