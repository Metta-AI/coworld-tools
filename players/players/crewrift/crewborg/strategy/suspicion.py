"""Near-certain imposter detection → ``believed_imposters`` (design §10.1).

A deliberately **narrow but high-confidence** flagger: it only fires on evidence
that identifies an imposter with near-100% certainty, and when it does it sets
suspicion very high. There are exactly two such situations, both **frame-to-frame
transitions** read off the perception tape (``belief.recent_frames``, §5.1):

1. **Witnessed kill.** We saw the victim *alive* one frame ago, we see the
   victim's *body* this frame, and exactly **one** other player was within kill
   range of the victim a frame ago — that lone neighbour is the killer.

2. **Witnessed vent.** Only an imposter can use a vent, so either transition is
   conclusive:
   a. *Emergence* — a frame ago we were watching the vent (and its one-tick-walk
      margin) and it was clear of players; this frame a player is inside the vent
      rect. They could not have walked in, so they came out of the vent.
   b. *Submersion* — a frame ago a player was inside the vent rect; this frame the
      vent is still in view but that player has vanished. They went into the vent.

Both detectors require the two frames to be **consecutive** (`tick` differs by 1)
so a meeting gap (no camera) can never be read as a transition. Occupancy and
adjacency are derived from the tape via ``strategy.occupancy`` — nothing is stored
beyond the raw frames and the resulting high suspicion score.

Only crewmates reason this way: an imposter already knows the truth (it accrues no
suspicion and never flees a crewmate); a ghost does not flee either.

The vent detectors use the real line-of-sight mask (the decoded ``shadow`` overlay,
via ``rect_visible``) for "we saw it", so occlusion no longer causes false
positives; they fall back to viewport containment only on frames before the mask
has arrived. Kill-witnessing uses only players we actually saw.
"""

from __future__ import annotations

from players.crewrift.crewborg.action import KILL_RANGE_SQ
from players.crewrift.crewborg.strategy.occupancy import (
    neighbors_within,
    players_in_rect,
    rect_visible,
)
from players.crewrift.crewborg.types import Belief, PerceptionFrame

# A confirmed detection sets suspicion this high — far above the belief threshold,
# and (with no decay) it persists for the rest of the game unless the suspect dies.
CONFIRMED_SUSPICION = 1000.0
# A color is a believed imposter once its suspicion reaches this. Any confirmed
# detection clears it by a wide margin; nothing else raises suspicion in this model.
BELIEVE_THRESHOLD = 1.0

# Max distance a player can walk in one tick (MaxSpeed/MotionScale = 704/256 ≈ 2.75,
# rounded up), so a player materialising inside a vent from beyond this could not
# have walked there — they vented.
VENT_WALK_MARGIN = 3


def update_suspicion(belief: Belief) -> None:
    """Fold near-certain evidence into ``believed_imposters`` (run each tick after
    ``update_belief``, which appends the current frame to the perception tape)."""

    if belief.self_role not in ("imposter", "dead"):
        _detect_witnessed_kill(belief)
        _detect_witnessed_vent(belief)
    _refresh_believed_imposters(belief)


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
    belief.suspicion[color] = CONFIRMED_SUSPICION


def _refresh_believed_imposters(belief: Belief) -> None:
    for color, score in belief.suspicion.items():
        record = belief.roster.get(color)
        if record is not None and record.life_status == "dead":
            belief.believed_imposters.discard(color)  # a dead imposter is no threat
        elif score >= BELIEVE_THRESHOLD:
            belief.believed_imposters.add(color)
