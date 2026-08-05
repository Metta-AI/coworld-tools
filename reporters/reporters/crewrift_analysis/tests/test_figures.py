"""Tests for the four figures: measure the rendered anatomy, not just exit."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("matplotlib")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import to_hex  # noqa: E402
from matplotlib.patches import Circle  # noqa: E402

from crewrift_analysis.events import CrewriftLogError, parse_episode  # noqa: E402
from crewrift_analysis.figures import (  # noqa: E402
    build_fog_of_war,
    build_missed_blend,
    contrast_footnotes,
    contrast_rows,
    ladder_inputs,
    missed_blend_windows,
    render_contrast_table,
    render_fog_of_war,
    render_missed_blend,
    render_vote_ladder,
)
from crewrift_analysis.metrics import AXES, aggregate_contrast  # noqa: E402
from episode_analysis.palette import NEGATIVE, PRIMARY  # noqa: E402

MAP_ASPECT = 1235 / 659


# --- missed blend -----------------------------------------------------------


def test_missed_blend_windows_exact(episode):
    windows = missed_blend_windows(episode, 0)
    assert len(windows) == 2
    first, second = windows
    assert (first.start, first.end) == (99, 162)  # fully unwatched station visit
    assert (first.cx, first.cy) == (pytest.approx(143.5), pytest.approx(407.0))
    # The second visit ran to tick 240 but obs 1 watched from 200: truncated.
    assert (second.start, second.end) == (180, 198)
    assert (second.cx, second.cy) == (pytest.approx(163.0), pytest.approx(407.0))


def test_missed_blend_windows_crew_and_errors(episode):
    assert missed_blend_windows(episode, 1) == []  # never near a station
    with pytest.raises(CrewriftLogError):
        missed_blend_windows(episode, 99)


def test_build_missed_blend_anatomy(episode):
    fig = build_missed_blend(episode, 0)
    ax = fig.axes[0]
    fig.canvas.draw()

    discs = [p for p in ax.patches if isinstance(p, Circle)]
    assert len(discs) == 2
    assert len(ax.collections) == 4  # stations, vents, kill casing, kill core
    assert len(ax.collections[0].get_offsets()) == 41
    assert len(ax.collections[1].get_offsets()) == 11
    assert len(ax.lines) == 2  # one path run per Playing span, never across meetings
    assert ax.get_legend() is not None

    bbox = ax.get_window_extent()
    assert bbox.width / bbox.height == pytest.approx(MAP_ASPECT, rel=0.03)
    assert bbox.width >= 0.9 * fig.bbox.width  # the map fills the canvas

    captions = [t.get_text() for t in fig.texts]
    assert any("2 windows" in c for c in captions)
    plt.close(fig)


def test_build_missed_blend_crew_slot_no_kills(episode):
    fig = build_missed_blend(episode, 1)
    ax = fig.axes[0]
    assert len(ax.collections) == 2  # stations + vents only
    assert any("0 windows" in t.get_text() for t in fig.texts)
    plt.close(fig)


def test_missed_blend_ndarray_backdrop_and_png(episode):
    backdrop = np.full((66, 124, 3), 0.5)
    fig = build_missed_blend(episode, 0, map_image=backdrop)
    assert len(fig.axes[0].images) == 1
    plt.close(fig)
    png = render_missed_blend(episode, 0)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


# --- fog of war -------------------------------------------------------------


def test_fog_panels_and_veil(episode):
    fig = build_fog_of_war(episode, 1)
    assert len(fig.axes) == 4  # 2 maps + 2 chip rows
    map1, chips1, map2, chips2 = fig.axes
    fig.canvas.draw()
    for map_ax in (map1, map2):
        veil = map_ax.patches[0]
        assert veil.get_alpha() == pytest.approx(0.86)
        assert to_hex(veil.get_facecolor()) == "#07090c"
        bbox = map_ax.get_window_extent()
        assert bbox.width / bbox.height == pytest.approx(MAP_ASPECT, rel=0.03)
    # Panel titles live inside the map axes.
    assert any("Playing phase 1" in t.get_text() for t in map1.texts)
    assert any("Playing phase 2" in t.get_text() for t in map2.texts)
    # Observer path (glow+casing+core+start) plus one seen-player run each.
    assert len(map1.lines) == 5
    assert len(map2.lines) == 5
    assert len(map1.collections) == 1  # batched last-seen dots
    plt.close(fig)


def test_fog_chip_rows(episode):
    fig = build_fog_of_war(episode, 1)
    _, chips1, _, chips2 = fig.axes
    for chip_ax in (chips1, chips2):
        assert len(chip_ax.patches) == 6  # 5 swatches + observer backing
        texts = [t.get_text() for t in chip_ax.texts]
        assert len(texts) == 6  # header + 5 chips
        assert texts[0] == "1 of 4 seen"  # variable roster, never "of 7"
        assert texts[1] == "blue · observer"  # the viewpoint chip comes first
        assert any("never seen" in t for t in texts)  # absence is information
    # Phase 1: obs 1 saw red for [200,240] -> 41 ticks ~ 2s at 24/s.
    assert any("red · 2s" in t.get_text() for t in chips1.texts)
    plt.close(fig)


def test_fog_never_encodes_roles(episode):
    fig = build_fog_of_war(episode, 1)
    for ax in fig.axes:
        for line in ax.lines:
            assert to_hex(line.get_color()) != NEGATIVE
    plt.close(fig)


def test_fog_observer_dead_panel(episode):
    fig = build_fog_of_war(episode, 4)  # murdered at tick 250
    map2 = fig.axes[2]
    assert any("observer dead this phase" in t.get_text() for t in map2.texts)
    chips1 = fig.axes[1]
    assert chips1.texts[0].get_text() == "0 of 4 seen"  # slot 4 observed nobody
    plt.close(fig)


def test_fog_validation_and_png(episode):
    with pytest.raises(ValueError, match="unknown observer"):
        build_fog_of_war(episode, 99)
    with pytest.raises(ValueError, match="does not exist"):
        build_fog_of_war(episode, 1, phases=[9])
    png = render_fog_of_war(episode, 1, phases=[1])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


# --- vote ladder ------------------------------------------------------------


def test_ladder_inputs(episode):
    actors, panels, footnote = ladder_inputs(episode)
    assert [a.label for a in actors] == ["red(0)", "blue(1)", "green(2)", "orange(3)", "cyan(4)"]
    assert [a.color for a in actors] == [NEGATIVE, PRIMARY, PRIMARY, PRIMARY, PRIMARY]

    p1, p2 = panels
    assert p1.title == "meeting 1 (body)"
    assert [(a.src, a.dst, a.label) for a in p1.arrows] == [(1, 0, "1"), (0, 1, "2"), (3, 0, "4")]
    assert p1.skips == (2,)
    assert p1.marked == (1,)  # spoke at 322, voted at 330
    assert p1.inactive == (4,)  # murdered before the meeting

    assert p2.title == "meeting 2 (button)"
    assert [(a.src, a.dst, a.label) for a in p2.arrows] == [(1, 0, "1"), (2, 0, "2"), (0, 3, "4")]
    assert p2.skips == (3,)
    assert p2.marked == (0,)  # the imposter spoke at 710, voted at 755
    assert p2.inactive == (4,)

    assert "0 of 2 imposter votes" in footnote


def test_ladder_requires_meetings(lines):
    quiet = [
        ln
        for ln in lines
        if not any(f'"{p}"' in ln for p in ("MeetingCall", "Voting", "VoteResult"))
    ]
    ep = parse_episode(quiet, episode_id="quiet")
    with pytest.raises(ValueError, match="no meetings"):
        ladder_inputs(ep)


def test_render_vote_ladder_png(episode):
    png = render_vote_ladder(episode)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


# --- contrast table ---------------------------------------------------------


def test_contrast_rows_and_footnotes(episode):
    contrasts = aggregate_contrast([episode, episode])
    rows = contrast_rows(contrasts)
    assert [r.label for r in rows] == [ax.label for ax in AXES]
    occ = rows[0]
    assert occ.mean_b == 0.0  # imposter mean
    assert math.isfinite(occ.auc)

    exclusion, counts = contrast_footnotes(contrasts, n_episodes=2)
    assert "zero tasks" in exclusion
    assert "2 episodes" in counts and "8 crew" in counts and "2 imposter" in counts


def test_render_contrast_table_png(episode):
    png = render_contrast_table(aggregate_contrast([episode]), n_episodes=1)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
