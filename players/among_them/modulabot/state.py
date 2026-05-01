"""Sub-record state dataclasses for modulabot.

Port of modulabot's ``types.nim`` to Python. Each dataclass corresponds to one
sub-record in the Nim layout (see the Nim bot's ``DESIGN.md`` §3 for the
rationale).

The guiding principle is: group by *concern*, not by *when it's mutated*. Each
module that operates on one of these sub-records owns its mutation — perception
writes to ``Perception``, the imposter policy writes to ``ImposterState``, etc.

We deliberately do NOT replicate the Nim ``Sprites`` / ``Paths`` / ``FrameIO``
sub-records here. They existed in Nim because the bot was a direct WebSocket
client parsing pixel frames on its own. Inside cogames we receive observations
preprocessed by the environment, so those concerns either disappear (Paths,
Sprites) or collapse into whatever the cogames harness hands us (FrameIO).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Role(Enum):
    """Our inferred role for the current round."""

    UNKNOWN = 0
    CREWMATE = 1
    IMPOSTER = 2


class Phase(Enum):
    """Current game phase. Mirrors the BitWorld state-observation ``phase`` byte.

    Values match the header byte the cogames BitWorld shim writes; do not
    renumber without also updating :mod:`modulabot.perception.state_obs`.
    """

    UNKNOWN = 0
    PLAYING = 1
    VOTING = 2
    # cogames reserves 3 and 4 for other interstitial variants; we collapse
    # them into ROLE_REVEAL/INTERSTITIAL for our decision-making.
    ROLE_REVEAL = 5
    INTERSTITIAL = 6


class TaskState(Enum):
    """Per-task state machine. Same four tiers as the Nim bot.

    - ``NOT_DOING``: no evidence this task is on our list.
    - ``MAYBE``: radar or checkout evidence; worth visiting but don't hold.
    - ``MANDATORY``: task icon visible or confirmed on our list.
    - ``COMPLETED``: finished; leave it alone unless it reappears.
    """

    NOT_DOING = 0
    MAYBE = 1
    MANDATORY = 2
    COMPLETED = 3


class CameraLock(Enum):
    """How confident we are in the current camera offset.

    Mirrors the Nim ``CameraLock`` enum (``types.nim``). Downstream
    policies check ``bot.percep.localized`` to decide whether to read
    the camera at all; the lock tier is only interesting for
    diagnostics and for deciding whether to re-run the full-frame
    global search (frame lock) vs. trusting the cheap local refit
    (local-frame lock).
    """

    NO_LOCK = 0
    LOCAL_FRAME_MAP_LOCK = 1
    FRAME_MAP_LOCK = 2


# ---------------------------------------------------------------------------
# Small value types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Point:
    """Screen-space point. Origin top-left, +x right, +y down.

    We keep the Nim world-coordinate convention at the policy layer, but every
    observation we get from cogames is already screen-centred, so most points
    end up as deltas from screen centre.
    """

    x: int = 0
    y: int = 0


@dataclass(slots=True)
class PlayerSighting:
    """One visible player as parsed from the state observation.

    Mirrors the Nim ``CrewmateMatch`` struct. ``slot`` is the player's stable
    index in the game (0..PLAYER_COUNT-1), ``color`` is their palette index.
    """

    slot: int = -1
    x: int = 0
    y: int = 0
    color: int = -1
    alive: bool = True
    is_self: bool = False
    is_imposter_known: bool = False  # set if we've learned they are an imposter


@dataclass(slots=True)
class BodySighting:
    """One visible body. ``color`` is the dead player's colour."""

    x: int = 0
    y: int = 0
    color: int = -1


@dataclass(slots=True)
class TaskInfo:
    """One task station as reported by the state observation.

    Flag semantics match the BitWorld state-observation format used by the
    cogames cyborg baseline policy — see :mod:`modulabot.perception.state_obs`
    for the bit layout.
    """

    index: int = -1
    x: int = 0  # task-rect top-left, screen-space
    y: int = 0
    arrow_x: int = 0  # radar arrow direction (when offscreen)
    arrow_y: int = 0
    state: TaskState = TaskState.NOT_DOING
    icon_visible: bool = False
    arrow_visible: bool = False
    active: bool = False  # currently holding A would complete it


