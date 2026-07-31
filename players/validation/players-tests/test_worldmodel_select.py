"""Scenario tests for players.player_sdk.worldmodel (select).

Ported 1:1 from the embedded smoke test of the original ``swgy_select.py``
(sm-policies scripted stack). Scenario comments and ``check`` labels are
preserved verbatim.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.select import (
    make_unclaimed_filter,
    select_with_relaxation,
    tiered_select_with_relaxation,
)


def check(label: str, cond: bool, detail: str = "") -> None:
    """Assertion helper preserved from the original smoke tests: the label
    pinpoints the failing scenario."""
    assert cond, f"FAIL {label}: {detail}"


def test_select_smoke_scenarios() -> None:

    # Candidates: (id, score, has_claim, exhausted, in_range).
    # Lower score wins. Filters: in_range (essential), no_claim, fresh.
    Cand = tuple[int, int, bool, bool, bool]

    def in_range(c: Cand) -> bool:
        return c[4]

    def no_claim(c: Cand) -> bool:
        return not c[2]

    def fresh(c: Cand) -> bool:
        return not c[3]

    def by_score(c: Cand) -> int:
        return c[1]

    # Filter order: most-essential first.
    filters = [in_range, no_claim, fresh]

    # 1. All filters pass: best score wins.
    cands: list[Cand] = [
        (1, 50, False, False, True),
        (2, 30, False, False, True),  # best
        (3, 40, False, False, True),
    ]
    pick = select_with_relaxation(cands, by_score, filters)
    check("1 all filters pass best score", pick is not None and pick[0] == 2, f"got {pick}")

    # 2. First pass empty (everyone exhausted), second pass has winners.
    cands = [
        (1, 50, False, True, True),
        (2, 30, False, True, True),  # best after dropping 'fresh'
        (3, 40, False, True, True),
    ]
    pick = select_with_relaxation(cands, by_score, filters)
    check("2 relax fresh", pick is not None and pick[0] == 2, f"got {pick}")

    # 3. First two passes empty (claimed AND exhausted), third pass has winners.
    cands = [
        (1, 50, True, True, True),
        (2, 30, True, True, True),  # best after dropping 'fresh' AND 'no_claim'
        (3, 40, True, True, True),
    ]
    pick = select_with_relaxation(cands, by_score, filters)
    check("3 relax claim+fresh", pick is not None and pick[0] == 2, f"got {pick}")

    # 4. Out of range survives even total relaxation? Yes — last pass
    #    has no filters and picks best score regardless.
    cands = [
        (1, 50, True, True, False),
        (2, 30, True, True, False),  # best when ALL filters drop
        (3, 40, True, True, False),
    ]
    pick = select_with_relaxation(cands, by_score, filters)
    check("4 final pass no filters", pick is not None and pick[0] == 2, f"got {pick}")

    # 5. Empty candidate list: returns None.
    pick = select_with_relaxation([], by_score, filters)
    check("5 empty candidates", pick is None, f"got {pick}")

    # 6. No filters: pure scoring.
    cands = [(1, 50, True, True, False), (2, 30, True, True, False)]
    pick = select_with_relaxation(cands, by_score, [])
    check("6 no filters pure scoring", pick is not None and pick[0] == 2, f"got {pick}")

    # 7. Filter order: dropping happens from the END. Verify by giving
    #    a strict-but-essential filter at index 0 and a loose one at
    #    index -1 — the loose one should be dropped first even if
    #    candidates exist that fail the strict one.
    cands = [
        (1, 10, True, False, False),  # passes 'fresh', fails 'no_claim' & 'in_range'
        (2, 20, False, True, True),   # passes 'in_range' & 'no_claim', fails 'fresh'
    ]
    # Pass 1 (all 3): nothing.
    # Pass 2 (drop 'fresh'): cand 2 passes (in_range + no_claim).
    # cand 1 only passes 'fresh', which is the dropped filter, so it
    # would only appear when all filters are dropped. Cand 2 wins.
    pick = select_with_relaxation(cands, by_score, filters)
    check("7 drop from end", pick is not None and pick[0] == 2, f"got {pick}")

    # ---- Tiered select ----

    # 8. Tiered: first tier non-empty wins.
    tiers: list[tuple[str, list[Cand]]] = [
        ("priority", [(1, 50, False, False, True)]),
        ("fallback", [(2, 10, False, False, True)]),  # would beat by score, but tier 2
    ]
    res = tiered_select_with_relaxation(tiers, by_score, filters)
    check("8 tiered first tier wins", res is not None and res[0][0] == 1 and res[1] == "priority", f"got {res}")

    # 9. Tiered: first tier empty, second tier produces winner.
    tiers = [
        ("priority", []),
        ("fallback", [(7, 30, False, False, True), (8, 10, False, False, True)]),
    ]
    res = tiered_select_with_relaxation(tiers, by_score, filters)
    check("9 tiered second tier", res is not None and res[0][0] == 8 and res[1] == "fallback", f"got {res}")

    # 10. Tiered: first tier candidates fail all filters and survive only
    #     by full relaxation; second tier has a passing candidate but
    #     loses anyway because tier 1 wins under relaxation.
    tiers = [
        ("priority", [(11, 60, True, True, False)]),  # fails all filters
        ("fallback", [(12, 10, False, False, True)]),  # passes everything
    ]
    res = tiered_select_with_relaxation(tiers, by_score, filters)
    check("10 tiered relaxation wins within tier", res is not None and res[0][0] == 11 and res[1] == "priority", f"got {res}")

    # 11. Tiered: all tiers empty.
    res = tiered_select_with_relaxation([("a", []), ("b", [])], by_score, filters)
    check("11 tiered all empty", res is None, f"got {res}")

    # 12. Tiered: empty tiers list.
    res = tiered_select_with_relaxation([], by_score, filters)
    check("12 tiered empty tiers list", res is None, f"got {res}")

    # ---- make_unclaimed_filter ----

    from players.player_sdk.nav_grid.distance import manhattan  # canonical metric

    # 13. No teammates: filter accepts all targets.
    f = make_unclaimed_filter((0, 0), [], manhattan, proximity_K=5, claim_buffer=1)
    check("13 unclaimed no teammates", f((10, 10)) and f((0, 0)))

    # 14. Distant target (>K): filter accepts even with closer teammate.
    f = make_unclaimed_filter(
        my_pos=(0, 0),
        teammates=[(5, 5)],
        manhattan=manhattan,
        proximity_K=5,
        claim_buffer=1,
    )
    target = (10, 0)  # my_d = 10 > 5
    check("14 unclaimed proximity gate", f(target))

    # 15. Within K, teammate has clear lead (>= buffer closer): filter rejects.
    f = make_unclaimed_filter(
        my_pos=(0, 0),
        teammates=[(2, 0)],  # teammate is 2 cells from target (3,0); we are 3
        manhattan=manhattan,
        proximity_K=5,
        claim_buffer=1,
    )
    target = (3, 0)  # my_d=3, teammate_d=1, lead=2 >= buffer 1 => reject
    check("15 unclaimed teammate lead", not f(target))

    # 16. Within K, teammate equidistant but lex-smaller: filter rejects.
    f = make_unclaimed_filter(
        my_pos=(2, 2),
        teammates=[(0, 0)],  # equidistant to (1, 1)
        manhattan=manhattan,
        proximity_K=5,
        claim_buffer=1,
    )
    target = (1, 1)  # both 2 manhattan from target; teammate (0,0) < (2,2) => reject
    check("16 unclaimed equidistant lex tiebreak", not f(target))

    # 17. Within K, teammate equidistant but lex-larger: filter accepts.
    f = make_unclaimed_filter(
        my_pos=(0, 0),
        teammates=[(2, 2)],
        manhattan=manhattan,
        proximity_K=5,
        claim_buffer=1,
    )
    target = (1, 1)  # both 2 from target; teammate (2,2) > (0,0) => accept
    check("17 unclaimed equidistant we win", f(target))

    # 18. Buffer matters: teammate closer by 1 with buffer=2 => accept.
    f = make_unclaimed_filter(
        my_pos=(0, 0),
        teammates=[(1, 0)],  # teammate 1 closer to (3,0) than us
        manhattan=manhattan,
        proximity_K=5,
        claim_buffer=2,
    )
    target = (3, 0)  # my_d=3, teammate_d=2, lead=1 < buffer=2 => accept
    check("18 unclaimed buffer survives 1-cell lead", f(target))

    # 19. Filter composes inside select_with_relaxation.
    teammates = [(1, 0)]
    targets = [(3, 0), (10, 0)]  # first is contested in K window, second is far
    unclaimed = make_unclaimed_filter(
        my_pos=(0, 0),
        teammates=teammates,
        manhattan=manhattan,
        proximity_K=5,
        claim_buffer=1,
    )
    pick = select_with_relaxation(
        targets,
        score=lambda t: manhattan((0, 0), t),  # nearest wins
        filters=[unclaimed],
    )
    # Pass 1 with unclaimed: (3,0) is rejected (teammate ahead). (10,0)
    # passes the proximity gate and survives. So (10, 0) wins.
    check("19 unclaimed composes", pick == (10, 0), f"got {pick}")
