from __future__ import annotations

from cogsguard.core import CogsguardGame, register_game
from cogsguard.evals.cognitive_substrate_evals import (
    EVAL_MISSIONS as COGNITIVE_SUBSTRATE_EVAL_MISSIONS,
)
from cogsguard.evals.diagnostic_evals import DIAGNOSTIC_EVALS
from cogsguard.evals.integrated_evals import (
    EVAL_MISSIONS as INTEGRATED_EVAL_MISSIONS,
)
from cogsguard.evals.spanning_evals import (
    EVAL_MISSIONS as SPANNING_EVAL_MISSIONS,
)
from cogsguard.game import _get_all_variants
from cogsguard.missions.arena import make_basic_mission
from cogsguard.missions.empty import make_empty_mission
from cogsguard.missions.four_score import FourScoreMission
from cogsguard.missions.machina_1 import make_machina1_mission
from cogsguard.missions.mission import CvCMission
from cogsguard.missions.tutorial import make_tutorial_mission


class CvCGame(CogsguardGame):
    """Cogs vs Clips game with CvC missions and variants."""

    def __init__(self) -> None:
        eval_missions: list[CvCMission] = []
        eval_missions.extend(INTEGRATED_EVAL_MISSIONS)
        eval_missions.extend(SPANNING_EVAL_MISSIONS)
        eval_missions.extend(COGNITIVE_SUBSTRATE_EVAL_MISSIONS)
        eval_missions.extend(m() for m in DIAGNOSTIC_EVALS)  # type: ignore[call-arg]

        super().__init__(
            name="cogsguard",
            missions=[
                make_empty_mission(),
                make_machina1_mission(),
                make_basic_mission(),
                make_tutorial_mission(),
                FourScoreMission(),
            ],
            variants=_get_all_variants(),
            eval_missions=eval_missions,
        )


# Register for CLI --game resolution
register_game(CvCGame())
