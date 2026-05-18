from __future__ import annotations

import pytest
from policies.scripted.cogsguard.scripted_agent.buggy.entity_map import Entity as BuggyEntity
from policies.scripted.cogsguard.scripted_agent.buggy.entity_map import EntityMap as BuggyEntityMap
from policies.scripted.cogsguard.scripted_agent.common.geometry import is_within_observation_shape
from policies.scripted.cogsguard.scripted_agent.cranky.entity_map import Entity as CrankyEntity
from policies.scripted.cogsguard.scripted_agent.cranky.entity_map import EntityMap as CrankyEntityMap


def test_observation_shape_3x3_excludes_diagonals() -> None:
    visible = {
        (dr, dc)
        for dr in range(-1, 2)
        for dc in range(-1, 2)
        if is_within_observation_shape(row_offset=dr, col_offset=dc, row_radius=1, col_radius=1)
    }
    assert visible == {(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)}


def test_observation_shape_11x11_has_three_wide_cardinal_tip() -> None:
    assert is_within_observation_shape(row_offset=-5, col_offset=-1, row_radius=5, col_radius=5)
    assert is_within_observation_shape(row_offset=-5, col_offset=0, row_radius=5, col_radius=5)
    assert is_within_observation_shape(row_offset=-5, col_offset=1, row_radius=5, col_radius=5)
    assert not is_within_observation_shape(row_offset=-5, col_offset=-2, row_radius=5, col_radius=5)
    assert not is_within_observation_shape(row_offset=-5, col_offset=2, row_radius=5, col_radius=5)


@pytest.mark.parametrize(
    ("entity_map", "entity"),
    [
        (CrankyEntityMap(), CrankyEntity),
        (BuggyEntityMap(), BuggyEntity),
    ],
)
def test_entity_maps_only_clear_entities_in_observation_mask(entity_map, entity) -> None:
    diagonal = (9, 9)  # Outside 3x3 circular mask around (10,10)
    cardinal = (10, 9)  # Inside 3x3 circular mask
    entity_map.entities[diagonal] = entity(type="wall", properties={})
    entity_map.entities[cardinal] = entity(type="wall", properties={})

    entity_map.update_from_observation(
        agent_pos=(10, 10),
        obs_half_height=1,
        obs_half_width=1,
        visible_entities={},
        step=1,
    )

    assert diagonal in entity_map.entities
    assert cardinal not in entity_map.entities
    assert diagonal not in entity_map.explored
    assert entity_map.explored == {
        (10, 10),
        (9, 10),
        (11, 10),
        (10, 9),
        (10, 11),
    }
