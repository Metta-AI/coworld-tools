"""Tests for the two-group contrast table chart."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("matplotlib")

import matplotlib.pyplot as plt  # noqa: E402

from episode_analysis.charts.contrast import (  # noqa: E402
    ContrastRow,
    _build,
    draw_contrast_table,
    render_contrast_table,
)
from episode_analysis.palette import INK, MUTED  # noqa: E402

NAN = float("nan")


def _rows():
    # separations: 0.8, 0.6 (B higher), 0.2 (A higher), 0.0
    return [
        ContrastRow("quiet axis", 1.0, 1.1, 0.5),
        ContrastRow("loud axis", 0.1, 0.9, 0.9),
        ContrastRow("reverse axis", 5.0, 2.0, 0.4),
        ContrastRow("mid axis", 2.0, 3.0, 0.8),
    ]


def _draw(rows, **kwargs):
    fig, ax = plt.subplots()
    try:
        drawn = draw_contrast_table(ax, rows, group_a="A mean", group_b="B mean", **kwargs)
        return fig, ax, drawn
    except Exception:
        plt.close(fig)
        raise


def test_draw_counts_and_sort_order():
    fig, ax, drawn = _draw(_rows())
    assert [r.label for r in drawn] == ["loud axis", "mid axis", "reverse axis", "quiet axis"]
    n = 4
    n_bars = 3  # the 0-separation row draws no fill
    assert len(ax.patches) == n // 2 + n + n_bars
    assert len(ax.texts) == 3 + 5 * n
    plt.close(fig)


def test_emphasis_split():
    fig, ax, drawn = _draw(_rows(), emphasis_threshold=0.5)
    label_texts = {t.get_text(): t for t in ax.texts}
    assert label_texts["loud axis"].get_color() == INK
    assert label_texts["loud axis"].get_fontweight() == "bold"
    assert label_texts["reverse axis"].get_color() == MUTED
    assert label_texts["reverse axis"].get_fontweight() == "normal"
    plt.close(fig)


def test_direction_markers_and_nan():
    rows = [
        ContrastRow("up", 0.0, 1.0, 0.9),
        ContrastRow("down", 1.0, 0.0, 0.1),
        ContrastRow("undefined", NAN, 1.0, NAN),
    ]
    fig, ax, drawn = _draw(rows, color_a="#111111", color_b="#222222")
    glyphs = {t.get_text(): t for t in ax.texts}
    assert glyphs["▲"].get_color() == "#222222"
    assert glyphs["▼"].get_color() == "#111111"
    assert glyphs["·"].get_color() == MUTED
    # NaN mean and NaN separation render the placeholder; no bar fill for them
    assert sum(t.get_text() == "–" for t in ax.texts) == 2
    assert len(ax.patches) == 1 + 3 + 2  # zebra + tracks + fills (up, down only)
    plt.close(fig)


def test_unsorted_keeps_caller_order():
    fig, ax, drawn = _draw(_rows(), sort=False)
    assert [r.label for r in drawn] == [r.label for r in _rows()]
    plt.close(fig)


def test_empty_rows_raise():
    fig, ax = plt.subplots()
    with pytest.raises(ValueError):
        draw_contrast_table(ax, [], group_a="a", group_b="b")
    plt.close(fig)


def test_build_wraps_footnotes():
    long_note = "word " * 60  # ~300 chars, must wrap into several lines
    fig = _build(
        _rows(),
        title="t",
        group_a="a",
        group_b="b",
        color_a="#111111",
        color_b="#222222",
        emphasis_threshold=0.5,
        footnotes=(long_note.strip(),),
        footnote_wrap=95,
        sort=True,
    )
    footer = [t for t in fig.texts if "word" in t.get_text()]
    assert len(footer) == 1
    assert len(footer[0].get_text().splitlines()) >= 3
    plt.close(fig)


def test_render_returns_png():
    png = render_contrast_table(
        _rows(), title="contrast", group_a="a", group_b="b", footnotes=("note one", "note two")
    )
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 5_000


def test_separation_property():
    assert ContrastRow("x", 0, 0, 0.9).separation == pytest.approx(0.8)
    assert math.isnan(ContrastRow("x", 0, 0, NAN).separation)
