"""Hunt mode: stalk a committed victim and strike when isolated (imposter; design §7.2).

Selected when the kill is ready and a victim is trackable. Rather than only firing on
a fleeting "visible + reachable + already-isolated" opportunity (which rarely lined
up, so imposters managed ~one kill a game), Hunt **commits to a victim and stalks
it**, leading its motion so it actually closes range on a moving target, and strikes
the moment the kill would go **unwitnessed**:

- pick the most-isolated reachable crewmate (``strategy.opportunity.select_victim``)
  and stick with it until it's killed or lost;
- navigate to its **predicted intercept** point (``strategy.trajectory``) — leading a
  moving target instead of tail-chasing its live position at equal speed;
- when within KillRange and unwitnessed → ``kill``; while a witness is near, keep
  shadowing (lie in wait) rather than blowing the kill — the urgency bar relaxes the
  witness requirement over time, so a perpetually-shadowed kill still eventually fires.

Two-imposter coordination (don't both stalk the same victim) and shadowing the victim
while the kill recharges are later refinements (design §7.4).
"""

from __future__ import annotations

from players.crewrift.crewborg.action import KILL_RANGE_SQ
from players.crewrift.crewborg.modes import imposter_common as ic
from players.crewrift.crewborg.strategy.opportunity import TRACK_WINDOW_TICKS, select_victim, unwitnessed
from players.crewrift.crewborg.strategy.trajectory import lead_ticks, predict
from players.crewrift.crewborg.types import ActionState, Belief, Intent, PlayerRecord
from players.player_sdk import EmptyModeParams, Mode, ModeParams


class HuntMode(Mode[Belief, ActionState, Intent]):
    name = "hunt"
    params_type = EmptyModeParams

    def __init__(self, params: ModeParams | None = None) -> None:
        super().__init__(params)
        self._victim_color: str | None = None  # the crewmate we have committed to hunting

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        self_xy = ic.self_xy(belief)
        if self_xy is None:
            return Intent(kind="idle", reason="no self position")

        victim = self._resolve_victim(belief)
        if victim is None:
            return Intent(kind="idle", reason="no victim to hunt")  # selector flips to Pretend

        victim_xy = (victim.world_x, victim.world_y)
        visible = victim.last_seen_tick == belief.last_tick

        # Strike: in range, victim present, and the kill goes unseen.
        if visible and ic.dist2(self_xy, victim_xy) <= KILL_RANGE_SQ and unwitnessed(belief, victim):
            return Intent(kind="kill", target_color=victim.color, reason="striking isolated victim")

        # Stalk: close on the predicted intercept (lead a moving target). If a witness
        # is near, we still shadow — just don't fire — until it isolates.
        intercept = predict(victim, lead_ticks(self_xy, victim_xy))
        lying_in_wait = visible and not unwitnessed(belief, victim)
        reason = "lying in wait for an opening" if lying_in_wait else "stalking the victim"
        return Intent(kind="navigate_to", point=intercept, reason=reason)

    def _resolve_victim(self, belief: Belief) -> PlayerRecord | None:
        """Keep the committed victim while it stays trackable; otherwise commit to a new one."""

        current = belief.roster.get(self._victim_color) if self._victim_color is not None else None
        if (
            current is not None
            and current.color not in belief.teammate_colors
            and current.life_status != "dead"
            and belief.last_tick - current.last_seen_tick <= TRACK_WINDOW_TICKS
        ):
            return current
        victim = select_victim(belief)
        self._victim_color = victim.color if victim is not None else None
        return victim
