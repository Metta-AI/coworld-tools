"""Suspicion: near-certain detection + conservative event-log scoring (design §10.1).

Two tiers feed one per-color ``suspicion`` score and the derived
``believed_imposters`` set (which drives Flee). Crewmate-only — an imposter knows
the truth (accrues nothing, never flees); a ghost does not flee either.

**Tier 1 — near-certain (permanent).** Frame-to-frame transitions off the
perception tape (§5.1) that identify an imposter with ~100% confidence; a hit adds
the color to ``confirmed_imposters`` for the rest of the game (cleared on death):

1. *Witnessed kill* — the victim was alive a frame ago, we see their body now, and
   exactly **one** other player was within kill range of the victim a frame ago.
2. *Witnessed vent* — *emergence* (a vent in line of sight + clear last frame is
   occupied now) or *submersion* (a player in the vent last frame is gone while the
   vent is still in line of sight). LoS uses the decoded ``shadow`` mask
   (``rect_visible``), so occlusion does not cause false "clear" calls.

Both require **consecutive** frames, so a meeting gap can never be read as a
transition.

**Tier 2 — graded (conservative, recomputed each tick).** A pure readout of the
per-player event log (§5.2) — no accumulation state of its own, so it can't
double-count and old evidence ages out as events are evicted. Only a few
**low-false-positive** patterns score; circumstantial-but-noisy ones (brief
proximity, passing a body) are deliberately excluded:

- *Sustained vent dwell* — sitting on a vent rect ≥ `VENT_DWELL_MIN_TICKS`
  (innocents cross vents, they don't loiter on them).
- *Lingering at a body* — ≥ `BODY_LINGER_MIN_TICKS` and within
  `BODY_LINGER_MAX_DIST` (hovering at a corpse, not a passing reporter).
- *Following a victim to their death* — proximity to player V for ≥
  `FOLLOW_MIN_TICKS` where V is now dead and the proximity ended within
  `FOLLOW_DEATH_WINDOW_TICKS` of when we found V's body.

The final score is `graded + (CONFIRMED_SCORE if confirmed)`. A color becomes a
believed imposter at `BELIEVE_THRESHOLD`: a near-certain confirmation clears it by
a wide margin, while graded evidence needs **corroboration** (no single soft signal
reaches it), so we never flee on one circumstantial cue. The weights are an initial
conservative cut and want tuning against real games.
"""

from __future__ import annotations

from players.crewrift.crewborg.action import KILL_RANGE_SQ
from players.crewrift.crewborg.strategy.occupancy import (
    neighbors_within,
    players_in_rect,
    rect_visible,
)
from players.crewrift.crewborg.types import Belief, PerceptionFrame

# A near-certain confirmation contributes this much — far above the belief
# threshold, so a confirmed imposter is always believed (until they die).
CONFIRMED_SCORE = 1000.0
# Flee a color once its score reaches this. Set so a confirmation trivially clears
# it but a single graded signal does not (graded flee needs corroboration).
BELIEVE_THRESHOLD = 3.0
# Graded score is capped so no one player's log can blow up the ranking.
GRADED_SCORE_CAP = 6.0

# Max distance a player can walk in one tick (MaxSpeed/MotionScale = 704/256 ≈ 2.75,
# rounded up): a player materialising inside a vent from beyond this vented.
VENT_WALK_MARGIN = 3

# --- graded-signal weights + gates (24 Hz; ~ticks) --------------------------
VENT_DWELL_MIN_TICKS = 24  # ~1 s loitering on a vent rect
WEIGHT_VENT_DWELL = 2.0
BODY_LINGER_MIN_TICKS = 24  # ~1 s next to a body
BODY_LINGER_MAX_DIST = 16  # world px — "right next to it", not passing by
WEIGHT_BODY_LINGER = 1.5
FOLLOW_MIN_TICKS = 48  # ~2 s of sustained proximity (following, not brushing past)
FOLLOW_DEATH_WINDOW_TICKS = 72  # the following ended ~within 3 s of finding the body
WEIGHT_FOLLOW_TO_DEATH = 2.0


def update_suspicion(belief: Belief) -> None:
    """Refresh ``suspicion`` + ``believed_imposters`` from both tiers.

    Run each tick after ``update_belief``/``update_event_log`` so the strategy
    snapshot sees a current set.
    """

    graded: dict[str, float] = {}
    if belief.self_role not in ("imposter", "dead"):
        _detect_witnessed_kill(belief)
        _detect_witnessed_vent(belief)
        graded = _score_event_log(belief)
    _recompute(belief, graded)


