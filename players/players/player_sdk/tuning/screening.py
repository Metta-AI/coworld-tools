"""Global sensitivity screening for knob surfaces: Morris -> LHS -> surrogate.

The tuning ladder that survived contact with a real (noisy, episodic)
evaluation budget:

1. **Morris elementary effects** (`morris_trajectories`, `elementary_effects`)
   — r trajectories x (k+1) one-at-a-time steps rank ALL knobs by mu*
   (mean |effect|) with sigma flagging interaction/nonlinearity, at r*(k+1)
   evaluations total. Use ONE shared seed batch for every configuration so
   each elementary effect is a paired difference.
2. **Maximin LHS** (`maximin_lhs`) over the shortlist that clears the noise
   floor — the space-filling design a kriging/GP response model wants.
3. **Compact GP** (`fit_gp`) — anisotropic RBF with per-point noise, MLE by
   random restarts (numpy-only; pass `minimize=scipy.optimize.minimize` for
   gradient polishing). Lengthscales are the interaction evidence; a
   suspiciously tiny lengthscale on one dim is the overfit tell — VERIFY
   surrogate optima on fresh evaluations before believing any of them.

Two field lessons encoded as advice, because they are cheap and repeatedly
paid for themselves:

- **Plant a negative control**: include one knob you KNOW is inert. Its
  mu* is your empirical noise floor; knobs that don't clear it are not
  resolvable at this budget, whatever their rank says.
- **Degenerate configurations must SCORE, never be skipped**: an evaluator
  that skips crashes/stalls hands the screen a hole exactly where the
  worst configs live.

Everything here is pure design/analysis math over the unit cube; mapping
unit coordinates onto real knob ranges belongs to the caller (see
`tuning.genome` for the dataclass-bounds route).
"""

from __future__ import annotations

import numpy as np

GRID_LEVELS = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
DELTA = 2.0 / 3.0


def morris_trajectories(k: int, r: int, *, seed: int = 0,
                        two_level: set[int] | None = None
                        ) -> list[list[tuple[int | None, list[float]]]]:
    """r trajectories over k unit-cube dims; each = [(stepped_dim, point)]
    with k+1 points, point 0 stepping nothing and every dim stepped exactly
    once thereafter. Dims in `two_level` (booleans, tiny enums) toggle
    0 <-> 1 instead of walking the p=4 grid."""
    rng = np.random.default_rng(seed)
    two = two_level or set()
    out = []
    for _ in range(r):
        base = [float(rng.integers(0, 2)) if d in two
                else float(rng.choice(GRID_LEVELS[:2])) for d in range(k)]
        order = rng.permutation(k)
        pts: list[tuple[int | None, list[float]]] = [(None, list(base))]
        cur = list(base)
        for d in map(int, order):
            step = 1.0 if d in two else DELTA
            nxt = list(cur)
            up_ok = cur[d] + step <= 1.0 + 1e-9
            down_ok = cur[d] - step >= -1e-9
            if up_ok and (not down_ok or rng.random() < 0.5):
                nxt[d] = min(1.0, cur[d] + step)
            else:
                nxt[d] = max(0.0, cur[d] - step)
            pts.append((d, nxt))
            cur = nxt
        out.append(pts)
    return out


def elementary_effects(trajs, fitness: dict[tuple[int, int], float],
                       reliable=lambda ti, si: True
                       ) -> dict[int, list[float]]:
    """Per-dim elementary effects from evaluated trajectories.

    fitness: {(traj_index, step_index): value}. Steps whose endpoints fail
    `reliable` are DROPPED (count them yourself — silent gaps read as
    coverage). Returns {dim: [effects...]}; summarize with mu*, sigma."""
    ees: dict[int, list[float]] = {}
    for ti, pts in enumerate(trajs):
        for si in range(1, len(pts)):
            d, cur = pts[si]
            _, prev = pts[si - 1]
            if d is None:
                continue
            if (ti, si) not in fitness or (ti, si - 1) not in fitness:
                continue
            if not (reliable(ti, si) and reliable(ti, si - 1)):
                continue
            du = cur[d] - prev[d]
            if abs(du) < 1e-12:
                continue
            ees.setdefault(d, []).append(
                (fitness[(ti, si)] - fitness[(ti, si - 1)]) / du)
    return ees


