"""Tests for players.player_sdk.worldmodel.mapping.

``is_stale`` scenarios ported 1:1 from the original ``swgy_memory.py``
smoke test; WorldMap behavior from ``mas_memory.SharedWorldMap``; PoiMap
scenarios adapted from the ``dedicated_runtime.py`` smoke test with the
game-specific PoiKind enum replaced by a caller-supplied vocabulary and the
junction ledger replaced by the ``on_kind_change`` hook.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.mapping import PoiMap, WorldMap, is_stale


def check(label: str, cond: bool, detail: str = "") -> None:
    assert cond, f"FAIL {label}: {detail}"


def test_is_stale_scenarios() -> None:
    # 1. Within ttl: not stale.
    check("1 within ttl", not is_stale(last_seen_step=100, current_step=200, ttl=200))
    # 2. At ttl boundary (gap == ttl): not stale (strict >).
    check("2 at ttl boundary not stale", not is_stale(100, 300, 200))
    # 3. Past ttl: stale.
    check("3 past ttl stale", is_stale(100, 301, 200))
    # 4. Same step: not stale.
    check("4 same step not stale", not is_stale(50, 50, 200))
    # 5. ttl=0: any gap is stale.
    check("5 ttl 0 immediate stale", is_stale(50, 51, 0))
    check("5b ttl 0 same tick not stale", not is_stale(50, 50, 0))


WALLS = frozenset({99})


def test_worldmap_monotonic_tag_union_and_walls() -> None:
    m = WorldMap()
    m.record((2, 2), {1, 2}, step=5, wall_tag_ids=WALLS)
    m.record((2, 2), {3}, step=9, wall_tag_ids=WALLS)  # transient overlay
    hits = m.cells_with_any_tag(include=frozenset({1}))
    assert hits == [((2, 2), {1, 2, 3})]  # union kept tag 1 despite overlay
    assert m.last_seen((2, 2)) == 9
    assert m.walls == set()
    m.record((0, 1), {99}, step=10, wall_tag_ids=WALLS)
    assert m.walls == {(0, 1)}


def test_worldmap_filtering() -> None:
    m = WorldMap()
    m.record((0, 0), {1, 10}, 0, WALLS)
    m.record((1, 1), {1, 20}, 0, WALLS)
    m.record((2, 2), {2}, 0, WALLS)
    inc = frozenset({1})
    assert {c for c, _ in m.cells_with_any_tag(inc)} == {(0, 0), (1, 1)}
    assert {c for c, _ in m.cells_with_any_tag(inc, require=frozenset({10}))} == {(0, 0)}
    assert {c for c, _ in m.cells_with_any_tag(inc, exclude=frozenset({20}))} == {(0, 0)}
    m.clear()
    assert m.cells_with_any_tag(inc) == []
    assert m.last_seen((0, 0)) is None


def test_poimap_upsert_and_kind_transitions() -> None:
    transitions: list[tuple] = []
    pois: PoiMap[str] = PoiMap(
        on_kind_change=lambda cell, old, new, step: transitions.append(
            (cell, old, new, step)
        )
    )

    # 5. Initial insert.
    pois.upsert((10, 10), "junction_neutral", frozenset(), 1)
    got = pois.get((10, 10))
    check("5 poi initial insert", got is not None and got.kind == "junction_neutral")

    # 6. neutral->friendly transition surfaces through the hook.
    pois.upsert((10, 10), "junction_friendly", frozenset(), 2)
    check(
        "6 neutral->friendly transition recorded",
        transitions == [((10, 10), "junction_neutral", "junction_friendly", 2)],
        f"{transitions}",
    )

    # 7. friendly->enemy transition also surfaces (game reaction is caller's).
    pois.upsert((10, 10), "junction_enemy", frozenset(), 50)
    check(
        "7 friendly->enemy transition recorded",
        transitions[-1] == ((10, 10), "junction_friendly", "junction_enemy", 50),
    )
    # Same-kind refresh does NOT fire the hook, but updates last_seen.
    pois.upsert((10, 10), "junction_enemy", frozenset({7}), 60)
    assert len(transitions) == 2
    assert pois.get((10, 10)).last_seen_step == 60
    assert pois.get((10, 10)).tags == frozenset({7})


def test_poimap_all_of_kind_filtering() -> None:
    pois: PoiMap[str] = PoiMap()
    pois.upsert((1, 1), "extractor_carbon", frozenset(), 1)
    pois.upsert((1, 2), "extractor_carbon", frozenset(), 1)
    pois.upsert((1, 3), "extractor_oxygen", frozenset(), 1)
    check("8 kind filter", len(pois.all_of_kind("extractor_carbon")) == 2)
    check(
        "8b multi-kind filter",
        len(pois.all_of_kind("extractor_carbon", "extractor_oxygen")) == 3,
    )
    assert len(pois) == 3
    assert (1, 1) in pois
    pois.forget((1, 1))
    assert (1, 1) not in pois and len(pois) == 2


def test_poi_is_stale_ttl_zero_disables() -> None:
    pois: PoiMap[str] = PoiMap()
    p = pois.upsert((0, 0), "hub", frozenset(), 100)
    assert not p.is_stale(step=100 + 500, ttl=0)  # ttl<=0 -> never stale
    assert not p.is_stale(step=100 + 500, ttl=500)  # boundary: strict >
    assert p.is_stale(step=100 + 501, ttl=500)


def test_poimap_upsert_updates_in_place() -> None:
    pois: PoiMap[str] = PoiMap()
    ref = pois.upsert((3, 3), "station", frozenset(), 1)
    again = pois.upsert((3, 3), "station", frozenset({5}), 7)
    assert again is ref  # existing references stay live
    assert ref.last_seen_step == 7 and ref.tags == frozenset({5})
