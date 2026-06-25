"""Powerups variant: destroying crates drops pickups based on their loot.

There are three crate flavours on the map:
  - plain crate: just crate_hp. Destroying it vacates the cell.
  - range_crate: holds has_range_loot. Destroying it spawns a ``range_up``
    pickup at its cell.
  - count_crate: holds has_count_loot. Destroying it spawns a ``count_up``
    pickup at its cell.

All three share ``name="crate"`` so ``isA("crate")`` filters and blast
blockers still match uniformly — they're distinguished purely by their
inventory contents.

Pickups (``range_up`` / ``count_up``) look and behave the same as before:
the agent walks onto the pickup (via the default ``use_target`` move
handler) and the pickup's ``on_use_handler`` grants +1 ``bomb_range`` or
+1 ``bomb_slots`` and removes itself.
"""

from __future__ import annotations

from bombercog._framework import CoGameMissionVariant
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import isNot, query, targetHas, typeTag
from mettagrid.config.handler_config import Handler, updateActor, updateTarget, withdraw
from mettagrid.config.mettagrid_config import (
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
)
from mettagrid.config.mutation import SpawnObjectMutation
from mettagrid.map_builder.ascii import AsciiMapBuilder

# Map: C = plain crate, R = range crate (drops range_up), B = count crate
# (drops count_up). Same overall shape as the base 11x9 grid so agents
# have a short path to their first bomb-eligible crate. Loot crates sit
# at symmetric positions roughly equidistant from both spawns.
POWERUPS_MAP: list[list[str]] = [
    list("###########"),
    list("#@........#"),
    list("#.R.C.C.R.#"),
    list("#.C..B..C.#"),
    list("#..C...C..#"),
    list("#.C..B..C.#"),
    list("#.R.C.C.R.#"),
    list("#........@#"),
    list("###########"),
]


class PowerupsVariant(CoGameMissionVariant):
    """Destroying a loot crate spawns a powerup in its cell."""

    name: str = "powerups"
    description: str = "Some crates drop range/count pickups when destroyed."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        # Add resources:
        #   pickup_hp      — self-removal marker on a spawned powerup
        #   has_range_loot — marks a crate as a range_crate (cap 1)
        #   has_count_loot — marks a crate as a count_crate (cap 1)
        for resource in ("pickup_hp", "has_range_loot", "has_count_loot"):
            if resource not in env.game.resource_names:
                env.game.resource_names = list(env.game.resource_names) + [resource]

        pickup_inv = InventoryConfig(
            initial={"pickup_hp": 1},
            limits={
                "pickup_hp": ResourceLimitsConfig(base=1, max=1, resources=["pickup_hp"]),
            },
        )

        env.game.objects["range_up"] = GridObjectConfig(
            name="range_up",
            inventory=pickup_inv.model_copy(deep=True),
            on_use_handler=Handler(
                name="collect_range",
                mutations=[
                    updateActor({"bomb_range": 1}),
                    withdraw({"pickup_hp": 1}, remove_when_empty=True),
                ],
            ),
        )

        env.game.objects["count_up"] = GridObjectConfig(
            name="count_up",
            inventory=pickup_inv.model_copy(deep=True),
            on_use_handler=Handler(
                name="collect_count",
                # +1 bomb_slots raises the effective bomb_count cap by 1
                # (bomb_slots acts as a modifier on the bomb_count limit, up
                # to BOMB_SLOTS_MAX). Regen fills the new slot over time.
                mutations=[
                    updateActor({"bomb_slots": 1}),
                    withdraw({"pickup_hp": 1}, remove_when_empty=True),
                ],
            ),
        )

        # Loot crates. Share name="crate" so they still match isA("crate")
        # as both blast blockers and as targets of damage_crates /
        # cleanup_crates. Distinguished by the has_*_loot inventory flag.
        env.game.objects["range_crate"] = GridObjectConfig(
            name="crate",
            map_name="range_crate",
            inventory=InventoryConfig(
                initial={"crate_hp": 1, "has_range_loot": 1},
                limits={
                    "crate_hp": ResourceLimitsConfig(base=1, max=1, resources=["crate_hp"]),
                    "has_range_loot": ResourceLimitsConfig(
                        base=1, max=1, resources=["has_range_loot"]
                    ),
                },
            ),
        )
        env.game.objects["count_crate"] = GridObjectConfig(
            name="crate",
            map_name="count_crate",
            inventory=InventoryConfig(
                initial={"crate_hp": 1, "has_count_loot": 1},
                limits={
                    "crate_hp": ResourceLimitsConfig(base=1, max=1, resources=["crate_hp"]),
                    "has_count_loot": ResourceLimitsConfig(
                        base=1, max=1, resources=["has_count_loot"]
                    ),
                },
            ),
        )

        # Loot drop events. Fire AFTER damage_crates (which drained crate_hp
        # to 0) and BEFORE cleanup_crates (which removes hp=0 crates).
        # Alphabetical ordering of event keys: ASCII '_' (0x5F) < 'a' (0x61),
        # so bomb_02_damage_crates < bomb_02a_drop_range_up <
        # bomb_02b_drop_count_up < bomb_02c_cleanup_crates. That means the
        # loot-drop events see a destroyed loot crate, drain its loot marker,
        # remove it from the grid via withdraw(remove_when_empty=True), then
        # spawn the pickup in the newly-freed cell.
        env.game.events["bomb_02a_drop_range_up"] = EventConfig(
            name="drop_range_up",
            target_query=query(
                typeTag("crate"),
                [
                    isNot(targetHas({"crate_hp": 1})),  # hp == 0 → just destroyed
                    targetHas({"has_range_loot": 1}),   # this was a range crate
                ],
            ),
            timesteps=periodic(start=0, period=1),
            mutations=[
                updateTarget({"has_range_loot": -1}),              # clear marker
                withdraw({"crate_hp": 0}, remove_when_empty=True), # remove crate
                SpawnObjectMutation(object_type="range_up"),        # spawn pickup in freed cell
            ],
        )
        env.game.events["bomb_02b_drop_count_up"] = EventConfig(
            name="drop_count_up",
            target_query=query(
                typeTag("crate"),
                [
                    isNot(targetHas({"crate_hp": 1})),
                    targetHas({"has_count_loot": 1}),
                ],
            ),
            timesteps=periodic(start=0, period=1),
            mutations=[
                updateTarget({"has_count_loot": -1}),
                withdraw({"crate_hp": 0}, remove_when_empty=True),
                SpawnObjectMutation(object_type="count_up"),
            ],
        )

        # Replace the map with one that marks some crates as loot crates.
        env.game.map_builder = AsciiMapBuilder.Config(
            map_data=[list(row) for row in POWERUPS_MAP],
            char_to_map_name={
                "#": "wall",
                ".": "empty",
                "@": "agent.agent",
                "C": "crate",
                "R": "range_crate",
                "B": "count_crate",
            },
        )