# ---------------------------------------------------------------------------
# Screen-space sprite match types (pixel-perception output)
# ---------------------------------------------------------------------------
# These mirror the Nim ``CrewmateMatch`` / ``BodyMatch`` / ``GhostMatch`` /
# ``IconMatch`` / ``RadarDot`` records. Populated by modulabot.perception
# from pixel observations; always screen coordinates relative to the
# sprite anchor top-left.


@dataclass(slots=True)
class CrewmateMatch:
    x: int = 0
    y: int = 0
    color_index: int = -1  # Index into PLAYER_COLORS; -1 = unknown tint
    flip_h: bool = False


@dataclass(slots=True)
class BodyMatch:
    x: int = 0
    y: int = 0
    color_index: int = -1


@dataclass(slots=True)
class GhostMatch:
    x: int = 0
    y: int = 0
    flip_h: bool = False


@dataclass(slots=True)
class IconMatch:
    x: int = 0
    y: int = 0


@dataclass(slots=True)
class RadarDotMatch:
    x: int = 0
    y: int = 0


@dataclass(slots=True)
class VoteSlot:
    """One player cell on the voting screen.

    Populated by :func:`modulabot.voting.parse_vote_slot`. ``color_index``
    is the PLAYER_COLORS index (0..15) or :data:`~modulabot.voting.
    VOTE_UNKNOWN` when the slot didn't match any known sprite.
    ``alive`` is ``False`` when the slot shows a body sprite instead
    of a player sprite — counts toward the vote but can't be voted
    *on* (the Nim bot enforces this via the cursor step helpers).
    """

    color_index: int = -1
    alive: bool = False


@dataclass(slots=True)
class VoteChatLine:
    """One OCR'd line from the voting-screen chat panel.

    Populated by :func:`modulabot.voting.parse_voting_candidate` once
    per frame. ``speaker_color`` is the PLAYER_COLORS index of the pip
    attributed to this line, or :data:`~modulabot.voting.VOTE_UNKNOWN`
    if we couldn't match the pip sprite. ``y`` is the text-line's
    screen-Y row — used for trace attribution and dedup across
    consecutive frames of the same meeting.
    """

    speaker_color: int = -1
    y: int = 0
    text: str = ""


@dataclass(slots=True)
class PathStep:
    """One waypoint along an A\\* path.

    ``found = False`` is the "no usable step" sentinel (matches the
    Nim convention); callers inspecting a path should treat an
    all-defaults PathStep as "idle" rather than "step to (0, 0)".
    Coordinates are world-space pixels, aligned with the walk mask
    grid.
    """

    found: bool = False
    x: int = 0
    y: int = 0


