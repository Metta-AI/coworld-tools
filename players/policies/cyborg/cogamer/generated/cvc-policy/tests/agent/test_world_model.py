"""Unit tests for WorldModel."""

from __future__ import annotations

import pytest

from cvc_policy.agent.scoring import is_usable_extractor
from cvc_policy.agent.world_model import WorldModel


@pytest.fixture
def wm():
    return WorldModel()


# --- update ---


def test_update_adds_entities(wm, make_state, make_semantic_entity):
    ent = make_semantic_entity("junction", 10, 20)
    state = make_state(visible_entities=[ent], step=1)
    wm.update(state)

    result = wm.entities()
    assert len(result) == 1
    assert result[0].entity_type == "junction"
    assert result[0].position == (10, 20)
    assert result[0].last_seen_step == 1


def test_update_skips_agents(wm, make_state, make_semantic_entity):
    agent = make_semantic_entity("agent", 5, 5)
    wall = make_semantic_entity("wall", 10, 10)
    state = make_state(visible_entities=[agent, wall], step=1)
    wm.update(state)

    result = wm.entities()
    assert len(result) == 1
    assert result[0].entity_type == "wall"


def test_update_overwrites_same_key_with_newer_step(wm, make_state, make_semantic_entity):
    ent_old = make_semantic_entity("junction", 10, 20, team="team_0")
    state_old = make_state(visible_entities=[ent_old], step=1)
    wm.update(state_old)

    ent_new = make_semantic_entity("junction", 10, 20, team="team_1")
    state_new = make_state(visible_entities=[ent_new], step=5)
    wm.update(state_new)

    result = wm.entities()
    assert len(result) == 1
    assert result[0].last_seen_step == 5
    assert result[0].attributes.get("team") == "team_1"


def test_update_multiple_entities(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 1, 1),
        make_semantic_entity("wall", 2, 2),
        make_semantic_entity("carbon_extractor", 3, 3),
    ]
    state = make_state(visible_entities=entities, step=10)
    wm.update(state)

    assert len(wm.entities()) == 3


# --- reset ---


def test_reset_clears_everything(wm, make_state, make_semantic_entity):
    ent = make_semantic_entity("junction", 10, 20)
    state = make_state(visible_entities=[ent], step=1)
    wm.update(state)
    assert len(wm.entities()) == 1

    wm.reset()
    assert len(wm.entities()) == 0


# --- entities ---


def test_entities_filters_by_type(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 1, 1),
        make_semantic_entity("wall", 2, 2),
        make_semantic_entity("junction", 3, 3),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    junctions = wm.entities(entity_type="junction")
    assert len(junctions) == 2
    assert all(e.entity_type == "junction" for e in junctions)


def test_entities_filters_by_predicate(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 1, 1, team="team_0"),
        make_semantic_entity("junction", 2, 2, team="team_1"),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    result = wm.entities(predicate=lambda e: e.attributes.get("team") == "team_0")
    assert len(result) == 1
    assert result[0].position == (1, 1)


def test_entities_filters_by_type_and_predicate(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 1, 1, team="team_0"),
        make_semantic_entity("wall", 2, 2, team="team_0"),
        make_semantic_entity("junction", 3, 3, team="team_1"),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    result = wm.entities(
        entity_type="junction",
        predicate=lambda e: e.attributes.get("team") == "team_0",
    )
    assert len(result) == 1
    assert result[0].position == (1, 1)


def test_entities_returns_empty_when_no_match(wm):
    assert wm.entities(entity_type="nonexistent") == []


# --- nearest ---


def test_nearest_finds_closest(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 10, 10),
        make_semantic_entity("junction", 5, 5),
        make_semantic_entity("junction", 20, 20),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    result = wm.nearest(position=(4, 4), entity_type="junction")
    assert result is not None
    assert result.position == (5, 5)


def test_nearest_respects_predicate(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 5, 5, team="team_0"),
        make_semantic_entity("junction", 10, 10, team="team_1"),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    # Closest is (5,5) but predicate excludes team_0
    result = wm.nearest(
        position=(4, 4),
        entity_type="junction",
        predicate=lambda e: e.attributes.get("team") == "team_1",
    )
    assert result is not None
    assert result.position == (10, 10)


