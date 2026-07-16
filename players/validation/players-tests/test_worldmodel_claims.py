"""Tests for players.player_sdk.worldmodel.claims.

The ClaimBook scenarios are ported 1:1 from the embedded smoke test of the
original ``swgy_memory.py`` (sm-policies scripted stack), adapted to the
unified constructor (``ClaimBook(default_ttl=...)`` instead of a config
object), plus new cases for the features absorbed from
``mas_memory.TargetClaims``: per-call TTL override, ``clear()``, and
non-coordinate hashable keys.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.claims import ClaimBook


def check(label: str, cond: bool, detail: str = "") -> None:
    assert cond, f"FAIL {label}: {detail}"


def test_claimbook_smoke_scenarios() -> None:
    book = ClaimBook(default_ttl=10)

    # 6. Empty book: nothing claimed.
    check("6 empty owner", book.claim_owner((0, 0), 0) is None)
    check("6b empty is_claimed_by_other", not book.is_claimed_by_other(1, (0, 0), 0))
    check("6c empty claims_held_by", book.claims_held_by(1) == [])

    # 7. Claim, then read.
    book.claim(agent_id=7, key=(3, 4), step=0)
    check("7 owner after claim", book.claim_owner((3, 4), 5) == 7)
    check("7b held_by_self", not book.is_claimed_by_other(7, (3, 4), 5))
    check("7c held_by_other", book.is_claimed_by_other(8, (3, 4), 5))
    check("7d claims_held_by", book.claims_held_by(7) == [(3, 4)])

    # 8. TTL expiry: claim drops after ttl elapses on next access.
    # Claimed at step 0 with ttl=10 -> expires at step 10. Strict <
    # comparison: at step 10 still valid; at step 11 expired.
    check("8 still valid at expiry tick", book.claim_owner((3, 4), 10) == 7)
    check("8b expired one past expiry", book.claim_owner((3, 4), 11) is None)
    check("8c expired entry removed", len(book) == 0)

    # 9. Renewal pushes expiry forward.
    book.claim(agent_id=7, key=(3, 4), step=20)
    check("9 renewal owner", book.claim_owner((3, 4), 25) == 7)
    check("9b renewal expired again", book.claim_owner((3, 4), 31) is None)

    # 10. release: only owner can release.
    book.claim(agent_id=7, key=(1, 1), step=0)
    check("10 release wrong owner false", not book.release(8, (1, 1)))
    check("10b after wrong release still claimed", book.claim_owner((1, 1), 1) == 7)
    check("10c release correct owner true", book.release(7, (1, 1)))
    check("10d after release no owner", book.claim_owner((1, 1), 1) is None)

    # 11. release_all drops every key held by an agent.
    book.claim(7, (2, 2), 0)
    book.claim(7, (3, 3), 0)
    book.claim(8, (4, 4), 0)
    book.release_all(7)
    check("11 release_all clears agent 7", book.claims_held_by(7) == [])
    check("11b agent 8 untouched", book.claim_owner((4, 4), 1) == 8)

    # 12. cleanup_expired drops expired without needing access.
    book = ClaimBook(default_ttl=5)
    book.claim(1, (0, 0), step=0)   # expires at 5
    book.claim(2, (1, 1), step=10)  # expires at 15
    book.cleanup_expired(step=10)
    check("12 cleanup drops first", book.claims_held_by(1) == [])
    check("12b cleanup keeps second", book.claim_owner((1, 1), 10) == 2)

    # 13. Multiple agents on different keys coexist.
    book = ClaimBook(default_ttl=10)
    book.claim(1, (0, 0), 0)
    book.claim(2, (1, 1), 0)
    book.claim(3, (2, 2), 0)
    check(
        "13 three claims tracked",
        book.claim_owner((0, 0), 1) == 1
        and book.claim_owner((1, 1), 1) == 2
        and book.claim_owner((2, 2), 1) == 3,
    )

    # 14. Same key re-claimed by different agent overrides.
    book.claim(99, (0, 0), 5)
    check("14 reclaim overrides owner", book.claim_owner((0, 0), 6) == 99)

    # 15. is_claimed_by_other False when expired.
    book = ClaimBook(default_ttl=2)
    book.claim(7, (5, 5), 0)
    check(
        "15 is_claimed_by_other after expiry",
        not book.is_claimed_by_other(8, (5, 5), 100),
    )


def test_per_call_ttl_override() -> None:
    # Absorbed from mas_memory.TargetClaims: per-call ttl beats default.
    book = ClaimBook(default_ttl=100)
    book.claim(1, (0, 0), step=0, ttl=5)
    assert book.claim_owner((0, 0), 5) == 1
    assert book.claim_owner((0, 0), 6) is None
    book.claim(1, (1, 1), step=0)  # default ttl still applies elsewhere
    assert book.claim_owner((1, 1), 50) == 1


def test_hashable_keys_beyond_coordinates() -> None:
    book = ClaimBook(default_ttl=10)
    book.claim(1, ((5, 5), "carbon"), step=0)
    book.claim(2, "relay-objective", step=0)
    assert book.claim_owner(((5, 5), "carbon"), 1) == 1
    assert book.claim_owner("relay-objective", 1) == 2
    assert not book.is_claimed_by_other(1, ((5, 5), "carbon"), 1)
    assert book.is_claimed_by_other(1, "relay-objective", 1)


def test_clear_drops_everything() -> None:
    book = ClaimBook(default_ttl=10)
    book.claim(1, (0, 0), 0)
    book.claim(2, (1, 1), 0)
    book.clear()
    assert len(book) == 0
    assert book.claim_owner((0, 0), 0) is None


def test_expiry_at_write_semantics() -> None:
    # The unified semantic: expiry is fixed at write time. (The absorbed
    # dedicated_runtime variant compared TTL at read; documented difference.)
    book = ClaimBook(default_ttl=25)
    book.claim(0, (5, 5), step=10)
    assert book.is_claimed_by_other(1, (5, 5), 35)  # step 10 + 25 still live
    assert not book.is_claimed_by_other(1, (5, 5), 36)  # one past: expired
