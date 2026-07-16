"""select.py — Multi-pass candidate selection with relaxation.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(sm-policies scripted stack; original module name ``swgy_select.py``).

Aligner / miner / scrambler all walk a list of POI candidates with
progressively relaxed predicates: try strict filters first, drop the
weakest filter and try again, keep dropping until something matches
(or scoring alone is left).

* ``policy_miner.py:437-494`` — 3 passes: claims + exhaustion → claims
  only → none.
* ``policy_aligner.py:516-548`` — 2 passes: claim + stranger-yield →
  drop both.
* ``policy_scrambler.py:740-768`` — similar 2 passes.

Convention: the caller orders ``filters`` from most-essential first
to least-essential last. Each pass drops one filter from the *end*
of the list, so the most-essential filter is the last to be dropped.

Two extensions sit on top of the core ``select_with_relaxation`` primitive:

* ``tiered_select_with_relaxation`` — outer loop over named tiers
  (e.g. visible-clip > visible-neutral > remembered-clip > remembered-
  neutral). The tiered version returns the first non-empty tier with
  the tier name attached. Tiers are caller-defined.
* ``make_unclaimed_filter`` — visible-symmetric, comm-free
  teammate-claim filter. Two-stage proximity + lead check; both agents
  observe each other and reach the same conclusion. Slots into the
  ``filters=[...]`` convention of ``select_with_relaxation``.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")
Coordinate = tuple[int, int]


def select_with_relaxation(
    candidates: Iterable[T],
    score: Callable[[T], Any],
    filters: Sequence[Callable[[T], bool]],
) -> T | None:
    """Pick the best candidate, relaxing filters from the end if needed.

    Pass 1: every filter must pass.
    Pass 2: drop the last filter, retry.
    Pass 3: drop the last two filters, retry.
    ...
    Final pass: no filters; pure ``score`` ranking.

    Returns ``None`` only when ``candidates`` is empty.

    Comparable score values: lower wins (matches Python's ``min``).
    """
    pool = list(candidates)
    if not pool:
        return None

    n = len(filters)
    for drop in range(n + 1):
        active = filters[: n - drop]
        kept = [c for c in pool if all(f(c) for f in active)]
        if kept:
            return min(kept, key=score)

    return None  # only reached if pool was empty


def tiered_select_with_relaxation(
    tiers: Sequence[tuple[str, Iterable[T]]],
    score: Callable[[T], Any],
    filters: Sequence[Callable[[T], bool]],
) -> tuple[T, str] | None:
    """Iterate ``tiers`` in priority order; return the first tier that
    yields a non-empty pick under ``select_with_relaxation``.

    ``tiers`` is a sequence of ``(tier_name, candidates)``. The first
    tier whose ``select_with_relaxation(candidates, score, filters)``
    returns non-None wins, and its ``(candidate, tier_name)`` is
    returned. If no tier produces a winner, returns ``None``.

    Same filter-relaxation semantics applies within each tier: filters
    drop from the end until a candidate matches or pure scoring takes
    over. Tiers do NOT share their relaxation state — each tier starts
    from "all filters strict."

    If callers need different filters per tier, they should pre-filter
    each tier list before passing it in.
    """
    for tier_name, candidates in tiers:
        pick = select_with_relaxation(candidates, score, filters)
        if pick is not None:
            return pick, tier_name
    return None


def make_unclaimed_filter(
    my_pos: Coordinate,
    teammates: Sequence[Coordinate],
    manhattan: Callable[[Coordinate, Coordinate], int],
    proximity_K: int = 5,
    claim_buffer: int = 1,
) -> Callable[[Coordinate], bool]:
    """Visible-symmetric teammate-claim filter.

    Returns a predicate ``ok(target)`` that is True when no visible
    teammate has a stronger claim on ``target``. Two-stage check:

    * Proximity gate: only consider yielding when ``my_dist <= K``.
      Distant POIs aren't anyone's "real" target yet — situations
      change before convergence and yielding now just causes pointless
      detours.
    * Lead check: a teammate is at least ``claim_buffer`` cells closer
      than I am, OR a teammate is equidistant with a lex-smaller
      ``(row, col)``.

    Both checks use only locally-observable info, which is symmetric
    across agents — two agents looking at the same target reach the
    same conclusion about who owns it without communication.

    The factory captures the caller's ``manhattan`` distance function
    so this stays decoupled from the project's coordinate convention
    (own-frame vs. hub-relative).
    """
    if not teammates:
        return lambda _t: True

    teammates = tuple(teammates)
    my_row, my_col = my_pos[0], my_pos[1]

    def ok(target: Coordinate) -> bool:
        my_d = manhattan(my_pos, target)
        if my_d > proximity_K:
            return True
        for t in teammates:
            t_d = manhattan(t, target)
            if t_d <= my_d - claim_buffer:
                return False
            if t_d == my_d and (t[0], t[1]) < (my_row, my_col):
                return False
        return True

    return ok