# ---------------------------------------------------------------------------
# Sub-records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Perception:
    """What the bot believes about the world from the current observation.

    Populated every frame by the perception layer. Policies read this and
    never write to it. Port of Nim ``Perception`` sub-record.

    Two kinds of fields live here:

    - **Screen-space raw matches** (``visible_crewmates`` / ``visible_bodies`` /
      ``visible_ghosts`` / ``visible_task_icons`` / ``radar_dots``):
      direct output of pixel-mode perception. Empty in state-obs mode.
    - **Derived high-level sightings** (``players`` / ``bodies`` / ``tasks``):
      policy-facing interpretation, populated from whichever pixel or state
      source was available.
    """

    tick: int = 0
    phase: Phase = Phase.UNKNOWN
    interstitial: bool = False
    interstitial_text: str = ""
    #: True when the pixel-mode localizer has a camera lock. Always
    #: True in state-obs mode (we effectively get ground-truth position).
    localized: bool = False
    camera_x: int = 0
    camera_y: int = 0
    camera_score: int = 0  # Lower = better map fit; 0 = uninitialized
    camera_lock: CameraLock = CameraLock.NO_LOCK
    #: Previous-frame camera, used by :mod:`modulabot.localize` to detect
    #: post-interstitial teleports (the bot may respawn far from its last
    #: lock — we don't want the local-refit heuristic to accept a bogus
    #: fit when that happens).
    last_camera_x: int = 0
    last_camera_y: int = 0
    #: Home point in world coordinates, typically the cafeteria/button.
    #: Seeded on the first successful lock; used to re-initialise the
    #: camera after an interstitial when the local refit has nothing to
    #: latch onto.
    home_x: int = 0
    home_y: int = 0
    home_set: bool = False
    #: True once we've localized at least once this round. Reset at
    #: interstitials so the localizer knows to run a full global search
    #: rather than trying a local refit from stale state.
    game_started: bool = False
    #: Task progress fraction 0..1 (from state-obs header). Unreliable in
    #: pixel-only mode — leave at 0.0.
    task_progress: float = 0.0

    # Pixel-mode raw matches (screen coords).
    visible_crewmates: list[CrewmateMatch] = field(default_factory=list)
    visible_bodies: list[BodyMatch] = field(default_factory=list)
    visible_ghosts: list[GhostMatch] = field(default_factory=list)
    visible_task_icons: list[IconMatch] = field(default_factory=list)
    radar_dots: list[RadarDotMatch] = field(default_factory=list)

    # Derived / high-level (policy-facing).
    players: list[PlayerSighting] = field(default_factory=list)
    bodies: list[BodySighting] = field(default_factory=list)
    tasks: list[TaskInfo] = field(default_factory=list)

    # Pixel-mode-only auxiliary signals.
    radar_target: Optional[Point] = None
    kill_icon_visible: bool = False


@dataclass(slots=True)
class Motion:
    """Previous-frame memory used to infer velocity and detect being stuck.

    The Nim bot uses this for pixel-level path steering with momentum. In
    screen-space cogames play we mostly use it to detect "we pressed a
    direction but didn't move" → nudge perpendicular (anti-stuck jiggle).

    ``prev_self_valid`` is the "have we recorded a sample yet?" flag —
    the first frame after construction or a teleport just seeds
    ``prev_self_*`` without computing velocity, so velocity spikes on
    that first frame can't confuse downstream readers.
    """

    prev_self_x: int = 0
    prev_self_y: int = 0
    prev_self_valid: bool = False
    velocity_x: int = 0
    velocity_y: int = 0
    stuck_ticks: int = 0
    jiggle_ticks: int = 0
    jiggle_side: int = 1  # +1 or -1


@dataclass(slots=True)
class Tasks:
    """Task-state bookkeeping. Sizes match ``Perception.tasks``."""

    states: list[TaskState] = field(default_factory=list)
    # Per-task latch: once MANDATORY and completed at least once, record it
    # so we don't re-navigate to the same station forever.
    resolved: list[bool] = field(default_factory=list)
    hold_ticks: int = 0
    hold_index: int = -1
    #: Index of the task the crewmate policy committed to on a previous
    #: tick. Kept across frames so ``best_actionable_task`` can stick
    #: with a target instead of re-scoring every tick — without this,
    #: tiny flickers in sprite matching or rect-boundary crossings
    #: cause the goal to flip frame-to-frame, which invalidates the
    #: A\* path and leaves the bot indecisive. ``-1`` means no commit.
    chosen_index: int = -1
    #: Tick at which ``chosen_index`` was set. Used to enforce a minimum
    #: commitment window (:data:`~modulabot.tuning.TASK_COMMIT_TICKS`)
    #: before the policy reconsiders its target.
    chosen_since_tick: int = -1


