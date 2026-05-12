"""CvC loss coglets for the PCO optimizer.

Each loss receives experience + evaluation and emits a signal with a name
and magnitude. Higher magnitude = worse performance on that axis.
"""

from __future__ import annotations

from typing import Any

from cogamer.pco.loss import LossCoglet


class ResourceLoss(LossCoglet):
    """Penalizes low total resource collection."""

    async def compute_loss(self, experience: Any, evaluation: Any) -> Any:
        total = evaluation.get("total_resources", 0)
        return {"name": "resource", "magnitude": max(0, 100 - total)}


class JunctionLoss(LossCoglet):
    """Penalizes negative junction control (enemy > friendly)."""

    async def compute_loss(self, experience: Any, evaluation: Any) -> Any:
        control = evaluation.get("junction_control", 0)
        return {"name": "junction", "magnitude": max(0, -control)}


class SurvivalLoss(LossCoglet):
    """Penalizes agent deaths (snapshots where hp == 0)."""

    async def compute_loss(self, experience: Any, evaluation: Any) -> Any:
        deaths = evaluation.get("deaths", 0)
        return {"name": "survival", "magnitude": deaths}
