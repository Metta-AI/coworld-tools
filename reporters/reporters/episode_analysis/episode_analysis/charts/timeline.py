"""Swimlane timelines: one row per episode or per player.

The generalized engine of the origin's task-completion swimlanes
(``swgy_tools.tasks.render._lanes``), with the game-specific dataclasses
replaced by a :class:`Lane`/:class:`Marker`/:class:`Band` model:

- a lane's grey baseline spans its lifetime; a red overlay after
  ``cross_tick`` marks the "dead but the episode kept going" stretch;
- :class:`Marker` events are tick-exact circles with short labels — a burst
  of quick events staggers markers onto helper rows (with a stem back to the
  lane) instead of stacking them into mush;
- :class:`Band` spans (meetings, phases, rounds) are translucent bands whose
  width is the time they actually cost; ``emphasized`` bands hatch;
- the x-axis is cropped at the last *event* (not the longest episode) with a
  caret on lanes that run past it, so a late-game lull can't squash the plot.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from ..palette import ACCENT, GRID, MUTED, NEGATIVE, PAGE, PRIMARY, POSITIVE, SECONDARY, SURFACE

__all__ = ["Band", "Lane", "Marker", "render_swimlanes"]


@dataclass(frozen=True)
class Marker:
    """A tick-exact event dot. ``alt=True`` renders hollow (secondary state,
    e.g. "completed while dead")."""

    tick: int
    label: str = ""
    alt: bool = False


@dataclass(frozen=True)
class Band:
    """A span (meeting/phase/round). ``emphasized`` hatches it (e.g. a vote
    that ran the clock out)."""

    start: int
    end: int
    emphasized: bool = False


@dataclass
class Lane:
    """One row: an episode, or one player within an episode."""

    label: str
    end_tick: int
    markers: list[Marker] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    cross_tick: int | None = None  # death / elimination


def render_swimlanes(
    lanes: list[Lane],
    *,
    title: str | None = None,
    x_label: str = "game tick",
    marker_label: str = "event",
    alt_label: str = "event (alt)",
    cross_label: str = "eliminated",
    band_label: str = "span",
    emphasized_label: str = "span (emphasized)",
    dpi: int = 130,
) -> bytes:
    """Render the lanes to PNG bytes. Lane order is top-to-bottom."""
    n = max(len(lanes), 1)
    fig, ax = plt.subplots(figsize=(12.5, 1.1 + 0.62 * n), facecolor=PAGE)
    ax.set_facecolor(SURFACE)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)

    # Scale the axis to the last thing that HAPPENS, not the longest lane.
    last_event = max(
        [m.tick for lane in lanes for m in lane.markers]
        + [lane.cross_tick for lane in lanes if lane.cross_tick is not None]
        + [b.end for lane in lanes for b in lane.bands]
        + [0]
    )
    max_tick = max([lane.end_tick for lane in lanes] + [1])
    x_max = max(min(max_tick, last_event * 1.05 + 1), 1)
    truncated = 0

    # Anti-clutter: a crowded marker lifts onto the next free row with a stem
    # down to the lane. Its x — the tick — stays exact.
    min_sep = x_max * 0.019
    rows = (0.0, 0.30, -0.30)

    for i, lane in enumerate(lanes):
        y = n - 1 - i  # first lane at the top
        end = min(lane.end_tick, x_max)
        ax.hlines(y, 0, end, color=GRID, lw=3, zorder=1, capstyle="round")
        if lane.end_tick > x_max:
            truncated += 1
            ax.plot(x_max, y, marker=5, ms=6, color=MUTED, zorder=5)  # caret: runs on
        if lane.cross_tick is not None and lane.cross_tick >= 0:
            ax.hlines(y, lane.cross_tick, end, color=NEGATIVE, lw=3, alpha=0.22, zorder=2)
            ax.plot(lane.cross_tick, y, marker="x", ms=8, mew=2.2, color=NEGATIVE, zorder=6)

        for b in lane.bands:
            if b.start > x_max:
                continue
            ax.fill_between(
                [b.start, min(b.end, x_max)],
                y - 0.44,
                y + 0.44,
                color=ACCENT,
                alpha=0.20 if b.emphasized else 0.10,
                hatch="///" if b.emphasized else None,
                edgecolor=ACCENT,
                lw=0,
                zorder=1,
            )
            ax.vlines(b.start, y - 0.44, y + 0.44, color=ACCENT, lw=1.4, alpha=0.9, zorder=2)

        last = dict.fromkeys(rows, -1e18)
        for m in sorted(lane.markers, key=lambda m: m.tick):
            row = next((r for r in rows if m.tick - last[r] >= min_sep), rows[0])
            last[row] = m.tick
            cy = y + row
            if row:
                ax.plot([m.tick, m.tick], [y, cy], color=GRID, lw=1, zorder=3)
            face, edge = (SURFACE, POSITIVE) if m.alt else (PRIMARY, SURFACE)
            ax.plot(m.tick, cy, marker="o", ms=15, mfc=face, mec=edge, mew=1.6, zorder=4)
            if m.label:
                ax.annotate(
                    m.label,
                    (m.tick, cy),
                    ha="center",
                    va="center",
                    zorder=5,
                    fontsize=7,
                    fontweight="bold",
                    color=POSITIVE if m.alt else "#ffffff",
                )

    ax.set_yticks(range(n))
    ax.set_yticklabels(
        [lane.label for lane in reversed(lanes)],
        fontfamily="monospace",
        fontsize=8,
        color=SECONDARY,
    )
    ax.set_xlim(-x_max * 0.015, x_max * 1.02)
    ax.set_ylim(-0.8, n - 0.2)
    xlabel = x_label
    if truncated:
        xlabel += f"   (axis cropped at the last event; {truncated} lanes run on past it)"
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9, labelpad=6)
    ax.grid(axis="x", color=GRID, lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=SECONDARY, fontsize=11, loc="left", pad=26)

    handles = [
        Line2D([], [], marker="o", ls="", ms=9, mfc=PRIMARY, mec=SURFACE, label=marker_label),
        Line2D(
            [], [], marker="o", ls="", ms=9, mfc=SURFACE, mec=POSITIVE, mew=1.6, label=alt_label
        ),
        Line2D([], [], marker="x", ls="", ms=8, mew=2, color=NEGATIVE, label=cross_label),
        Patch(facecolor=ACCENT, alpha=0.10, label=band_label),
        Patch(
            facecolor=ACCENT,
            alpha=0.20,
            hatch="///",
            edgecolor=ACCENT,
            lw=0,
            label=emphasized_label,
        ),
    ]
    ax.legend(
        handles=handles,
        loc="lower right",
        bbox_to_anchor=(1.0, 1.005),
        ncol=5,
        frameon=False,
        fontsize=8,
        labelcolor=SECONDARY,
        handletextpad=0.4,
        columnspacing=1.6,
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=PAGE, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return buf.getvalue()
