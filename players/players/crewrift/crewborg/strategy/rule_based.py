"""Rule-based mode selector (design §10).

For v1 the strategy is a deterministic ``decide(snapshot) -> ModeDirective`` run
every tick via ``SynchronousStrategyRunner`` — pure rules over belief. The
role/phase-aware selection in design §10 lands in P2+ (crewmate) and P4
(imposter). In P0 it always selects ``idle``, exercising the strategy seam
end-to-end.
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief
from players.player_sdk import ModeDirective
from players.player_sdk.types import BeliefSnapshot


class RuleBasedStrategy:
    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> ModeDirective:
        del snapshot  # P0 selection is belief-independent
        return ModeDirective(mode="idle", source="strategy", reason="P0 idle policy")
