"""Chain reaction variant: bombs caught in a blast detonate."""

from __future__ import annotations

from bombercog._framework import CoGameMissionVariant
from bombercog.game import _blast_raycast, _exploding_bombs_query
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import isA, isNot, query, targetHas, typeTag
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import (
    MettaGridConfig,
    ResourceLimitsConfig,
)

# Bombs start with this much hp. Each blast ray that hits a bomb drains 1 hp.
# A bomb at 0 hp detonates one tick later (its fuse is forced to 0, and the
# normal blast pipeline handles the rest).
BOMB_HP = 1


class ChainReactionVariant(CoGameMissionVariant):
    """Bombs in a blast path lose ``bomb_hp``. When a bomb's ``bomb_hp``
    reaches 0 its fuse is drained to 0 on the next tick, so it detonates
    using the normal blast pipeline — producing a 1-tick chain delay per
    link.
    """

    name: str = "chain_reaction"
    description: str = "Bombs in a blast path detonate, chaining explosions."

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        if "bomb_hp" not in env.game.resource_names:
            env.game.resource_names = list(env.game.resource_names) + ["bomb_hp"]

        # Give the bomb a bomb_hp slot (1 hp, cap 1).
        bomb = env.game.objects["bomb"]
        bomb.inventory.initial["bomb_hp"] = BOMB_HP
        bomb.inventory.limits["bomb_hp"] = ResourceLimitsConfig(
            base=BOMB_HP,
            max=BOMB_HP,
            resources=["bomb_hp"],
        )

        # Reuse the base game's exploding-bomb raycast so chain damage
        # respects the upgraded bomb_range_transfer + wall/crate blockers.
        blast = _blast_raycast()

        # Event key naming: the base game uses auto-numbered "bomb_{NN}_<name>".
        # Alphabetical order in std::map is what the engine honors, so we pick
        # keys that sort into the right slots relative to the existing events:
        #
        #   bomb_00_fuse_tick           < bomb_00z_detonate_damaged  (this variant)
        #   bomb_00z_detonate_damaged   < bomb_01_spawn_blast
        #   bomb_02_damage_crates       < bomb_02z_damage_bombs     (this variant)
        #   bomb_02z_damage_bombs       < bomb_03_damage_agents
        #
        # ASCII: '_' (0x5F) < 'z' (0x7A), and '0' (0x30) < '1' (0x31).

        # Drain fuse on any bomb whose bomb_hp is 0 — this forces detonation
        # via the normal fuse=0 pipeline on the same tick. The minus
        # keeps fuse <=0 in case it was also mid-countdown.
        env.game.events["bomb_00z_detonate_damaged"] = EventConfig(
            name="detonate_damaged",
            target_query=query(typeTag("bomb"), [isNot(targetHas({"bomb_hp": 1}))]),
            timesteps=periodic(start=0, period=1),
            mutations=[updateTarget({"fuse": -10})],
        )

        # Damage bombs along the blast path. Same raycast as damage_crates /
        # damage_agents — source = exploding bombs, blocker = walls + crates.
        # We only target bombs that still have >=1 bomb_hp so we don't go
        # negative. The minus-1 drives bomb_hp to 0, which triggers
        # bomb_00z_detonate_damaged on the NEXT tick (chain delay).
        env.game.events["bomb_02z_damage_bombs"] = EventConfig(
            name="damage_bombs",
            target_query=blast,
            timesteps=periodic(start=0, period=1),
            filters=[isA("bomb"), targetHas({"bomb_hp": 1})],
            mutations=[updateTarget({"bomb_hp": -1})],
        )

        # Drain bomb_hp on any bomb that's detonating (fuse<=0) so the base
        # game's bomb_05_remove_exploded event can actually remove it via
        # its inventory-empty check. Without this, a solitary bomb that's
        # never been chain-damaged still carries bomb_hp=1 at detonation
        # time, the withdraw(fuse=0, remove_when_empty=True) sees the
        # non-empty inventory and leaves a zombie bomb on the grid forever.
        # Sorts between bomb_04_cleanup_crates and bomb_05_remove_exploded.
        env.game.events["bomb_04z_drain_bomb_hp"] = EventConfig(
            name="drain_bomb_hp",
            target_query=_exploding_bombs_query(),
            timesteps=periodic(start=0, period=1),
            mutations=[updateTarget({"bomb_hp": -BOMB_HP})],
        )
