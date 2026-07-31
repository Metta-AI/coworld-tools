"""Paired A/B statistics for episode metrics.

The one statistical kernel both origin harnesses used: paired differences
with a Student-t 95% CI, a seeded bootstrap CI, a win rate, and a one-word
verdict. Plus a plain mean±CI for unpaired summaries.

Origin: merged from Ron Dahlgren's (swgy) tooling — the nav-ablation
harness's ``_paired_stats``/``_verdict`` (swgy-crewrift
``navbench/bench.py``) and the eval aggregator's ``stats`` (sm-policies
``aggregate_paired.py``). The game-specific metric extraction did not port.
"""

from __future__ import annotations

import numpy as np

__all__ = ["mean_ci", "paired_stats", "verdict"]

# Student-t two-sided 95% critical values by degrees of freedom. Small table
# on purpose: paired runs in practice have n in the tens to low hundreds;
# everything else falls back to the asymptotic-ish 1.984.
_T_975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021,
    60: 2.000, 99: 1.9842,
}


def _t_crit(df: int) -> float:
    if df in _T_975:
        return _T_975[df]
    smaller = [k for k in _T_975 if k <= df]
    return _T_975[max(smaller)] if smaller else _T_975[1]


def paired_stats(
    base: list[float], cand: list[float], rng: np.random.Generator | None = None
) -> dict:
    """Paired-difference stats: ``d = base - cand`` (positive ⇒ candidate
    improved, when lower-is-better, e.g. travel ticks).

    Returns ``n``, ``mean_before``/``mean_after``, ``mean_improvement``,
    ``pct_improvement``, ``t_ci``/``boot_ci`` (both 95%), and ``win_rate``.
    Pass a seeded ``rng`` for reproducible bootstrap CIs.
    """
    if len(base) != len(cand):
        raise ValueError(f"paired lengths differ: {len(base)} vs {len(cand)}")
    if not base:
        raise ValueError("paired_stats needs at least one pair")
    if rng is None:
        rng = np.random.default_rng(0)
    b = np.array(base, dtype=float)
    c = np.array(cand, dtype=float)
    d = b - c
    n = len(d)
    mean = float(d.mean())
    se = float(d.std(ddof=1)) / np.sqrt(n) if n > 1 else float("inf")
    t = _t_crit(n - 1)
    t_ci = (mean - t * se, mean + t * se)
    boot = rng.choice(d, size=(10_000, n), replace=True).mean(axis=1)
    boot_ci = tuple(float(x) for x in np.percentile(boot, [2.5, 97.5]))
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(b != 0, d / b, 0.0)
    return {
        "n": n,
        "mean_before": float(b.mean()),
        "mean_after": float(c.mean()),
        "mean_improvement": mean,
        "pct_improvement": float(pct.mean() * 100.0),
        "t_ci": t_ci,
        "boot_ci": boot_ci,
        "win_rate": float((d > 0).mean() * 100.0),
    }


def verdict(stats: dict, improved: str = "IMPROVED (sig)", worse: str = "worse (sig)") -> str:
    """One-word significance call at alpha=0.05 off the t-CI: ``improved``
    when the CI excludes 0 from below, ``worse`` when from above, else
    ``"ns"``."""
    lo, hi = stats["t_ci"]
    if lo > 0:
        return improved
    if hi < 0:
        return worse
    return "ns"


def mean_ci(vals: list[float]) -> tuple[float, float, float]:
    """``(mean, sd, ci_half_width)`` with a Student-t 95% half-width.

    ``(nan, nan, nan)`` on empty input; ``ci`` is ``nan`` for a single value.
    """
    n = len(vals)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    a = np.array(vals, dtype=float)
    m = float(a.mean())
    if n > 1:
        sd = float(a.std(ddof=1))
        ci = _t_crit(n - 1) * sd / np.sqrt(n)
    else:
        sd = 0.0
        ci = float("nan")
    return m, sd, float(ci)
