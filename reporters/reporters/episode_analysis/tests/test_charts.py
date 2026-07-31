"""Chart smoke tests: render to PNG bytes, assert magic + parseable size.

matplotlib is optional (the [charts] extra); everything here skips cleanly
without it.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

pytest.importorskip("matplotlib")

from episode_analysis.charts import (  # noqa: E402
    Band,
    Lane,
    Marker,
    colored_path,
    density_layer,
    draw_track,
    mean_layer,
    render_heatmap,
    render_swimlanes,
    sample_track,
    share_layer,
)
from episode_analysis.heatmap import bin_positions  # noqa: E402


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def test_density_layer_and_render():
    grid = bin_positions([(1, 1), (1, 1), (5, 3), (8, 2)], width=10, height=6)
    layer = density_layer(grid)
    assert layer is not None
    rgba, norm, cmap = layer
    assert rgba.shape == (6, 10, 4)
    png = render_heatmap(
        layer,
        title="occupancy",
        cbar_label="samples (log)",
        width=10,
        height=6,
        landmarks=[(2.0, 2.0, "s", "station")],
    )
    w, h = _png_size(png)
    assert w > 100 and h > 100
    assert density_layer(np.zeros((4, 4))) is None


def test_share_layer_centres_on_base_rate():
    a = np.zeros((4, 4))
    a[0, 0] = 30
    b = np.zeros((4, 4))
    b[0, 0] = 10
    b[3, 3] = 10
    layer = share_layer(a, b, base_rate=0.25)
    assert layer is not None
    rgba, norm, cmap = layer
    assert norm.vcenter == 0.25
    assert rgba[..., 3].max() > 0
    with pytest.raises(ValueError):
        share_layer(a, b, base_rate=1.5)
    assert share_layer(np.zeros((2, 2)), np.zeros((2, 2))) is None


def test_mean_layer():
    total = np.zeros((4, 4))
    count = np.zeros((4, 4))
    total[1, 1] = 300.0
    count[1, 1] = 3
    layer = mean_layer(total, count)
    assert layer is not None
    assert mean_layer(np.zeros((2, 2)), np.zeros((2, 2))) is None


def test_render_swimlanes_shapes():
    lanes = [
        Lane(
            label="ep-1  3/8",
            end_tick=1000,
            markers=[Marker(100, "1"), Marker(105, "2"), Marker(400, "3", alt=True)],
            bands=[Band(200, 300), Band(600, 700, emphasized=True)],
            cross_tick=500,
        ),
        Lane(label="ep-2  0/8", end_tick=5000),  # runs far past the last event
    ]
    png = render_swimlanes(lanes, title="tasks per episode")
    w, h = _png_size(png)
    assert w > 200 and h > 100


def test_render_swimlanes_empty_lane_list_is_safe():
    png = render_swimlanes([])
    assert _png_size(png)[0] > 0


def test_sample_and_draw_track_and_ribbon():
    import matplotlib.pyplot as plt

    track = {t: (float(t), 5.0) for t in range(0, 100, 10)}
    track.pop(50)  # a hole: teleport/meeting
    samples = sample_track(track, end_tick=90, window_ticks=90, step=10)
    assert samples[0][0] == 0 and samples[-1][0] == 90
    assert all(t != 50 for t, _, _ in samples)

    fig, ax = plt.subplots()
    draw_track(ax, samples, color="#3987e5", step=10)
    # Stationary run collapses to a single +:
    still = [(0, 3.0, 3.0), (10, 3.0, 3.0), (20, 3.0, 3.0), (30, 4.0, 3.0)]
    draw_track(ax, still, color="#c98500", step=10)
    lc = colored_path(ax, [(0, 0), (1, 1), (2, 0)], [0.0, 0.5, 1.0])
    assert lc.get_array().shape == (2,)
    with pytest.raises(ValueError):
        colored_path(ax, [(0, 0), (1, 1)], [1.0])
    plt.close(fig)
