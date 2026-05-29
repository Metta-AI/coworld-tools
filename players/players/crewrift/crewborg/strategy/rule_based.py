"""Rule-based mode selector (design §10).

A deterministic ``decide(snapshot) -> ModeDirective`` run every tick via
``SynchronousStrategyRunner`` — pure rules over belief. Because it runs every
tick, transitions are re-evaluated each cycle (no reflexes).

P2 covers the crewmate task loop: ``Normal`` during ``Playing``, ``idle``
otherwise. Meetings / report / flee (P3) and imposter selection (P4) extend the
priority order in design §10.
"""

from __future__ import annotations

from players.crewrift.crewborg.types import ActionState, Belief
from players.player_sdk import ModeDirective
from players.player_sdk.types import BeliefSnapshot


class RuleBasedStrategy:
    def decide(self, snapshot: BeliefSnapshot[Belief, ActionState]) -> ModeDirective:
        with snapshot.read() as memory:
            belief = memory.belief
            phase = belief.phase
            role = belief.self_role

        # Crewmate task loop. Imposters fall through to idle until P4; a dead
        # crewmate ghost still runs Normal to finish its own tasks (design §7.3).
        if phase == "Playing" and role in (None, "crewmate", "dead"):
            return ModeDirective(mode="normal", source="strategy", reason="playing: do tasks")

        # Meetings, report, and flee are added in P3; everything else idles.
        return ModeDirective(mode="idle", source="strategy", reason=f"idle in phase {phase}")
