"""Lane-arrow ladders: who chose whom, per round, at a glance.

One panel per round; one horizontal lane per actor, spanning the panel and
shaded in the actor's category color. A choice is a curved arrow from the
chooser's lane (left column) to the target's lane (right column), colored by
the *chooser's* category. The lane shading is the load-bearing choice: with
lanes tinted, "no arrow of color X ever lands on an X-shaded lane" is
visible without tracing a single endpoint. Callers order actors so their
priority group pins to the top.

Margins carry the secondary record: an ``x`` glyph for actors who abstained,
a small square for actors flagged by the caller (e.g. "spoke before
choosing"), and a faded lane for actors no longer active that round. Labels
for all of these are parameters — game vocabulary stays out of this module.
"""

from __future__ import annotations

import io
import math
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch

from ..palette import EDGE, MUTED, PAGE, SECONDARY, SURFACE

__all__ = ["LadderActor", "LadderArrow", "LadderPanel", "draw_ladder_panel", "render_lane_ladder"]

_X_MARK, _X_SKIP, _X_TAIL, _X_HEAD = 0.03, 0.10, 0.18, 0.90


@dataclass(frozen=True)
class LadderActor:
    """One lane: display label + the category color shared by the lane
    shading and every outgoing arrow."""

    label: str
    color: str


@dataclass(frozen=True)
class LadderArrow:
    """One choice: actor index -> actor index, with an optional small
    numeral at the tail (e.g. arrival order)."""

    src: int
    dst: int
    label: str = ""


@dataclass(frozen=True)
class LadderPanel:
    """One round. All member indices refer to the shared actor list."""

    title: str
    arrows: tuple[LadderArrow, ...] = ()
    skips: tuple[int, ...] = ()  # abstained: x glyph at the left margin
    marked: tuple[int, ...] = ()  # caller-defined flag: square at the far-left margin
    inactive: tuple[int, ...] = ()  # lane fades (e.g. dead this round)


def _check_indices(panel: LadderPanel, n: int) -> None:
    for what, indices in (
        ("arrow", [i for a in panel.arrows for i in (a.src, a.dst)]),
        ("skip", panel.skips),
        ("marked", panel.marked),
        ("inactive", panel.inactive),
    ):
        for i in indices:
            if not 0 <= i < n:
                raise ValueError(f"{what} index {i} out of range for {n} actors ({panel.title!r})")


