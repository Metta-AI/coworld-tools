"""CvCCritic — evaluates game experience for the PCO loop.

Listens on "experience" for a list of snapshot dicts, computes an evaluation
summary (total_resources, junction_control, deaths, final_hp), and transmits
the result on "evaluation". The "update" listener is a no-op required by the
PCO protocol (optimizer sends patches to both actor and critic).
"""

from __future__ import annotations

from typing import Any

from cogamer.cvc.coglet import Coglet, enact, listen


class CvCCritic(Coglet):
    """Evaluates CvC game snapshots and produces an evaluation dict."""

    @listen("experience")
    async def _on_experience(self, data: Any) -> None:
        evaluation = self.evaluate(data)
        await self.transmit("evaluation", evaluation)

    @enact("update")
    async def _on_update(self, data: Any) -> None:
        pass  # no-op: PCO protocol requires this handler

    def evaluate(self, snapshots: list[dict]) -> dict:
        """Compute evaluation metrics from a list of game snapshots."""
        total_resources = 0
        for snap in snapshots:
            resources = snap.get("team_resources", snap.get("resources", {}))
            total_resources += sum(resources.values())

        junction_control = 0
        for snap in snapshots:
            junctions = snap.get("junctions", {})
            junction_control += junctions.get("friendly", 0) - junctions.get("enemy", 0)

        deaths = sum(1 for snap in snapshots if snap.get("hp", 1) == 0)

        final_hp = snapshots[-1].get("hp", 0) if snapshots else 0

        return {
            "total_resources": total_resources,
            "junction_control": junction_control,
            "deaths": deaths,
            "final_hp": final_hp,
        }
