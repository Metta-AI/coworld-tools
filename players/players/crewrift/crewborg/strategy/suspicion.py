"""Bayesian suspicion: posterior P(imposter) per player (design §10.1).

→ Canonical reference: ``docs/designs/suspicion.md`` — the living home for the
model, the likelihood-ratio table's rationale, the offline LR-learning workflow,
and the provenance log of every weight. Update that doc (and its provenance log)
whenever ``LIKELIHOOD_RATIOS`` changes.

Crewmate POV. For every other player we maintain `belief.suspicion[color]` = the
posterior **probability they are an imposter**, updated from a combinatorial prior
by the evidence we have observed. The score is a real probability, so thresholds
(e.g. the flee bar) are interpretable — no magic numbers.

**Prior.** With `P` players and `K` imposters, a crewmate knows the `K` imposters
are among the other `P − 1`; by symmetry each other player's marginal prior is
`K / (P − 1)`. `K` is derived from the player count via the game's auto formula
(`(P − 3) // 2`), overridable by `belief.imposter_count`.

**Update.** Work in log-odds: `logit(P) = logit(prior) + Σ log(LR_e)` over observed
evidence `e`, where `LR_e = P(e | imposter) / P(e | crewmate)` comes from a table.
`P = sigmoid(logit)`. The likelihood ratios are the **learnable surface**: the
values here are an initial hand-tuned cut, meant to be recomputed offline from game
replays and swapped in — the agent just consumes the table.

**Evidence** is a *set of types* per player (each type updates at most once), so an
unbounded event log can't inflate the posterior and there's no double-counting; and
because role is a fixed latent, evidence **persists** (no decay):

- Near-certain (huge LR ⇒ P ≈ 1), from frame-to-frame transitions on the tape (§5.1):
  *witnessed kill* (lone kill-range neighbour of a just-killed victim) and
  *witnessed vent* (emergence / submersion, line-of-sight via the `shadow` mask).
- Graded (modest LR), from the per-player event log (§5.2): *sustained vent dwell*,
  *lingering at a body*, *following a victim to their death*.

`believed_imposters` (which gates Flee) is every alive player with `P ≥
FLEE_PROBABILITY`. Crewmate-only — an imposter knows the truth, a ghost doesn't flee.

v1 simplifications (documented for later): naive-Bayes independence between evidence
types; positive-evidence-only (the prior is the baseline — no exculpatory terms);
and a static `K / (P − 1)` prior without redistributing the imposter budget as
players are confirmed/die (a proper joint model is a refinement).
"""

from __future__ import annotations

import math

from players.crewrift.crewborg.action import KILL_RANGE_SQ
from players.crewrift.crewborg.strategy.occupancy import (
    neighbors_within,
    players_in_rect,
    rect_visible,
)
from players.crewrift.crewborg.types import Belief, PerceptionFrame

# Likelihood ratios LR = P(evidence | imposter) / P(evidence | crewmate) per evidence
# type — the learnable surface of the model. The values below are INITIAL hand
# estimates (no games analysed yet); they are meant to be recomputed offline from
# replays and swapped in. Per-entry rationale, the learning procedure, and the
# provenance log for every value live in docs/designs/suspicion.md (§3, §6, §7) —
# update that doc whenever these change. witnessed_* are definitional (we saw it),
# not learned.
LIKELIHOOD_RATIOS: dict[str, float] = {
    "witnessed_kill": 1e6,  # caught in the act — only imposters kill; near-certain
    "witnessed_vent": 1e6,  # only imposters vent — near-certain
    "vent_dwell": 15.0,  # loitering on a vent rect; crewmates ~never do
    "body_linger": 3.0,  # hovering right at a corpse (innocent reporters do too)
    "follow_to_death": 6.0,  # sustained proximity to a victim who then died
}

# Flee a player once P(imposter) reaches this — a real probability, so the bar is
# interpretable (only near-certainty triggers the reactive Flee).
FLEE_PROBABILITY = 0.9
# Clamp the prior away from 0/1 so its log-odds stays finite.
PRIOR_MIN, PRIOR_MAX = 1e-3, 0.99

# Max distance a player can walk in one tick (MaxSpeed/MotionScale = 704/256 ≈ 2.75,
# rounded up): a player materialising inside a vent from beyond this vented.
VENT_WALK_MARGIN = 3

