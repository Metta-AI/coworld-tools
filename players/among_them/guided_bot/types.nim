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

# ---------------------------------------------------------------------------
# Small point and action-intent types
# ---------------------------------------------------------------------------

type
  Point* = object
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
      hunPreferredTarget*: int     ## -1 = opportunistic.
      hunMaxWitnesses*: int
      hunOpportunistic*: bool
      hunCoverMode*: ModeName      ## ModePretending or ModeIdle.
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
    homeX*, homeY*: int
    homeSet*: bool
    phase*: GamePhase

  PerceptionState* = object
    ## Phase 1 fills this in. Empty placeholders for now.
    cameraX*, cameraY*: int
    localized*: bool
    selfX*, selfY*: int
    visiblePlayers*: seq[Point]    ## Phase 1: richer records.
    visibleBodies*: seq[Point]
    visibleTaskIcons*: seq[int]
    interstitialText*: string

  PlayerSummary* = object
    lastSeenTick*: int
    lastSeenX*, lastSeenY*: int
    timesNearBody*: int
    timesWitnessedKill*: int
    ejected*: bool

  MemoryState* = object
    perPlayer*: array[PlayerColorCount, PlayerSummary]
    lastMeetingEndTick*: int

  TaskSlot* = object
    state*: uint8            ## 0 not_doing, 1 maybe, 2 mandatory, 3 completed.
    lastSeenTick*: int

  TaskState* = object
    slots*: seq[TaskSlot]
    inProgressIndex*: int    ## -1 if none.

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
# Action-layer persistent state
# ---------------------------------------------------------------------------

type
  ActionState* = object
    ## Persistent tactical state owned by the action layer. See DESIGN.md
    ## §4.4. Phase 0 carries the fields so signatures are stable; phase-2
    ## movement logic fills them in.
    currentPath*: seq[Point]
    currentGoal*: Point
    currentGoalValid*: bool
    lastEmittedMask*: uint8
    lastVelocityX*, lastVelocityY*: int
    stuckFrames*: int
    jiggleTicks*: int
    taskHoldTicks*: int

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
      tcLockedTaskIndex*: int
      tcEnterTick*: int
    of ModeFear:
      fearEnterTick*: int
    of ModeInvestigating:
      invDeadlineTick*: int
    of ModeReporting:
      repEnterTick*: int
    of ModePretending:
      preFakeTargetIndex*: int
      preLoiterUntilTick*: int
      preEnterTick*: int
    of ModeHunting:
      hunTargetColor*: int
      hunLastSightingTick*: int
      hunEnterTick*: int
    of ModeFleeing:
      fleeUntilTick*: int
    of ModeAlibiBuilding:
      aliEnterTick*: int
    of ModeSabotageWatching:
      sabEnterTick*: int
    of ModeMeeting:
      meetEnterTick*: int
      meetVoteConfirmed*: bool
      meetPendingActions*: seq[MeetingAction]
