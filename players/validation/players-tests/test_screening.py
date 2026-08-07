import numpy as np

from players.player_sdk.tuning.screening import (
    elementary_effects, fit_gp, maximin_lhs, morris_trajectories,
    mu_star_sigma)


def test_trajectories_step_every_dim_exactly_once():
    trajs = morris_trajectories(k=7, r=4, seed=3, two_level={2, 5})
    assert len(trajs) == 4
    for pts in trajs:
        assert len(pts) == 8
        stepped = set()
        for i in range(1, len(pts)):
            d, cur = pts[i]
            _, prev = pts[i - 1]
            diffs = [j for j in range(7) if abs(cur[j] - prev[j]) > 1e-12]
            assert diffs == [d]
            stepped.add(d)
            assert 0.0 <= cur[d] <= 1.0
        assert stepped == set(range(7))


def test_elementary_effects_recover_linear_slopes():
    k, r = 4, 6
    trajs = morris_trajectories(k, r, seed=1)
    w = np.array([2.0, -1.0, 0.0, 0.5])
    fitness = {}
    for ti, pts in enumerate(trajs):
        for si, (_d, u) in enumerate(pts):
            fitness[(ti, si)] = float(w @ np.array(u))
    ees = elementary_effects(trajs, fitness)
    for d in range(k):
        ms, sg = mu_star_sigma(ees[d])
        assert abs(ms - abs(w[d])) < 1e-9      # exact on a linear surface
        assert sg < 1e-9


def test_elementary_effects_drop_unreliable_endpoints():
    trajs = morris_trajectories(3, 2, seed=0)
    fitness = {(ti, si): 0.0 for ti, pts in enumerate(trajs)
               for si in range(len(pts))}
    ees_all = elementary_effects(trajs, fitness)
    ees_cut = elementary_effects(trajs, fitness,
                                 reliable=lambda ti, si: ti != 0)
    assert sum(map(len, ees_cut.values())) < sum(map(len, ees_all.values()))


def test_maximin_lhs_is_latin_and_spread():
    x = maximin_lhs(20, 3, seed=5)
    assert x.shape == (20, 3)
    for d in range(3):
        bins = np.floor(x[:, d] * 20).astype(int)
        assert sorted(bins) == list(range(20))   # one point per stratum


def test_gp_recovers_smooth_optimum():
    rng = np.random.default_rng(2)
    X = maximin_lhs(60, 2, seed=2)
    def f(q):
        return -((q[..., 0] - 0.7) ** 2) - 2 * (q[..., 1] - 0.3) ** 2
    y = f(X) + rng.normal(0, 0.01, len(X))
    predict, params = fit_gp(X, y, noise_var=0.01 ** 2, restarts=12, seed=2)
    grid = np.stack(np.meshgrid(np.linspace(0, 1, 41),
                                np.linspace(0, 1, 41)), -1).reshape(-1, 2)
    best = grid[int(np.argmax(predict(grid)))]
    assert abs(best[0] - 0.7) < 0.08 and abs(best[1] - 0.3) < 0.08
    assert len(params["lengthscales"]) == 2