def test_nearest_returns_none_when_empty(wm):
    assert wm.nearest(position=(0, 0)) is None


def test_nearest_returns_none_when_no_match(wm, make_state, make_semantic_entity):
    ent = make_semantic_entity("wall", 5, 5)
    state = make_state(visible_entities=[ent], step=1)
    wm.update(state)

    assert wm.nearest(position=(0, 0), entity_type="junction") is None


# --- occupied_cells ---


def test_occupied_cells_returns_positions(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 1, 1),
        make_semantic_entity("wall", 2, 2),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    cells = wm.occupied_cells()
    assert cells == {(1, 1), (2, 2)}


def test_occupied_cells_excludes_specified(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 1, 1),
        make_semantic_entity("wall", 2, 2),
        make_semantic_entity("wall", 3, 3),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    cells = wm.occupied_cells(exclude={(2, 2)})
    assert cells == {(1, 1), (3, 3)}


def test_is_occupied(wm, make_state, make_semantic_entity):
    ent = make_semantic_entity("wall", 5, 5)
    state = make_state(visible_entities=[ent], step=1)
    wm.update(state)

    assert wm.is_occupied((5, 5)) is True
    assert wm.is_occupied((6, 6)) is False


# --- prune_missing_extractors ---


def test_prune_removes_stale_extractors_in_view(wm, make_state, make_semantic_entity):
    # Add an extractor at (10, 10) to the world model
    ext = make_semantic_entity("carbon_extractor", 10, 10)
    state = make_state(visible_entities=[ext], step=1)
    wm.update(state)
    assert len(wm.entities(entity_type="carbon_extractor")) == 1

    # Now the agent is at (10, 10) with obs 11x11 (half=5), so (10,10) is in view.
    # visible_entities is empty -> extractor should be pruned.
    wm.prune_missing_extractors(
        current_position=(10, 10),
        visible_entities=[],
        obs_width=11,
        obs_height=11,
    )
    assert len(wm.entities(entity_type="carbon_extractor")) == 0


def test_prune_keeps_out_of_view_extractors(wm, make_state, make_semantic_entity):
    # Add an extractor far away at (100, 100)
    ext = make_semantic_entity("carbon_extractor", 100, 100)
    state = make_state(visible_entities=[ext], step=1)
    wm.update(state)

    # Agent at (10, 10) with obs 11x11 -> view is [5..15, 5..15], (100,100) is outside
    wm.prune_missing_extractors(
        current_position=(10, 10),
        visible_entities=[],
        obs_width=11,
        obs_height=11,
    )
    assert len(wm.entities(entity_type="carbon_extractor")) == 1


def test_prune_keeps_extractors_still_visible(wm, make_state, make_semantic_entity):
    ext = make_semantic_entity("carbon_extractor", 10, 10)
    state = make_state(visible_entities=[ext], step=1)
    wm.update(state)

    # Extractor is still in the visible list, so it should not be pruned
    wm.prune_missing_extractors(
        current_position=(10, 10),
        visible_entities=[ext],
        obs_width=11,
        obs_height=11,
    )
    assert len(wm.entities(entity_type="carbon_extractor")) == 1


def test_prune_does_not_affect_non_extractors(wm, make_state, make_semantic_entity):
    wall = make_semantic_entity("wall", 10, 10)
    state = make_state(visible_entities=[wall], step=1)
    wm.update(state)

    wm.prune_missing_extractors(
        current_position=(10, 10),
        visible_entities=[],
        obs_width=11,
        obs_height=11,
    )
    # Wall should remain even though it's in view and not in visible_entities
    assert len(wm.entities(entity_type="wall")) == 1


# --- forget_nearest ---


def test_forget_nearest_removes_within_range(wm, make_state, make_semantic_entity):
    ent = make_semantic_entity("junction", 5, 5)
    state = make_state(visible_entities=[ent], step=1)
    wm.update(state)

    result = wm.forget_nearest(position=(4, 4), entity_type="junction", max_distance=5)
    assert result is True
    assert len(wm.entities(entity_type="junction")) == 0


