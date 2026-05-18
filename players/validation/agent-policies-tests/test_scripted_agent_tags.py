from __future__ import annotations

from policies.scripted.cogsguard.scripted_agent.utils import create_object_state

from mettagrid.config.tag import typeTag


def test_primary_tag_prefers_type_over_team() -> None:
    obj_state = create_object_state(
        {"tags": [1, 2]},
        tag_names={1: "team:cogs", 2: typeTag("junction")},
    )

    assert obj_state.name == "junction"
    assert obj_state.tags == ["team:cogs", typeTag("junction")]


def test_primary_tag_falls_back_to_non_team() -> None:
    obj_state = create_object_state(
        {"tags": [1, 2]},
        tag_names={1: "team:clips", 2: "hub"},
    )

    assert obj_state.name == "hub"
    assert obj_state.tags == ["team:clips", "hub"]
