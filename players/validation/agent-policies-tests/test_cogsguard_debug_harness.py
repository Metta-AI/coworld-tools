from types import SimpleNamespace

import pytest
from agent_policies.policies.scripted.cogsguard.scripted_agent.cogsguard.debug_agent import DebugHarness


def _make_harness(*objects: dict) -> DebugHarness:
    harness = DebugHarness.__new__(DebugHarness)
    harness.sim = SimpleNamespace(resource_names=["oxygen", "carbon", "heart"])
    harness.env_cfg = SimpleNamespace(
        game=SimpleNamespace(id_map=lambda: SimpleNamespace(tag_names=lambda: ["team:cogs", "team:clips"]))
    )
    harness.get_grid_objects = lambda: dict(enumerate(objects))
    return harness


def _hub(*, cogs: bool, inventory: dict[int, int]) -> dict:
    tag_ids = {0} if cogs else {1}
    return {
        "type_name": "hub",
        "inventory": inventory,
        "has_tag": lambda tag_id, tag_ids=tag_ids: tag_id in tag_ids,
    }


def test_object_inventory_reads_named_resources() -> None:
    harness = _make_harness(_hub(cogs=True, inventory={0: 12, 1: 34, 2: 1}))

    assert harness.object_inventory("hub", team_name="cogs") == {
        "oxygen": 12,
        "carbon": 34,
        "heart": 1,
    }


def test_object_inventory_requires_team_when_multiple_hubs_exist() -> None:
    harness = _make_harness(
        _hub(cogs=True, inventory={0: 12}),
        _hub(cogs=False, inventory={1: 34}),
    )

    with pytest.raises(ValueError, match="Expected exactly one 'hub' object"):
        harness.object_inventory("hub")


def test_object_inventory_selects_requested_team_hub() -> None:
    harness = _make_harness(
        _hub(cogs=True, inventory={0: 12}),
        _hub(cogs=False, inventory={1: 34}),
    )

    assert harness.object_inventory("hub", team_name="cogs") == {"oxygen": 12}
