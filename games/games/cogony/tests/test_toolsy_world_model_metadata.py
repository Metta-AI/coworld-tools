from __future__ import annotations

from mettagrid.sdk.agent.runtime.observation import DecodedObservation, ObservationCell
from mettagrid.simulator.interface import Location

from toolsy_policy.obs import WorldMap


def _cell(row: int, col: int, *, tags: tuple[str, ...] = (), features: dict[str, int] | None = None) -> ObservationCell:
    center = Location(0, 0)
    return ObservationCell(
        location=Location(row, col),
        center=center,
        tags=tags,
        features=features or {},
    )


def _decoded(step: int, cells: dict[tuple[int, int], ObservationCell]) -> DecodedObservation:
    return DecodedObservation(
        observation=None,
        policy_env_info=None,
        step=step,
        center_row=0,
        center_col=0,
        cells_by_location=cells,
        global_features={},
    )


def test_world_model_snapshot_tracks_entity_age_level_and_alignment() -> None:
    world_map = WorldMap()
    world_map.update(_decoded(
        10,
        {
            (0, 1): _cell(
                0,
                1,
                tags=("type:junction", "team:cogs_red"),
                features={"inv:core_a": 2, "inv:os_a": 1, "inv:storage_d": 3},
            ),
        },
    ))
    world_map.update(_decoded(14, {(0, 0): _cell(0, 0)}))

    assert world_map.snapshot(0, 0)["entities"] == [
        {
            "type": "junction",
            "row": 0,
            "col": 1,
            "dr": 0,
            "dc": 1,
            "dist": 1,
            "age": 4,
            "level": 6,
            "alignment": "red",
        }
    ]


def test_world_model_infers_compound_stations_from_hub_and_market() -> None:
    world_map = WorldMap()

    world_map.update(_decoded(
        7,
        {
            (10, 10): _cell(10, 10, tags=("type:hub",)),
            (10, 13): _cell(10, 13, tags=("type:market_station",)),
        },
    ))

    snapshot = world_map.snapshot(10, 10, max_entities=40)
    by_type = {entity["type"]: entity for entity in snapshot["entities"]}
    assert snapshot["entity_count"] == 12
    assert by_type["stake_buy_station"] == {
        "type": "stake_buy_station",
        "row": 8,
        "col": 7,
        "dr": -2,
        "dc": -3,
        "dist": 5,
        "age": 0,
        "level": 0,
        "alignment": "",
    }
    assert by_type["core_a_station"]["row"] == 17
    assert by_type["core_a_station"]["col"] == 1


def test_world_model_snapshot_includes_all_entities_by_default() -> None:
    world_map = WorldMap()
    world_map.update(_decoded(
        1,
        {
            (0, col): _cell(0, col, tags=("type:market_station",))
            for col in range(90)
        },
    ))

    snapshot = world_map.snapshot(0, 0)

    assert snapshot["entity_count"] == 90
    assert len(snapshot["entities"]) == 90


def test_world_model_snapshot_exposes_seen_bounds_for_stable_map_growth() -> None:
    world_map = WorldMap()
    world_map.update(_decoded(
        1,
        {
            (10, 10): _cell(10, 10),
            (10, 12): _cell(10, 12, tags=("type:market_station",)),
        },
    ))
    world_map.update(_decoded(2, {(8, 9): _cell(8, 9)}))

    assert world_map.snapshot(10, 10)["seen_bounds"] == {
        "min_row": 8,
        "max_row": 10,
        "min_col": 9,
        "max_col": 12,
    }