# --- graded-evidence gates (24 Hz; ~ticks) ----------------------------------
VENT_DWELL_MIN_TICKS = 24  # ~1 s loitering on a vent rect
BODY_LINGER_MIN_TICKS = 24  # ~1 s next to a body
BODY_LINGER_MAX_DIST = 16  # world px — "right next to it", not passing by
FOLLOW_MIN_TICKS = 48  # ~2 s of sustained proximity (following, not brushing past)
FOLLOW_DEATH_WINDOW_TICKS = 72  # the following ended ~within 3 s of finding the body


def update_suspicion(belief: Belief) -> None:
    """Recompute `suspicion` (posterior P(imp)) + `believed_imposters` each tick.

    Run after `update_belief`/`update_event_log` so the strategy snapshot is current.
    """

    if belief.self_role in ("imposter", "dead"):
        belief.suspicion = {}
        belief.believed_imposters = set()
        return
    _detect_witnessed_kill(belief)
    _detect_witnessed_vent(belief)
    _recompute(belief, _graded_evidence(belief))


# --- prior ------------------------------------------------------------------


def _imposter_count(belief: Belief) -> int:
    if belief.imposter_count is not None:
        return belief.imposter_count
    total = belief.total_player_count
    return 0 if total < 5 else max(0, min((total - 3) // 2, total - 1))


def _prior_imposter_p(belief: Belief) -> float:
    n_others = max(1, belief.total_player_count - 1)
    return min(max(_imposter_count(belief) / n_others, PRIOR_MIN), PRIOR_MAX)


# --- tier 1: near-certain transitions → confirmed_imposters ------------------


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
            belief.confirmed_imposters.add(killers[0])


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
                belief.confirmed_imposters.add(color)
        # (b) Submersion: a player was in the vent last frame; vent still in sight, player gone.
        if rect_visible(curr, x, y, w, h):
            for color in players_in_rect(prev, x, y, w, h):
                if color not in curr.players:
                    belief.confirmed_imposters.add(color)


# --- tier 2: graded evidence from the event log -----------------------------


def _graded_evidence(belief: Belief) -> dict[str, set[str]]:
    """The set of graded evidence types each live player exhibits in their log."""

    out: dict[str, set[str]] = {}
    for color, record in belief.roster.items():
        if record.life_status == "dead":
            continue
        types: set[str] = set()
        for event in record.events:
            if event.kind == "vent" and event.duration_ticks >= VENT_DWELL_MIN_TICKS:
                types.add("vent_dwell")
            elif (
                event.kind == "near_body"
                and event.duration_ticks >= BODY_LINGER_MIN_TICKS
                and event.min_dist is not None
                and event.min_dist <= BODY_LINGER_MAX_DIST
            ):
                types.add("body_linger")
            elif event.kind == "proximity" and event.duration_ticks >= FOLLOW_MIN_TICKS:
                victim = belief.roster.get(event.target_color)
                if (
                    victim is not None
                    and victim.life_status == "dead"
                    and victim.death_seen_tick is not None
                    and abs(victim.death_seen_tick - event.end_tick) <= FOLLOW_DEATH_WINDOW_TICKS
                ):
                    types.add("follow_to_death")
        if types:
            out[color] = types
    return out


# --- combine into the posterior ---------------------------------------------


def _recompute(belief: Belief, graded: dict[str, set[str]]) -> None:
    prior_logit = _logit(_prior_imposter_p(belief))
    suspicion: dict[str, float] = {}
    believed: set[str] = set()

    colors = set(belief.roster) | belief.confirmed_imposters
    for color in colors:
        record = belief.roster.get(color)
        if record is not None and record.life_status == "dead":
            continue  # the dead are no threat (the confirmation is kept for the record)
        evidence = set(graded.get(color, ()))
        if color in belief.confirmed_imposters:
            evidence.add("witnessed_kill")  # any near-certain catch — overwhelming LR
        logit = prior_logit + sum(math.log(LIKELIHOOD_RATIOS[e]) for e in evidence)
        p = _sigmoid(logit)
        suspicion[color] = p
        if p >= FLEE_PROBABILITY:
            believed.add(color)

    belief.suspicion = suspicion
    belief.believed_imposters = believed


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(logit: float) -> float:
    logit = max(-700.0, min(700.0, logit))  # keep exp finite
    return 1.0 / (1.0 + math.exp(-logit))
