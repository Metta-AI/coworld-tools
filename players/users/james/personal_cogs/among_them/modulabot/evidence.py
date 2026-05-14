"""Witness / evidence bookkeeping for crewmate accusations.

Port of modulabot's ``evidence.nim``. The goal is to distinguish *proof*
(we saw the kill animation) from *correlation* (we saw this colour near a
body we just discovered). Both feed into the voting policy; proof outranks
correlation.

In state-observation mode the perception layer fills in player positions
and body positions every frame; we run diff logic here to detect *new*
bodies and log who was close when they appeared.
"""

from __future__ import annotations

from .state import Bot, BodySighting


def _manhattan(ax: int, ay: int, bx: int, by: int) -> int:
    return abs(ax - bx) + abs(ay - by)


def update_evidence(bot: Bot) -> None:
    """Run per-frame evidence bookkeeping. Called by the orchestrator."""
    percep = bot.percep
    evidence = bot.evidence
    tick = percep.tick

    current_body_positions = [(body.x, body.y) for body in percep.bodies]
    new_bodies = [
        body
        for body in percep.bodies
        if (body.x, body.y) not in evidence.prev_body_positions
    ]

    if new_bodies:
        _register_new_bodies(bot, new_bodies, tick)

    evidence.prev_body_positions = current_body_positions


def _register_new_bodies(bot: Bot, new_bodies: list[BodySighting], tick: int) -> None:
    """Anyone visible and close to a new body gets a ``near_body`` stamp.

    We don't stamp self or known imposter teammates (for imposters who might
    reuse this policy logic defensively — for crewmates the self-branch is
    dead code, but it's cheap to be symmetric).
    """
    percep = bot.percep
    identity = bot.identity
    evidence = bot.evidence

    for body in new_bodies:
        for player in percep.players:
            if player.is_self:
                continue
            if player.color in identity.known_imposters:
                continue
            if player.color == body.color:
                # The corpse can't have been close to itself.
                continue
            if _manhattan(player.x, player.y, body.x, body.y) <= 30:
                evidence.near_body_ticks[player.color] = tick


def evidence_suspect_color(bot: Bot) -> int:
    """Return the colour with the strongest evidence, or -1 if none.

    Priority: witnessed kill > near-body > none. Ties are broken by
    tick recency (more recent wins). Returns -1 so callers can treat
    it as a "no accusation" sentinel.
    """
    evidence = bot.evidence

    if evidence.witnessed_kill_ticks:
        return max(evidence.witnessed_kill_ticks.items(), key=lambda kv: kv[1])[0]
    if evidence.near_body_ticks:
        return max(evidence.near_body_ticks.items(), key=lambda kv: kv[1])[0]
    return -1


def record_witnessed_kill(bot: Bot, color: int) -> None:
    """Stamp ``color`` as a witnessed killer at the current tick.

    Currently unused from within this package — kept as a public hook for
    future policy extensions that detect kill animations in the pixel path.
    """
    bot.evidence.witnessed_kill_ticks[color] = bot.percep.tick
