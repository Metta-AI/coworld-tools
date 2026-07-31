"""Tests for heatmap binning/blur, paired stats, and tour routing."""

from __future__ import annotations

import math

import numpy as np
import pytest

from episode_analysis.heatmap import accumulate_by_group, bin_positions, gaussian_blur, total_grid
from episode_analysis.routing import TourComparison, optimal_open_tour, pairwise_costs, path_cost
from episode_analysis.stats import mean_ci, paired_stats, verdict

# --- heatmap ----------------------------------------------------------------


def test_bin_positions_counts_and_clamps():
    grid = bin_positions([(0, 0), (0, 0), (2, 1), (99, 99)], width=3, height=2)
    assert grid.shape == (2, 3)
    assert grid[0, 0] == 2
    assert grid[1, 2] == 2  # (2,1) plus the out-of-bounds sample clamped to the corner
    assert grid.sum() == 4


def test_bin_positions_cell_size():
    grid = bin_positions([(0, 0), (9, 9)], width=10, height=10, cell=5)
    assert grid.shape == (2, 2)
    assert grid[0, 0] == 1 and grid[1, 1] == 1


def test_accumulate_by_group_and_total():
    grids = accumulate_by_group(
        [(0, 0, "crew"), (1, 0, "crew"), (0, 1, "imposter")], width=2, height=2
    )
    assert set(grids) == {"crew", "imposter"}
    assert grids["crew"].sum() == 2 and grids["imposter"].sum() == 1
    assert total_grid(grids).sum() == 3
    assert total_grid({}).sum() == 0


def test_gaussian_blur_conserves_mass_and_noops():
    g = np.zeros((9, 9))
    g[4, 4] = 100.0
    blurred = gaussian_blur(g, sigma=1.0)
    assert blurred[4, 4] < 100.0  # spread out
    assert blurred.sum() == pytest.approx(100.0, rel=1e-6)  # mass conserved
    assert gaussian_blur(g, sigma=0) is g


def test_gaussian_blur_preserves_shape_on_tiny_grids():
    # Kernel longer than the axis: naive mode="same" convolution GROWS the
    # grid (returns max(M, N)); the centred full-mode slice must not.
    tiny = np.zeros((3, 2))
    tiny[1, 1] = 9.0
    out = gaussian_blur(tiny, sigma=2.0)  # radius 6 > both axes
    assert out.shape == tiny.shape


# --- stats --------------------------------------------------------------------


def test_paired_stats_hand_computed():
    base = [10.0, 12.0, 11.0, 13.0]
    cand = [8.0, 11.0, 9.0, 12.0]  # d = [2, 1, 2, 1], mean 1.5
    s = paired_stats(base, cand, rng=np.random.default_rng(7))
    assert s["n"] == 4
    assert s["mean_improvement"] == pytest.approx(1.5)
    assert s["mean_before"] == pytest.approx(11.5)
    assert s["mean_after"] == pytest.approx(10.0)
    assert s["win_rate"] == 100.0
    # d sd = 0.577..., se = 0.2887, t(3) = 3.182 -> half-width ~0.919
    lo, hi = s["t_ci"]
    assert lo == pytest.approx(1.5 - 3.182 * (np.std([2, 1, 2, 1], ddof=1) / 2), rel=1e-3)
    assert verdict(s) == "IMPROVED (sig)"


def test_paired_stats_bootstrap_deterministic_with_seed():
    base, cand = [5.0, 6.0, 7.0, 8.0], [5.5, 5.5, 7.5, 7.0]
    a = paired_stats(base, cand, rng=np.random.default_rng(42))
    b = paired_stats(base, cand, rng=np.random.default_rng(42))
    assert a["boot_ci"] == b["boot_ci"]


def test_verdict_directions():
    worse = paired_stats([1.0, 1.0, 1.0], [2.0, 2.1, 1.9], rng=np.random.default_rng(0))
    assert verdict(worse) == "worse (sig)"
    ns = paired_stats([1.0, 3.0, 2.0], [2.0, 1.0, 3.0], rng=np.random.default_rng(0))
    assert verdict(ns) == "ns"


def test_paired_stats_validates_input():
    with pytest.raises(ValueError):
        paired_stats([1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        paired_stats([], [])


def test_mean_ci():
    m, sd, ci = mean_ci([2.0, 4.0, 6.0])
    assert m == pytest.approx(4.0)
    assert sd == pytest.approx(2.0)
    assert ci == pytest.approx(4.303 * 2.0 / math.sqrt(3), rel=1e-3)
    assert all(math.isnan(v) for v in mean_ci([]))
    m1, sd1, ci1 = mean_ci([5.0])
    assert m1 == 5.0 and sd1 == 0.0 and math.isnan(ci1)


# --- routing ---------------------------------------------------------------------


def _matrix_where_greedy_loses() -> list[list[float]]:
    # Points on a line: start 0 at x=0, stop 1 at x=1, stop 2 at x=-1.5,
    # stop 3 at x=2.5. Nearest-neighbour from 0 picks 1, then 3, then pays
    # the long walk back to 2 (1 + 1.5 + 4 = 6.5); optimal clears the
    # left flank first: 2 -> 1 -> 3 = 1.5 + 2.5 + 1.5 = 5.5.
    return [
        [0.0, 1.0, 1.5, 2.5],
        [1.0, 0.0, 2.5, 1.5],
        [1.5, 2.5, 0.0, 4.0],
        [2.5, 1.5, 4.0, 0.0],
    ]


def test_optimal_open_tour_beats_greedy():
    dist = _matrix_where_greedy_loses()
    order, cost = optimal_open_tour(dist)
    greedy_cost = path_cost(dist, [1, 3, 2])  # nearest-neighbour: 1 + 1.5 + 4
    assert greedy_cost == pytest.approx(6.5)
    assert cost == pytest.approx(5.5)
    assert cost < greedy_cost
    assert order == [2, 1, 3]
    assert cost == pytest.approx(path_cost(dist, order))


def test_optimal_open_tour_edge_cases():
    assert optimal_open_tour([[0.0]]) == ([], 0.0)
    order, cost = optimal_open_tour([[0.0, 3.0], [3.0, 0.0]])
    assert order == [1] and cost == 3.0


def test_tour_comparison_excess_never_negative():
    dist = _matrix_where_greedy_loses()
    cmp = TourComparison.score(dist, visited=[1, 2, 3])
    assert cmp.excess >= 0
    assert cmp.actual_cost == pytest.approx(1.0 + 2.5 + 4.0)
    assert cmp.ratio >= 1.0
    perfect = TourComparison.score(dist, visited=list(cmp.optimal))
    assert perfect.excess == pytest.approx(0.0)


def test_pairwise_costs_uses_and_fills_cache():
    calls = []

    def cost_fn(a, b):
        calls.append((a, b))
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    points = [(0, 0), (3, 0), (0, 4)]
    cache: dict = {}
    d1 = pairwise_costs(points, cost_fn, cache)
    assert d1[0][1] == 3 and d1[0][2] == 4 and d1[1][2] == 7
    n_calls = len(calls)
    d2 = pairwise_costs(points, cost_fn, cache)  # all cache hits
    assert d2 == d1
    assert len(calls) == n_calls
