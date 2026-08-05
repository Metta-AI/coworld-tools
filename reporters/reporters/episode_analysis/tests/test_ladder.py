"""Tests for the lane-arrow ladder chart."""

from __future__ import annotations

import pytest

pytest.importorskip("matplotlib")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch  # noqa: E402

from episode_analysis.charts.ladder import (  # noqa: E402
    LadderActor,
    LadderArrow,
    LadderPanel,
    _build,
    draw_ladder_panel,
    render_lane_ladder,
)
from episode_analysis.palette import MUTED  # noqa: E402

ACTORS = [
    LadderActor("amber(0)", "#c98500"),
    LadderActor("blue(1)", "#3987e5"),
    LadderActor("aqua(2)", "#199e70"),
    LadderActor("red(3)", "#d03b3b"),
]


def _panel(**kwargs):
    defaults = dict(
        title="round 1",
        arrows=(LadderArrow(0, 1, "1"), LadderArrow(1, 0), LadderArrow(2, 0)),
        skips=(3,),
        marked=(1,),
        inactive=(2,),
    )
    defaults.update(kwargs)
    return LadderPanel(**defaults)


def test_draw_panel_counts():
    fig, ax = plt.subplots()
    draw_ladder_panel(ax, ACTORS, _panel())
    assert len(ax.patches) == 4 + 3  # lanes + arrows
    assert len(ax.collections) == 2  # skip batch + marked batch
    assert len(ax.texts) == 1  # only the labeled arrow
    lanes = ax.patches[:4]
    assert lanes[2].get_alpha() == pytest.approx(0.25 * 0.35)  # inactive fade
    assert lanes[0].get_alpha() == pytest.approx(0.25)
    arrow = next(p for p in ax.patches if isinstance(p, FancyArrowPatch))
    assert arrow.get_edgecolor()[:3] == pytest.approx((0xC9 / 255, 0x85 / 255, 0x00 / 255))
    plt.close(fig)


def test_duplicate_arrows_get_distinct_rads():
    fig, ax = plt.subplots()
    draw_ladder_panel(
        ax, ACTORS, LadderPanel("r", arrows=(LadderArrow(0, 1), LadderArrow(0, 1)))
    )
    rads = [p.get_connectionstyle().rad for p in ax.patches if isinstance(p, FancyArrowPatch)]
    assert len(rads) == 2 and rads[0] != rads[1]
    plt.close(fig)


def test_arrowless_panel_is_safe():
    fig, ax = plt.subplots()
    draw_ladder_panel(ax, ACTORS, LadderPanel("all skipped", skips=(0, 1, 2, 3)))
    assert len(ax.patches) == 4
    assert len(ax.collections) == 1
    plt.close(fig)


def test_out_of_range_index_raises():
    fig, ax = plt.subplots()
    with pytest.raises(ValueError, match="out of range"):
        draw_ladder_panel(ax, ACTORS, LadderPanel("bad", arrows=(LadderArrow(0, 9),)))
    plt.close(fig)


def test_build_wraps_panels_and_shares_labels():
    panels = [_panel(title=f"round {i}") for i in range(8)]
    fig = _build(
        ACTORS,
        panels,
        title="ladder",
        lane_alpha=0.25,
        inactive_alpha_scale=0.35,
        skip_label="skipped",
        marker_label="spoke",
        wrap=6,
        footnote="a note",
    )
    axes = fig.axes
    assert len(axes) == 12  # 2 rows x 6 cols
    assert sum(ax.get_visible() for ax in axes) == 8
    labels = [t.get_text() for t in axes[0].get_yticklabels()]
    assert labels == [a.label for a in ACTORS]
    assert all(not t.get_visible() for t in axes[1].get_yticklabels())  # sharey hides inner
    # panel-0 inactive actor greys in the shared label column
    assert axes[0].get_yticklabels()[2].get_color() == MUTED
    plt.close(fig)


def test_render_returns_png():
    png = render_lane_ladder(ACTORS, [_panel()], title="t", footnote="n")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_empty_raises():
    with pytest.raises(ValueError):
        render_lane_ladder([], [_panel()])
    with pytest.raises(ValueError):
        render_lane_ladder(ACTORS, [])