# --- tier 1: near-certain transitions ---------------------------------------


def _frame_pair(belief: Belief) -> tuple[PerceptionFrame, PerceptionFrame] | None:
    """The (previous, current) tape frames, only if they are consecutive ticks."""

    frames = belief.recent_frames
    if len(frames) < 2:
        return None
    prev, curr = frames[-2], frames[-1]
    return (prev, curr) if curr.tick == prev.tick + 1 else None


def _detect_witnessed_kill(belief: Belief) -> None:
    pair = _frame_pair(belief)
    if pair is None:
        return
    prev, curr = pair
    for victim_color in curr.bodies:
        victim_pos = prev.players.get(victim_color)  # was this body's owner alive a frame ago?
        if victim_pos is None:
            continue
        killers = [
            color
            for color in neighbors_within(prev, victim_pos, KILL_RANGE_SQ, exclude=victim_color)
            if color not in belief.teammate_colors
        ]
        if len(killers) == 1:  # a single, unambiguous neighbour ⇒ the killer
            _confirm(belief, killers[0])


def _detect_witnessed_vent(belief: Belief) -> None:
    pair = _frame_pair(belief)
    if pair is None or belief.map is None:
        return
    prev, curr = pair
    for vent in belief.map.vents:
        x, y, w, h = vent.x, vent.y, vent.w, vent.h
        # (a) Emergence: vent + walk-margin in line of sight and clear last frame, occupied now.
        watched_clear = rect_visible(prev, x, y, w, h, margin=VENT_WALK_MARGIN) and not players_in_rect(
            prev, x, y, w, h, margin=VENT_WALK_MARGIN
        )
        if watched_clear:
            for color in players_in_rect(curr, x, y, w, h):
                _confirm(belief, color)
        # (b) Submersion: a player was in the vent last frame; vent still in sight, player gone.
        if rect_visible(curr, x, y, w, h):
            for color in players_in_rect(prev, x, y, w, h):
                if color not in curr.players:
                    _confirm(belief, color)


def _confirm(belief: Belief, color: str) -> None:
    belief.confirmed_imposters.add(color)


# --- tier 2: graded event-log scoring ---------------------------------------


def _score_event_log(belief: Belief) -> dict[str, float]:
    """A conservative suspicion score per live player from their event log."""

    scores: dict[str, float] = {}
    for color, record in belief.roster.items():
        if record.life_status == "dead":
            continue
        score = sum(_event_weight(event, belief) for event in record.events)
        if score > 0:
            scores[color] = min(score, GRADED_SCORE_CAP)
    return scores


def _event_weight(event, belief: Belief) -> float:
    if event.kind == "vent" and event.duration_ticks >= VENT_DWELL_MIN_TICKS:
        return WEIGHT_VENT_DWELL
    if (
        event.kind == "near_body"
        and event.duration_ticks >= BODY_LINGER_MIN_TICKS
        and event.min_dist is not None
        and event.min_dist <= BODY_LINGER_MAX_DIST
    ):
        return WEIGHT_BODY_LINGER
    if event.kind == "proximity" and event.duration_ticks >= FOLLOW_MIN_TICKS:
        victim = belief.roster.get(event.target_color)
        if (
            victim is not None
            and victim.life_status == "dead"
            and victim.death_seen_tick is not None
            and abs(victim.death_seen_tick - event.end_tick) <= FOLLOW_DEATH_WINDOW_TICKS
        ):
            return WEIGHT_FOLLOW_TO_DEATH
    return 0.0


# --- combine ----------------------------------------------------------------


def _recompute(belief: Belief, graded: dict[str, float]) -> None:
    # A confirmed imposter who has died is no longer a threat.
    for color in list(belief.confirmed_imposters):
        record = belief.roster.get(color)
        if record is not None and record.life_status == "dead":
            belief.confirmed_imposters.discard(color)

    suspicion: dict[str, float] = {}
    believed: set[str] = set()
    for color in set(graded) | belief.confirmed_imposters:
        record = belief.roster.get(color)
        if record is not None and record.life_status == "dead":
            continue
        score = graded.get(color, 0.0) + (CONFIRMED_SCORE if color in belief.confirmed_imposters else 0.0)
        if score <= 0:
            continue
        suspicion[color] = score
        if score >= BELIEVE_THRESHOLD:
            believed.add(color)
    belief.suspicion = suspicion
    belief.believed_imposters = believed