@dataclass(slots=True)
class Goal:
    """Currently selected navigation target.

    Shared between crewmate and imposter policies (Nim ``Goal``
    sub-record, Q1 in the design doc). ``index`` means different
    things to different policies: task index for crewmates,
    fake-target index for imposters.

    Two coordinate systems coexist here by design — one for the
    trace / policy-state diagnostic readout (screen space), one for
    the pathfinder (world space). The screen-space ``x``/``y`` /
    ``has`` fields are what the legacy state-obs-era code reads;
    the world-space ``world_x``/``world_y`` / ``has_world`` fields
    drive the A* pathfinder. The two can be set independently — a
    crewmate that sees a task icon right next to it sets the screen
    coords and skips pathing; a crewmate that's heading to a
    remembered task station sets both and lets
    :func:`~modulabot.policies.base.navigate_to_world_goal` run A*.

    ``path`` / ``path_step`` / ``has_path_step`` cache the most
    recent A\\* result and the lookahead waypoint selected from it.
    ``path_plan_tick`` is the tick count at which the path was last
    planned; used to gate re-planning (we don't want to pay A* on
    every frame, ~1-30 ms worst case is enough to blow the budget).
    """

    # Screen-space ("where we're aiming visually") — written for
    # every goal pick, regardless of whether pathfinding is used.
    has: bool = False
    x: int = 0
    y: int = 0
    index: int = -1
    name: str = ""

    # World-space ("where we actually want to be on the map") — set
    # when a world position is known (tasks have rect centres in the
    # game map; bodies / kill targets project via the camera). The
    # A* pathfinder reads from here.
    has_world: bool = False
    world_x: int = 0
    world_y: int = 0

    # Cached A* result + lookahead waypoint.
    path: list["PathStep"] = field(default_factory=list)
    path_step_x: int = 0
    path_step_y: int = 0
    has_path_step: bool = False
    #: Tick at which the path was last planned. Used with
    #: ``PATH_REPLAN_INTERVAL`` to throttle A* so the bot doesn't
    #: spend the whole tick budget re-planning.
    path_plan_tick: int = -1
    #: Re-planner anchor: the world position used to seed the last
    #: plan. We re-plan when we've wandered far from it (the cached
    #: lookahead is a relative waypoint, so stale anchors give
    #: bad directions).
    path_plan_self_x: int = 0
    path_plan_self_y: int = 0


@dataclass(slots=True)
class Identity:
    """What we know about ourselves and other players."""

    self_slot: int = -1
    self_color: int = -1
    # Colours we've identified as imposter teammates (from ROLE_REVEAL).
    known_imposters: set[int] = field(default_factory=set)
    # Tick-of-last-sighting per slot index. -1 means never seen.
    last_seen: dict[int, int] = field(default_factory=dict)


@dataclass(slots=True)
class Evidence:
    """Witness bookkeeping for the crewmate accusation policy.

    The Nim bot uses this to distinguish "witnessed the kill itself" from
    "was near a body when I found it". We keep the same distinction even
    though cogames state observations give us high-level ground truth, so
    the policies can degrade gracefully when we only have pixels.
    """

    # Tick of last time a colour was seen adjacent to a newly-appeared body.
    near_body_ticks: dict[int, int] = field(default_factory=dict)
    # Tick we directly saw a colour execute a kill (visible kill animation).
    witnessed_kill_ticks: dict[int, int] = field(default_factory=dict)
    # Last frame's body positions, so we can detect *new* bodies.
    prev_body_positions: list[tuple[int, int]] = field(default_factory=list)


@dataclass(slots=True)
class ImposterState:
    """Imposter-only book-keeping. Only meaningful when ``Bot.role == IMPOSTER``."""

    kill_ready: bool = False
    # Followee / fake-task mode as in the Nim bot.
    followee_color: int = -1
    followee_since_tick: int = 0
    fake_task_index: int = -1
    fake_task_until_tick: int = 0
    fake_task_cooldown_tick: int = 0
    prev_near_task_index: int = -1
    # After-kill self-report window.
    last_kill_tick: int = -1
    last_kill_x: int = 0
    last_kill_y: int = 0
    # Random-fake-target wander index (farthest from current / body).
    wander_index: int = -1


