"""Scenario tests for players.player_sdk.nav_grid (distance).

Ported 1:1 from the embedded smoke test of the original ``swgy_distance.py``
(sm-policies SWGY-Nav bundle). The numbered scenario comments and the
``check(label, ...)`` assertion labels are preserved verbatim so failures
map straight back to the origin scenarios.
"""

from __future__ import annotations

from players.player_sdk.nav_grid.distance import (
    BUMP_TARGET_RANGE_METRIC,
    JUNCTION_ALIGN_RANGE_METRIC,
    NAV_HEURISTIC_METRIC,
    chebyshev,
    euclidean,
    euclidean_sq,
    manhattan,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_distance_smoke_scenarios() -> None:

    # 1. manhattan basics
    check("1 manhattan zero", manhattan((0, 0), (0, 0)) == 0)
    check("1b manhattan symmetric", manhattan((3, 4), (0, 0)) == manhattan((0, 0), (3, 4)))
    check("1c manhattan axis", manhattan((0, 0), (3, 0)) == 3)
    check("1d manhattan diagonal", manhattan((0, 0), (3, 4)) == 7)

    # 2. chebyshev basics
    check("2 chebyshev zero", chebyshev((0, 0), (0, 0)) == 0)
    check("2b chebyshev king-move", chebyshev((0, 0), (1, 1)) == 1)
    check("2c chebyshev axis equals manhattan", chebyshev((0, 0), (3, 0)) == 3)
    check("2d chebyshev diagonal less than manhattan",
          chebyshev((0, 0), (3, 4)) == 4 and manhattan((0, 0), (3, 4)) == 7)

    # 3. euclidean_sq basics
    check("3 euclidean_sq zero", euclidean_sq((0, 0), (0, 0)) == 0)
    check("3b euclidean_sq 3-4-5", euclidean_sq((0, 0), (3, 4)) == 25)
    check("3c euclidean_sq integer", isinstance(euclidean_sq((1, 2), (3, 4)), int))

    # 4. euclidean float
    check("4 euclidean 3-4-5", abs(euclidean((0, 0), (3, 4)) - 5.0) < 1e-9)
    check("4b euclidean float type", isinstance(euclidean((0, 0), (1, 1)), float))

    # 5. Symmetry & non-negativity
    for a, b in [((0, 0), (5, 7)), ((-3, 2), (4, -1)), ((10, 10), (10, 10))]:
        check(f"5 manhattan symmetric {a},{b}", manhattan(a, b) == manhattan(b, a))
        check(f"5b chebyshev symmetric {a},{b}", chebyshev(a, b) == chebyshev(b, a))
        check(f"5c euclidean_sq symmetric {a},{b}", euclidean_sq(a, b) == euclidean_sq(b, a))
        check(f"5d manhattan nonneg {a},{b}", manhattan(a, b) >= 0)
        check(f"5e chebyshev nonneg {a},{b}", chebyshev(a, b) >= 0)
        check(f"5f euclidean_sq nonneg {a},{b}", euclidean_sq(a, b) >= 0)

    # 6. Triangle / metric ordering: chebyshev <= euclidean <= manhattan
    #    (always true on integer 2D grids).
    for pts in [((0, 0), (3, 4)), ((1, 1), (-2, 5)), ((0, 0), (7, 0)),
                ((0, 0), (5, 5))]:
        a, b = pts
        m = manhattan(a, b)
        c = chebyshev(a, b)
        e = euclidean(a, b)
        check(f"6 cheby <= eucl <= manh on {pts}", c <= e <= m + 1e-9,
              f"c={c} e={e} m={m}")

    # 7. euclidean_sq matches euclidean^2 within float tolerance.
    for a, b in [((0, 0), (3, 4)), ((-7, 2), (5, -3)), ((0, 0), (1, 1))]:
        sq = euclidean_sq(a, b)
        e = euclidean(a, b)
        check(f"7 euclidean_sq == euclidean^2 {a},{b}", abs(sq - e * e) < 1e-9)

    # 8. Range-gate idiom: euclidean_sq(a, b) <= R*R is exact.
    R = 14
    # Cells exactly at distance R along an axis: in range.
    check("8 axis at R in range", euclidean_sq((0, 0), (0, R)) <= R * R)
    # Cell at distance R+1 along axis: out of range.
    check("8b axis at R+1 out of range", euclidean_sq((0, 0), (0, R + 1)) > R * R)
    # Diagonal cell at distance > R: out of range. sqrt(10^2 + 10^2) ~ 14.14 > 14.
    check("8c diagonal slightly over: out", euclidean_sq((0, 0), (10, 10)) > R * R)
    # Diagonal cell at distance < R: in range. sqrt(9^2 + 9^2) ~ 12.7 < 14.
    check("8d diagonal under: in", euclidean_sq((0, 0), (9, 9)) <= R * R)

    # 9. Env-truth metric constants are recognized strings.
    check("9 align metric is euclidean", JUNCTION_ALIGN_RANGE_METRIC == "euclidean")
    check("9b bump metric is manhattan", BUMP_TARGET_RANGE_METRIC == "manhattan")
    check("9c nav heuristic is manhattan", NAV_HEURISTIC_METRIC == "manhattan")
