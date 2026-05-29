"""Hunt mode: kill an isolated crewmate (imposter, kill ready; design §7.2).

Targets the kill opportunity chosen by ``strategy.opportunity.kill_opportunity``
(the nearest reachable, isolated, non-teammate crewmate in view) and emits
``kill``; the action layer navigates to it and edge-presses A in range. Hunt and
the selector share that one opportunity function, so Hunt only ever runs when a
target genuinely exists — and the instant the opening evaporates it idles, which
the selector observes and flips back to Pretend.
"""

from __future__ import annotations

from players.crewrift.crewborg.strategy.opportunity import kill_opportunity
from players.crewrift.crewborg.types import ActionState, Belief, Intent
from players.player_sdk import EmptyModeParams, Mode


class HuntMode(Mode[Belief, ActionState, Intent]):
    name = "hunt"
    params_type = EmptyModeParams

    def decide(self, belief: Belief, action_state: ActionState) -> Intent:
        del action_state
        target = kill_opportunity(belief)
        if target is None:
            return Intent(kind="idle", reason="no kill opportunity")
        return Intent(kind="kill", target_id=target.object_id, reason="hunting isolated crewmate")