@dataclass(slots=True)
class VotingState:
    """Voting-screen UI state machine + parsed-frame cache.

    The decision half (cursor drive + listen timer + A press) lives
    in :class:`modulabot.policies.voting.VotingPolicy` and uses the
    first block of fields. The parsed-frame cache — every field
    prefixed with *parse:* below — is populated by
    :func:`modulabot.voting.parse_voting_screen` and consumed by the
    policy + the trace writer.

    The parse cache rebuilds every frame the voting screen is
    visible. Fields carry the *last known good* values across
    interstitials within a meeting; :func:`modulabot.voting.
    clear_voting_state` zeroes everything when a round ends.
    """

    active: bool = False
    start_tick: int = -1
    listen_done: bool = False  # true once we've waited long enough to commit
    committed: bool = False  # we've pressed A on our chosen target
    target_slot: int = -1  # -1 = skip
    cursor: int = -1  # current cursor slot; -1 = unknown
    # Accusation metadata derived from evidence. Used both for voting and for
    # meeting-chat generation.
    accusation_color: int = -1

    # Parsed-frame cache (filled by modulabot.voting.parse_voting_screen).
    player_count: int = 0
    self_slot: int = -1
    slots: list[VoteSlot] = field(default_factory=list)
    #: Per-slot vote target: ``choices[voter_color_index]`` = slot
    #: index the voter picked, :data:`VOTE_SKIP`, or
    #: :data:`VOTE_UNKNOWN` if no dot was seen for this colour. Fixed
    #: length of ``MAX_PLAYERS`` so the slot lookup never bounds-checks.
    choices: list[int] = field(default_factory=list)
    #: Colour index called "sus" most prominently in the chat panel,
    #: or :data:`VOTE_UNKNOWN` if no sus-call parses cleanly.
    chat_sus_color: int = -1
    #: Concatenated chat OCR for sus-target detection and trace
    #: writer payloads.
    chat_text: str = ""
    #: Per-line OCR entries with speaker attribution.
    chat_lines: list[VoteChatLine] = field(default_factory=list)


@dataclass(slots=True)
class ChatState:
    """Queued chat to flush on next voting interstitial.

    The BitWorld server only accepts chat while the vote UI is up, so we
    queue a message when we see a body / witness a kill and flush it on the
    next voting transition.
    """

    queued: str = ""
    last_flushed_tick: int = -1
    # Last body we reported *as* a crewmate (not a kill we made).
    last_report_x: int = -1
    last_report_y: int = -1


@dataclass(slots=True)
class Diag:
    """Human-readable activity description for logs / the eventual viewer.

    One-shot per frame; callers overwrite at will. Kept deliberately separate
    from the state the policies read so that adding a log line can't change
    behavior (Nim ``Diag`` sub-record).
    """

    intent: str = ""  # policy-set: "doing task", "flee body", ...
    thought: str = ""  # free-form debug
    branch_id: str = ""  # stable ID of the policy branch fired this frame


# ---------------------------------------------------------------------------
# Top-level Bot envelope
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Bot:
    """Per-agent state envelope.

    Intentionally thin. Cross-cutting scalars (``role``, ``tick``, ``rng_seed``)
    live at the top level; everything else is in a sub-record. See the Nim
    ``DESIGN.md`` §3 for why this split matters.

    There is one ``Bot`` per controlled agent. The :class:`~modulabot.policy.
    ModulabotPolicy` owns a dict of them keyed by agent id.
    """

    agent_id: int = -1
    role: Role = Role.UNKNOWN
    is_ghost: bool = False
    ghost_icon_frames: int = 0  # Consecutive frames the ghost HUD icon was visible
    tick: int = 0
    rng_seed: int = 0

    # Sub-records
    percep: Perception = field(default_factory=Perception)
    motion: Motion = field(default_factory=Motion)
    tasks: Tasks = field(default_factory=Tasks)
    goal: Goal = field(default_factory=Goal)
    identity: Identity = field(default_factory=Identity)
    evidence: Evidence = field(default_factory=Evidence)
    imposter: ImposterState = field(default_factory=ImposterState)
    voting: VotingState = field(default_factory=VotingState)
    chat: ChatState = field(default_factory=ChatState)
    diag: Diag = field(default_factory=Diag)

    def fired(self, branch_id: str, intent: str = "") -> None:
        """Mark the policy branch that produced this frame's action.

        Port of the Nim ``bot.fired(...)`` helper; used for tracing and debug
        logging. Safe to call multiple times — last call wins.
        """
        self.diag.branch_id = branch_id
        if intent:
            self.diag.intent = intent