def mu_star_sigma(effects: list[float]) -> tuple[float, float]:
    if not effects:
        return 0.0, 0.0
    a = np.asarray(effects, dtype=float)
    mu = float(a.mean())
    sig = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    return float(np.abs(a).mean()), sig


def maximin_lhs(n: int, d: int, *, seed: int = 0, tries: int = 60
                ) -> np.ndarray:
    """Best-of-`tries` Latin hypercube by max min-pairwise-distance."""
    rng = np.random.default_rng(seed)
    best, best_score = None, -1.0
    for _ in range(tries):
        x = (rng.permuted(np.tile(np.arange(n), (d, 1)), axis=1).T
             + rng.random((n, d))) / n
        dm = np.sqrt(((x[:, None, :] - x[None, :, :]) ** 2).sum(-1))
        np.fill_diagonal(dm, np.inf)
        score = float(dm.min())
        if score > best_score:
            best, best_score = x, score
    return best


def fit_gp(X: np.ndarray, y: np.ndarray, noise_var: np.ndarray | float = 0.0,
           *, restarts: int = 24, seed: int = 0, minimize=None):
    """Anisotropic-RBF GP posterior mean. Returns (predict, params).

    noise_var: per-point observation variance (e.g. SEM**2) or scalar.
    MLE over log lengthscales / signal / extra nugget by random restarts;
    pass scipy.optimize.minimize as `minimize` to polish each restart."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, d = X.shape
    nv = (np.full(n, float(noise_var)) if np.isscalar(noise_var)
          else np.asarray(noise_var, dtype=float))
    ymu, ysd = float(y.mean()), float(y.std() or 1.0)
    ys = (y - ymu) / ysd
    nvs = nv / (ysd ** 2)

    def kern(A, B, ls, sf2):
        d2 = ((A[:, None, :] - B[None, :, :]) / ls) ** 2
        return sf2 * np.exp(-0.5 * d2.sum(-1))

    def nll(theta):
        ls = np.exp(theta[:d]); sf2 = np.exp(theta[d]); ng = np.exp(theta[d + 1])
        K = kern(X, X, ls, sf2) + np.diag(nvs + ng) + 1e-8 * np.eye(n)
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return 1e6
        a = np.linalg.solve(L.T, np.linalg.solve(L, ys))
        return float(0.5 * ys @ a + np.log(np.diag(L)).sum())

    rng = np.random.default_rng(seed)
    best_theta, best_v = None, np.inf
    for _ in range(restarts):
        t0 = np.concatenate([np.log(rng.uniform(0.2, 2.0, d)),
                             [np.log(rng.uniform(0.5, 2.0))],
                             [np.log(rng.uniform(0.01, 0.3))]])
        if minimize is not None:
            r = minimize(nll, t0, method="L-BFGS-B")
            t0, v = r.x, r.fun
        else:
            v = nll(t0)
        if v < best_v:
            best_theta, best_v = t0, v
    ls = np.exp(best_theta[:d]); sf2 = np.exp(best_theta[d])
    ng = np.exp(best_theta[d + 1])
    K = kern(X, X, ls, sf2) + np.diag(nvs + ng) + 1e-8 * np.eye(n)
    L = np.linalg.cholesky(K)
    alpha = np.linalg.solve(L.T, np.linalg.solve(L, ys))

    def predict(Q):
        Q = np.atleast_2d(np.asarray(Q, dtype=float))
        return (kern(Q, X, ls, sf2) @ alpha) * ysd + ymu

    return predict, {"lengthscales": ls.tolist(), "sf2": float(sf2),
                     "nugget": float(ng), "nll": float(best_v)}