def draw_ladder_panel(
    ax,
    actors: Sequence[LadderActor],
    panel: LadderPanel,
    *,
    lane_alpha: float = 0.25,
    inactive_alpha_scale: float = 0.35,
) -> None:
    """Draw one panel onto ``ax``. Deterministic anatomy for tests:
    ``len(actors) + len(arrows)`` patches, one collection per non-empty
    skip/marked set, one text per labeled arrow."""
    n = len(actors)
    _check_indices(panel, n)
    ax.set_xlim(0, 1)
    ax.set_ylim(n - 0.5, -0.5)  # actor 0 at the top
    ax.set_facecolor(SURFACE)
    ax.set_xticks([])
    ax.tick_params(colors=MUTED, length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(panel.title, fontsize=9, color=SECONDARY, loc="left")

    for i, actor in enumerate(actors):
        faded = inactive_alpha_scale if i in panel.inactive else 1.0
        ax.axhspan(
            i - 0.42,
            i + 0.42,
            xmin=0.15,
            xmax=1.0,
            facecolor=actor.color,
            alpha=lane_alpha * faded,
            lw=0,
            zorder=0,
        )

    seen: dict[tuple[int, int], int] = {}
    for arrow in panel.arrows:
        k = seen.get((arrow.src, arrow.dst), 0)
        seen[(arrow.src, arrow.dst)] = k + 1
        ax.add_patch(
            FancyArrowPatch(
                (_X_TAIL, arrow.src),
                (_X_HEAD, arrow.dst),
                connectionstyle=f"arc3,rad={0.16 + 0.06 * k}",
                arrowstyle="-|>",
                mutation_scale=11,
                color=actors[arrow.src].color,
                lw=1.5,
                zorder=3,
            )
        )
        if arrow.label:
            ax.text(
                _X_TAIL - 0.015,
                arrow.src - 0.18,
                arrow.label,
                fontsize=6,
                color=SECONDARY,
                ha="right",
                va="center",
                zorder=4,
            )

    if panel.skips:
        ax.scatter(
            [_X_SKIP] * len(panel.skips), list(panel.skips), marker="x", c=MUTED, s=42, zorder=3
        )
    if panel.marked:
        ax.scatter(
            [_X_MARK] * len(panel.marked),
            list(panel.marked),
            marker="s",
            facecolor=SECONDARY,
            edgecolor=EDGE,
            s=28,
            zorder=3,
        )


def _build(
    actors: Sequence[LadderActor],
    panels: Sequence[LadderPanel],
    *,
    title: str | None,
    lane_alpha: float,
    inactive_alpha_scale: float,
    skip_label: str,
    marker_label: str,
    wrap: int,
    footnote: str | None,
) -> Figure:
    if not actors:
        raise ValueError("lane ladder needs at least one actor")
    if not panels:
        raise ValueError("lane ladder needs at least one panel")
    n = len(actors)
    ncols = min(len(panels), wrap)
    nrows = math.ceil(len(panels) / wrap)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        sharey=True,
        squeeze=False,
        figsize=(1.5 + 2.3 * ncols, (0.42 * n + 0.9) * nrows + 0.6),
        facecolor=PAGE,
    )
    flat = [ax for row in axes for ax in row]
    for ax, panel in zip(flat, panels):
        draw_ladder_panel(
            ax, actors, panel, lane_alpha=lane_alpha, inactive_alpha_scale=inactive_alpha_scale
        )
    for ax in flat[len(panels) :]:
        ax.set_visible(False)

    axes[0][0].set_yticks(range(n))
    axes[0][0].set_yticklabels(
        [a.label for a in actors], fontfamily="monospace", fontsize=8, color=SECONDARY
    )
    # An actor gone before the first panel greys in the shared label column too.
    for i in panels[0].inactive:
        axes[0][0].get_yticklabels()[i].set_color(MUTED)

    handles = [
        Line2D([], [], marker="x", ls="", ms=7, mew=2, color=MUTED, label=skip_label),
        Line2D(
            [], [], marker="s", ls="", ms=6, mfc=SECONDARY, mec=EDGE, color=SECONDARY, label=marker_label
        ),
    ]
    fig.legend(
        handles=handles,
        loc="upper right",
        frameon=False,
        fontsize=8,
        labelcolor=SECONDARY,
        ncol=2,
    )
    if title:
        fig.suptitle(title, x=0.01, ha="left", color=SECONDARY, fontsize=11)
    if footnote:
        fig.text(
            0.01,
            0.005,
            "\n".join(textwrap.wrap(footnote, 95)),
            ha="left",
            va="bottom",
            color=MUTED,
            fontsize=7,
            linespacing=1.5,
        )
    return fig


def render_lane_ladder(
    actors: Sequence[LadderActor],
    panels: Sequence[LadderPanel],
    *,
    title: str | None = None,
    lane_alpha: float = 0.25,
    inactive_alpha_scale: float = 0.35,
    skip_label: str = "abstained",
    marker_label: str = "flagged",
    wrap: int = 6,
    footnote: str | None = None,
    dpi: int = 130,
) -> bytes:
    """Render the panels to PNG bytes; panels beyond ``wrap`` start new rows."""
    fig = _build(
        actors,
        panels,
        title=title,
        lane_alpha=lane_alpha,
        inactive_alpha_scale=inactive_alpha_scale,
        skip_label=skip_label,
        marker_label=marker_label,
        wrap=wrap,
        footnote=footnote,
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=PAGE, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return buf.getvalue()
