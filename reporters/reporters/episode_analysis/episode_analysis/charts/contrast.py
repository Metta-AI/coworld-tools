"""Two-group contrast table: a typographic figure, not a bar chart.

Answers "across many observations, which axes actually distinguish group A
from group B?" — one row per axis: both group means, a slim separation bar
with the rank AUC beside it, and a direction glyph for which side scores
higher. Rows at or above the emphasis threshold render bold and bright;
everything below greys out so the eye lands on the few axes that matter.
Bar charts of the same means were rejected in the origin work: the table
carries identical information densely and scans a dozen axes at once.

Footnotes are hard-wrapped by the renderer, not the caller — with
``bbox_inches='tight'`` a footer wider than the table silently inflates the
canvas and shrinks the content in relative terms.
"""

from __future__ import annotations

import io
import math
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from ..palette import ACCENT, GRID, INK, MUTED, PAGE, PRIMARY, SECONDARY, SURFACE

__all__ = ["ContrastRow", "draw_contrast_table", "render_contrast_table"]

_BAR_X0, _BAR_W = 0.64, 0.22


@dataclass(frozen=True)
class ContrastRow:
    """One axis of the contrast. ``auc`` follows :func:`..stats.rank_auc`
    with group B as the group of interest: ``auc > 0.5`` means B tends
    higher. NaN means/auc render as placeholders and never emphasize."""

    label: str
    mean_a: float
    mean_b: float
    auc: float
    fmt: str = "{:.2f}"  # per-row: occupancy shares and tick counts differ wildly

    @property
    def separation(self) -> float:
        return abs(self.auc - 0.5) * 2.0 if math.isfinite(self.auc) else float("nan")


def _fmt(value: float, fmt: str) -> str:
    return fmt.format(value) if math.isfinite(value) else "–"


def draw_contrast_table(
    ax,
    rows: Sequence[ContrastRow],
    *,
    group_a: str,
    group_b: str,
    color_a: str = PRIMARY,
    color_b: str = ACCENT,
    emphasis_threshold: float = 0.5,
    sort: bool = True,
) -> list[ContrastRow]:
    """Draw the table onto ``ax`` (unit x, one row per unit y, header above).

    Returns the rows in drawn order (descending separation when ``sort``).
    Deterministic anatomy for tests: ``3 + 5 * n`` texts; ``n // 2`` zebra
    + ``n`` bar-track + one bar-fill patch per finite non-zero separation.
    """
    if not rows:
        raise ValueError("contrast table needs at least one row")
    drawn = list(rows)
    if sort:
        drawn.sort(key=lambda r: r.separation if math.isfinite(r.separation) else -1.0, reverse=True)

    n = len(drawn)
    ax.set_xlim(0, 1)
    ax.set_ylim(n - 0.5, -1.0)  # row 0 at the top, header row above it
    ax.set_facecolor(PAGE)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    for header, x, ha in ((group_a, 0.46, "right"), (group_b, 0.60, "right"), ("separation", _BAR_X0, "left")):
        ax.text(x, -0.5, header, ha=ha, va="center", color=SECONDARY, fontsize=8)

    for i, row in enumerate(drawn):
        s = row.separation
        emphasized = math.isfinite(s) and s >= emphasis_threshold
        if i % 2:
            ax.add_patch(Rectangle((0, i - 0.5), 1, 1, facecolor=SURFACE, lw=0, zorder=0))
        ax.add_patch(Rectangle((_BAR_X0, i - 0.12), _BAR_W, 0.24, facecolor=GRID, lw=0, zorder=1))
        if math.isfinite(s) and s > 0:
            ax.add_patch(
                Rectangle(
                    (_BAR_X0, i - 0.12),
                    _BAR_W * s,
                    0.24,
                    facecolor=color_b if row.auc > 0.5 else color_a,
                    alpha=1.0 if emphasized else 0.45,
                    lw=0,
                    zorder=2,
                )
            )
        ax.text(
            0.02,
            i,
            row.label,
            ha="left",
            va="center",
            fontsize=9,
            color=INK if emphasized else MUTED,
            fontweight="bold" if emphasized else "normal",
        )
        value_color = SECONDARY if emphasized else MUTED
        ax.text(0.46, i, _fmt(row.mean_a, row.fmt), ha="right", va="center", fontsize=9, color=value_color)
        ax.text(0.60, i, _fmt(row.mean_b, row.fmt), ha="right", va="center", fontsize=9, color=value_color)
        ax.text(0.88, i, _fmt(s, "{:.2f}"), ha="left", va="center", fontsize=8, color=value_color)
        if math.isfinite(row.auc) and row.auc > 0.5:
            glyph, glyph_color = "▲", color_b
        elif math.isfinite(row.auc) and row.auc < 0.5:
            glyph, glyph_color = "▼", color_a
        else:
            glyph, glyph_color = "·", MUTED
        ax.text(0.965, i, glyph, ha="center", va="center", fontsize=8, color=glyph_color)
    return drawn


def _build(
    rows: Sequence[ContrastRow],
    *,
    title: str,
    group_a: str,
    group_b: str,
    color_a: str,
    color_b: str,
    emphasis_threshold: float,
    footnotes: Sequence[str],
    footnote_wrap: int,
    sort: bool,
) -> Figure:
    lines = [line for note in footnotes for line in textwrap.wrap(note, footnote_wrap)]
    n = len(rows)
    axes_h = 0.34 * (n + 1)
    footer_h = 0.20 * len(lines) + 0.30
    fig_h = 0.55 + axes_h + footer_h
    fig = plt.figure(figsize=(10.0, fig_h), facecolor=PAGE)
    ax = fig.add_axes((0.02, footer_h / fig_h, 0.96, axes_h / fig_h))
    draw_contrast_table(
        ax,
        rows,
        group_a=group_a,
        group_b=group_b,
        color_a=color_a,
        color_b=color_b,
        emphasis_threshold=emphasis_threshold,
        sort=sort,
    )
    fig.text(0.02, 1 - 0.18 / fig_h, title, ha="left", va="top", color=SECONDARY, fontsize=11)
    if lines:
        fig.text(
            0.02,
            (footer_h - 0.12) / fig_h,
            "\n".join(lines),
            ha="left",
            va="top",
            color=MUTED,
            fontsize=7,
            linespacing=1.5,
        )
    return fig


def render_contrast_table(
    rows: Sequence[ContrastRow],
    *,
    title: str,
    group_a: str,
    group_b: str,
    color_a: str = PRIMARY,
    color_b: str = ACCENT,
    emphasis_threshold: float = 0.5,
    footnotes: Sequence[str] = (),
    footnote_wrap: int = 95,
    sort: bool = True,
    dpi: int = 130,
) -> bytes:
    """Render the contrast table to PNG bytes."""
    fig = _build(
        rows,
        title=title,
        group_a=group_a,
        group_b=group_b,
        color_a=color_a,
        color_b=color_b,
        emphasis_threshold=emphasis_threshold,
        footnotes=footnotes,
        footnote_wrap=footnote_wrap,
        sort=sort,
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor=PAGE, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    return buf.getvalue()
