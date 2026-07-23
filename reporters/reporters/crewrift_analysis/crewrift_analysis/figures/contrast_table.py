"""The aggregate contrast table: crew vs imposter, one row per axis.

A thin mapping onto ``episode_analysis.charts.contrast``: this module owns
only the crewrift-specific parts — role colors, the group labels, and the
two on-figure footnotes (the task-exclusion rationale the figure must carry,
and the sample-size line).
"""

from __future__ import annotations

from collections.abc import Sequence

from episode_analysis.charts import ContrastRow
from episode_analysis.charts import render_contrast_table as _render_rows

from ..metrics import AxisContrast
from ..palette import ROLE_COLORS

__all__ = ["contrast_footnotes", "contrast_rows", "render_contrast_table"]

_EXCLUSION_NOTE = (
    "task completion/assignment excluded: the engine assigns imposters zero tasks, so those "
    "axes separate perfectly by construction; station occupancy is the behavioral version of "
    "the same idea."
)


def contrast_rows(contrasts: Sequence[AxisContrast]) -> list[ContrastRow]:
    """Map aggregated axes onto chart rows (crew = group A, imposter = B)."""
    return [ContrastRow(c.label, c.crew_mean, c.imposter_mean, c.auc, c.fmt) for c in contrasts]


def contrast_footnotes(contrasts: Sequence[AxisContrast], n_episodes: int) -> tuple[str, str]:
    n_crew = max((c.n_crew for c in contrasts), default=0)
    n_imposter = max((c.n_imposter for c in contrasts), default=0)
    counts = (
        f"{n_episodes} episodes, {n_crew} crew and {n_imposter} imposter player-games. "
        "separation = |rank AUC - 0.5| x 2; rows below 0.50 greyed."
    )
    return (_EXCLUSION_NOTE, counts)


def render_contrast_table(
    contrasts: Sequence[AxisContrast],
    *,
    n_episodes: int,
    title: str | None = None,
) -> bytes:
    """Render the crew/imposter contrast table to PNG bytes."""
    return _render_rows(
        contrast_rows(contrasts),
        title=title or "which behavioral axes distinguish imposters from crew",
        group_a="crew mean",
        group_b="imposter mean",
        color_a=ROLE_COLORS["crew"],
        color_b=ROLE_COLORS["imposter"],
        footnotes=contrast_footnotes(contrasts, n_episodes),
    )