def test_forget_nearest_returns_false_if_too_far(wm, make_state, make_semantic_entity):
    ent = make_semantic_entity("junction", 50, 50)
    state = make_state(visible_entities=[ent], step=1)
    wm.update(state)

    result = wm.forget_nearest(position=(0, 0), entity_type="junction", max_distance=5)
    assert result is False
    assert len(wm.entities(entity_type="junction")) == 1


def test_forget_nearest_returns_false_when_empty(wm):
    result = wm.forget_nearest(position=(0, 0), entity_type="junction", max_distance=10)
    assert result is False


def test_forget_nearest_removes_only_closest(wm, make_state, make_semantic_entity):
    entities = [
        make_semantic_entity("junction", 3, 3),
        make_semantic_entity("junction", 10, 10),
    ]
    state = make_state(visible_entities=entities, step=1)
    wm.update(state)

    result = wm.forget_nearest(position=(2, 2), entity_type="junction", max_distance=5)
    assert result is True
    remaining = wm.entities(entity_type="junction")
    assert len(remaining) == 1
    assert remaining[0].position == (10, 10)


# ---------------------------------------------------------------------------
# End-to-end: miner target selection filters out empty extractors.
# Exercises the same (WorldModel.entities + is_usable_extractor)
# query path used by _preferred_miner_extractor and _sticky_miner_target.
# ---------------------------------------------------------------------------


def test_query_skips_empty_extractors(wm, make_state, make_semantic_entity):
    """Given one empty and one full carbon_extractor, the miner query returns only the full one."""
    empty = make_semantic_entity("carbon_extractor", 5, 5, carbon=0)
    full = make_semantic_entity("carbon_extractor", 20, 20, carbon=150)
    state = make_state(visible_entities=[empty, full], step=10)
    wm.update(state)

    usable = wm.entities(
        entity_type="carbon_extractor",
        predicate=lambda e: is_usable_extractor(e),
    )
    assert len(usable) == 1
    assert usable[0].position == (20, 20)


def test_query_skips_drained_extractor_with_key_removed(wm, make_state, make_semantic_entity):
    """Real drained extractors drop their resource key entirely (verified against live game).
    The predicate must treat a missing resource attribute as empty, not unknown."""
    # No `carbon=` kwarg → no carbon key in attributes — mirrors the live observation.
    drained = make_semantic_entity("carbon_extractor", 5, 5)
    full = make_semantic_entity("carbon_extractor", 20, 20, carbon=150)
    state = make_state(visible_entities=[drained, full], step=10)
    wm.update(state)

    usable = wm.entities(
        entity_type="carbon_extractor",
        predicate=lambda e: is_usable_extractor(e),
    )
    assert [e.position for e in usable] == [(20, 20)]


def test_query_returns_nothing_when_all_extractors_empty(wm, make_state, make_semantic_entity):
    """If every known extractor of this resource is drained, nothing is returned."""
    entities = [
        make_semantic_entity("oxygen_extractor", 1, 1, oxygen=0),
        make_semantic_entity("oxygen_extractor", 2, 2, oxygen=0),
        make_semantic_entity("oxygen_extractor", 3, 3, oxygen=0),
    ]
    state = make_state(visible_entities=entities, step=5)
    wm.update(state)

    usable = wm.entities(
        entity_type="oxygen_extractor",
        predicate=lambda e: is_usable_extractor(e),
    )
    assert usable == []


def test_query_re_admits_extractor_once_refilled(wm, make_state, make_semantic_entity):
    """World model update with a fresh observation replaces the cached amount."""
    drained = make_semantic_entity("germanium_extractor", 7, 7, germanium=0)
    wm.update(make_state(visible_entities=[drained], step=10))
    assert (
        wm.entities(
            entity_type="germanium_extractor",
            predicate=lambda e: is_usable_extractor(e),
        )
        == []
    )

    refilled = make_semantic_entity("germanium_extractor", 7, 7, germanium=200)
    wm.update(make_state(visible_entities=[refilled], step=20))
    usable = wm.entities(
        entity_type="germanium_extractor",
        predicate=lambda e: is_usable_extractor(e),
    )
    assert len(usable) == 1
    assert usable[0].position == (7, 7)