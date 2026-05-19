"""Game configuration for Bombercog.

Bomberman-style deathmatch on a small fixed grid. Agents switch into the
``bomb`` vibe, move into an empty cell to drop a bomb, and flee before the
fuse expires. Bombs produce a cross-shaped blast (via ``RaycastSpawnMutation``
for visual markers and ``raycastQuery`` for damage) that destroys crates and
damages agents, blocked by walls and crates.

See ``rules.md`` for the design contract and variant table.

Pipeline architecture
---------------------

Each tick runs: **actions** first, then **events** (world update).
The blast pipeline is expressed as events so that all game-world updates
(fuse countdown, blast damage, marker spawn/cleanup) happen together in
the world-update phase after agents have acted. The pipeline is defined
as an ordered Python list of ``(name, EventConfig)`` tuples; a helper
auto-numbers the dict keys so alphabetical iteration matches list order.

Only ``bomb_regen`` lives in ``game.on_tick`` (timing-insensitive).
"""

from __future__ import annotations

from typing import cast

from pydantic import Field

from bombercog._framework import CoGameMission
from mettagrid.config.action_config import (
    ActionsConfig,
    ChangeVibeActionConfig,
    MoveActionConfig,
    NoopActionConfig,
)
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import (
    GameValueFilter,
    HandlerTarget,
    ResourceFilter,
    TargetLocEmptyFilter,
    VibeFilter,
    isA,
    isNot,
    query,
    raycastQuery,
    targetHas,
    typeTag,
)
from mettagrid.config.game_value import InventoryValue
from mettagrid.config.handler_config import Handler, deposit, updateTarget, withdraw
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ResourceLimitsConfig,
    WallConfig,
)
from mettagrid.config.mutation.change_vibe_mutation import ChangeVibeMutation
from mettagrid.config.mutation.game_value_mutation import SetGameValueMutation
from mettagrid.config.mutation.mutation import EntityTarget
from mettagrid.config.mutation.raycast_spawn_mutation import RaycastSpawnMutation
from mettagrid.config.mutation.resource_mutation import ResourceDeltaMutation
from mettagrid.config.mutation.spawn_object_mutation import SpawnObjectMutation
from mettagrid.config.obs_config import GlobalObsConfig, ObsConfig
from mettagrid.config.render_config import RenderConfig
from mettagrid.config.reward_config import inventoryReward
from mettagrid.config.vibes import Vibe
from mettagrid.map_builder.ascii import AsciiMapBuilder

# ===== Constants =====

RESOURCE_NAMES = [
    "bomb_count",
    "bomb_range",
    "bomb_range_transfer",
    "bomb_slots",
    "hp",
    "fuse",
    "crate_hp",
    "life",
    "bomb_regen",
]

BOMB_MAX = 3  # base cap on bombs an agent can hold (before count_up upgrades)
BOMB_SLOTS_MAX = 5  # absolute ceiling — even count_up can't push past this
BOMB_REGEN_COST = 10  # bomb_regen ticks needed to earn a new bomb
FUSE_TICKS = 5  # ticks from placement to explosion
BLAST_RANGE = 2  # starting blast cells along each cardinal arm
BOMB_RANGE_MAX = 5  # max blast range an agent can hold
HP_MAX = 3  # agent starting / max hp
EXPLOSION_LIFE = 2  # life=2 → same-tick cleanup decrements to 1 → next tick removes → 1 visible tick
DEFAULT_MAX_STEPS = 500

BOMB_VIBES: list[Vibe] = [
    Vibe("😐", "default", category="emotion"),
    Vibe("💣", "bomb", category="emotion"),
]

# 11 x 9 ASCII grid. Two spawns at opposite corners with open space adjacent
# so the first bomb can blast in multiple directions. A crate sits two cells
# from each spawn along the agent's first natural move, making the crate
# destruction test deterministic. The middle of the map is a mix of empty
# cells and crates to give the policy something to interact with.
MAP_11x9: list[list[str]] = [
    list("###########"),
    list("#@........#"),
    list("#...C.C...#"),
    list("#.C..C..C.#"),
    list("#..C...C..#"),
    list("#.C..C..C.#"),
    list("#...C.C...#"),
    list("#........@#"),
    list("###########"),
]


# ===== Queries =====


def _exploding_bombs_query():
    """Bombs whose fuse has reached 0.

    ``targetHas`` is ``>=`` semantics, so ``isNot(targetHas({"fuse": 1}))``
    matches "fuse is not >= 1", i.e. exactly 0.
    """
    return query(typeTag("bomb"), [isNot(targetHas({"fuse": 1}))])


def _blast_raycast():
    """Raycast from every exploding bomb, blocked by walls, crates, and
    agents.

    max_range reads ``bomb_range_transfer`` from each source bomb's
    inventory. That value is deposited onto the bomb at placement time by
    the ``place_bomb`` handler (copying the placing agent's ``bomb_range``),
    so powerups that upgrade the agent's range actually extend the blast.

    Agents are blockers so that a cog in the blast path absorbs the hit
    and shields anything further down the ray (classic Bomberman-style
    bodyblock). ``include_blocker=True`` still lets the blast damage the
    agent it blocks on.
    """
    return raycastQuery(
        source=_exploding_bombs_query(),
        max_range=InventoryValue(item="bomb_range_transfer"),
        blocker=[isA("wall"), isA("crate"), isA("agent")],
        include_blocker=True,
    )


# ===== Move handler =====


def _place_bomb_handler() -> Handler:
    """Move handler (inserted at move.handlers[0]): while in ``bomb`` vibe
    and with at least 1 ``bomb_count``, moving into an empty cell drops a
    bomb there and decrements bomb_count instead of walking.

    After spawning the bomb (which sets ``ctx.target``), the agent's
    current ``bomb_range`` is copied into a scratch ``bomb_range_transfer``
    slot on the agent and then deposited onto the freshly spawned bomb.
    The blast raycast reads ``bomb_range_transfer`` from the bomb, so this
    wires powerup upgrades through to actual blast radius at placement time.
    ``TargetLocEmptyFilter`` guarantees the spawn cell is empty, so the
    chain never short-circuits mid-sequence.

    After the bomb is placed, the agent's vibe is auto-reset to
    ``default`` so the next move action walks instead of trying to place
    another bomb — matching the intuition that "drop bomb, then flee".
    """
    return Handler(
        name="place_bomb",
        filters=[
            VibeFilter(target=HandlerTarget.ACTOR, vibe="bomb"),
            ResourceFilter(target=HandlerTarget.ACTOR, resources={"bomb_count": 1}),
            TargetLocEmptyFilter(),
        ],
        mutations=[
            # 1. Spawn the bomb; ctx.target is now the new bomb.
            SpawnObjectMutation(object_type="bomb"),
            # 2. actor.bomb_range_transfer += actor.bomb_range (delta semantics).
            #    The scratch slot starts at 0 each tick because step 3 drains it,
            #    so += behaves like =.
            SetGameValueMutation(
                value=InventoryValue(item="bomb_range_transfer"),
                source=InventoryValue(item="bomb_range"),
                target=EntityTarget.ACTOR,
            ),
            # 3. Transfer actor.bomb_range_transfer → target (bomb).bomb_range_transfer.
            deposit({"bomb_range_transfer": -1}),
            # 4. Decrement the placing agent's bomb budget.
            ResourceDeltaMutation(target="actor", deltas={"bomb_count": -1}),
            # 5. Reset the agent's vibe to default. Dropping a bomb is a
            #    one-shot action; the next move should walk, not try to
            #    place another bomb. Saves one change_vibe action per
            #    placement.
            ChangeVibeMutation(target=EntityTarget.ACTOR, vibe_name="default"),
        ],
    )


# (bomb regen is now handled by events in the blast pipeline)


# ===== Blast pipeline (events — fire BEFORE actions each tick) =====


def _bomb_events() -> dict[str, EventConfig]:
    """The blast pipeline must run before agent actions so that damage
    lands on the tick the blast is visible, not a tick later. Events fire
    in alphabetical key order within a timestep, so we define the pipeline
    as an ordered Python list and auto-number the keys.

    Within each event, mutations run in list order.
    """

    exploding = _exploding_bombs_query()
    blast = _blast_raycast()

    pipeline: list[tuple[str, EventConfig]] = [
        # 1. Decrement fuse on every bomb.
        ("fuse_tick", EventConfig(
            name="fuse_tick",
            target_query=query(typeTag("bomb")),
            timesteps=periodic(start=0, period=1),
            mutations=[updateTarget({"fuse": -1})],
        )),
        # 2. Spawn cross-shaped explosion markers from each fuse=0 bomb.
        #    RaycastSpawnMutation uses ctx.target (the bomb) as the ray
        #    origin, so this must be a per-target event. Does NOT remove
        #    the bomb — damage events below still need it as a raycast source.
        ("spawn_blast", EventConfig(
            name="spawn_blast",
            target_query=exploding,
            timesteps=periodic(start=0, period=1),
            mutations=[
                RaycastSpawnMutation(
                    object_type="explosion",
                    directions=["north", "south", "east", "west"],
                    max_range=InventoryValue(item="bomb_range_transfer"),
                    # Match _blast_raycast's blocker set so explosion
                    # markers visually stop where the damage stops.
                    blocker=[isA("wall"), isA("crate"), isA("agent")],
                ),
            ],
        )),
        # 3a. Drain crate_hp along the blast path.
        #     Removal is split out into a separate event (cleanup_crates)
        #     below so variants can hook between "crate at 0 hp" and the
        #     actual grid removal — e.g. the powerups variant spawns a
        #     pickup at the crate's cell before cleanup.
        ("damage_crates", EventConfig(
            name="damage_crates",
            target_query=blast,
            timesteps=periodic(start=0, period=1),
            filters=[isA("crate")],
            mutations=[updateTarget({"crate_hp": -1})],
        )),
        # 3b. Damage alive agents along the blast path.
        ("damage_agents", EventConfig(
            name="damage_agents",
            target_query=blast,
            timesteps=periodic(start=0, period=1),
            filters=[isA("agent"), targetHas({"hp": 1})],
            mutations=[updateTarget({"hp": -1})],
        )),
        # 3c. Remove crates whose hp reached 0. Runs after damage_crates so
        #     any variant-added loot-drop events (keyed alphabetically between
        #     damage_crates and cleanup_crates, e.g. bomb_02a_drop_range_up)
        #     see the destroyed crate and can act on it before it's gone.
        ("cleanup_crates", EventConfig(
            name="cleanup_crates",
            target_query=query(typeTag("crate"), [isNot(targetHas({"crate_hp": 1}))]),
            timesteps=periodic(start=0, period=1),
            mutations=[withdraw({"crate_hp": 0}, remove_when_empty=True)],
        )),
        # 5. Remove fuse=0 bombs after damage events have used them as
        #    raycast sources.
        ("remove_exploded", EventConfig(
            name="remove_exploded",
            target_query=exploding,
            timesteps=periodic(start=0, period=1),
            mutations=[
                # Zero out bomb_range_transfer so inventory is fully empty
                # for removal. (bomb_range itself never lives on the bomb —
                # only the transfer scratch slot does.)
                updateTarget({"bomb_range_transfer": -BOMB_RANGE_MAX}),
                withdraw({"fuse": 0}, remove_when_empty=True),
            ],
        )),
        # 6. Decrement explosion life and remove when empty.
        ("cleanup_explosion", EventConfig(
            name="cleanup_explosion",
            target_query=query(typeTag("explosion")),
            timesteps=periodic(start=0, period=1),
            mutations=[
                updateTarget({"life": -1}),
                withdraw({"life": 0}, remove_when_empty=True),
            ],
        )),
        # 7. Accumulate bomb_regen on agents below max bomb_count.
        #    Agents at BOMB_MAX bombs don't accumulate (filter excludes them).
        ("regen_accumulate", EventConfig(
            name="regen_accumulate",
            # Only accumulate on agents below their (dynamic) bomb_count cap.
            # bomb_count cap = bomb_slots, so "below cap" = bomb_count < bomb_slots.
            # GameValueFilter checks `value >= min`; negate to get `<`.
            target_query=query(
                typeTag("agent"),
                [
                    isNot(
                        GameValueFilter(
                            target=HandlerTarget.TARGET,
                            value=InventoryValue(item="bomb_count"),
                            min=InventoryValue(item="bomb_slots"),
                        )
                    )
                ],
            ),
            timesteps=periodic(start=0, period=1),
            mutations=[updateTarget({"bomb_regen": 1})],
        )),
        # 8. Convert accumulated regen into a bomb when threshold is reached.
        ("regen_convert", EventConfig(
            name="regen_convert",
            target_query=query(typeTag("agent"), [targetHas({"bomb_regen": BOMB_REGEN_COST})]),
            timesteps=periodic(start=0, period=1),
            mutations=[
                updateTarget({"bomb_count": 1}),
                updateTarget({"bomb_regen": -BOMB_REGEN_COST}),
            ],
        )),
    ]

    # Auto-number so alphabetical dict order matches list order.
    return {f"bomb_{i:02d}_{name}": cfg for i, (name, cfg) in enumerate(pipeline)}


def _bombercog_map() -> AsciiMapBuilder.Config:
    return AsciiMapBuilder.Config(
        map_data=[list(row) for row in MAP_11x9],
        char_to_map_name={
            "#": "wall",
            ".": "empty",
            "@": "agent.agent",
            "C": "crate",
        },
    )


# ===== Mission =====


class BombercogMission(CoGameMission):
    """2-player Bomberman-style deathmatch."""

    default_variant: str | None = None
    max_steps: int = Field(default=DEFAULT_MAX_STEPS)

    @classmethod
    def create(cls, num_agents: int, max_steps: int) -> BombercogMission:
        return cls(
            name="bombercog",
            description="Bomberman-style deathmatch (2–4 players)",
            map_builder=_bombercog_map(),
            num_cogs=num_agents,
            min_cogs=2,
            # 2 for base game, 4 for the four_player variant. Variants can
            # further change env.game.num_agents in modify_env.
            max_cogs=4,
            max_steps=max_steps,
        )

    def make_base_env(self) -> MettaGridConfig:
        num_cogs = cast(int, self.num_cogs)

        move = MoveActionConfig()
        move.handlers.insert(0, _place_bomb_handler())

        agent = AgentConfig(
            inventory=InventoryConfig(
                initial={
                    "bomb_count": BOMB_MAX,
                    "bomb_range": BLAST_RANGE,
                    "bomb_range_transfer": 0,
                    # bomb_slots drives the effective bomb_count cap via the
                    # "bombs" modifier below. Start at BOMB_MAX so the base
                    # game feels identical; count_up pickups raise this up to
                    # BOMB_SLOTS_MAX.
                    "bomb_slots": BOMB_MAX,
                    "hp": HP_MAX,
                },
                limits={
                    # base is the effective cap (formula: min(max, max(base, modifier_sum))).
                    # Without modifiers, `base` acts as the ceiling. `max` is a hard upper
                    # bound used only when modifiers push the limit higher. bomb_count's
                    # effective cap = bomb_slots (each slot adds +1), capped at BOMB_SLOTS_MAX.
                    "bombs": ResourceLimitsConfig(
                        base=0,
                        max=BOMB_SLOTS_MAX,
                        resources=["bomb_count"],
                        modifiers={"bomb_slots": 1},
                    ),
                    "slots": ResourceLimitsConfig(
                        base=BOMB_SLOTS_MAX, max=BOMB_SLOTS_MAX, resources=["bomb_slots"]
                    ),
                    "range": ResourceLimitsConfig(base=BOMB_RANGE_MAX, max=BOMB_RANGE_MAX, resources=["bomb_range"]),
                    # Scratch slot used by place_bomb to carry bomb_range → bomb.
                    # Large enough to hold any BOMB_RANGE_MAX-sized transfer.
                    "range_transfer": ResourceLimitsConfig(
                        base=BOMB_RANGE_MAX,
                        max=BOMB_RANGE_MAX,
                        resources=["bomb_range_transfer"],
                    ),
                    "hp": ResourceLimitsConfig(base=HP_MAX, max=HP_MAX, resources=["hp"]),
                    "regen": ResourceLimitsConfig(base=BOMB_REGEN_COST, max=BOMB_REGEN_COST, resources=["bomb_regen"]),
                },
            ),
            rewards={"hp": inventoryReward("hp", weight=0.1, per_tick=True)},
        )

        game = GameConfig(
            map_builder=self.map_builder,
            max_steps=self.max_steps,
            num_agents=num_cogs,
            resource_names=RESOURCE_NAMES,
            obs=ObsConfig(
                global_obs=GlobalObsConfig(
                    local_position=True,
                    last_action_move=True,
                ),
            ),
            actions=ActionsConfig(
                noop=NoopActionConfig(),
                move=move,
                change_vibe=ChangeVibeActionConfig(vibes=BOMB_VIBES),
            ),
            agents=[agent.model_copy(deep=True) for _ in range(num_cogs)],
            objects={
                "wall": WallConfig(name="wall"),
                "crate": GridObjectConfig(
                    name="crate",
                    inventory=InventoryConfig(
                        initial={"crate_hp": 1},
                        limits={
                            "crate_hp": ResourceLimitsConfig(base=1, max=1, resources=["crate_hp"]),
                        },
                    ),
                ),
                "bomb": GridObjectConfig(
                    name="bomb",
                    inventory=InventoryConfig(
                        # Bombs start with no range; the place_bomb handler
                        # deposits bomb_range_transfer from the placing agent.
                        initial={"fuse": FUSE_TICKS, "bomb_range_transfer": 0},
                        limits={
                            "fuse": ResourceLimitsConfig(
                                base=FUSE_TICKS,
                                max=FUSE_TICKS,
                                resources=["fuse"],
                            ),
                            "range_transfer": ResourceLimitsConfig(
                                base=BOMB_RANGE_MAX,
                                max=BOMB_RANGE_MAX,
                                resources=["bomb_range_transfer"],
                            ),
                        },
                    ),
                ),
                "explosion": GridObjectConfig(
                    name="explosion",
                    inventory=InventoryConfig(
                        initial={"life": EXPLOSION_LIFE},
                        limits={
                            "life": ResourceLimitsConfig(
                                base=EXPLOSION_LIFE,
                                max=EXPLOSION_LIFE,
                                resources=["life"],
                            ),
                        },
                    ),
                ),
            },
            events=_bomb_events(),
            render=RenderConfig(
                assets={"agent": []},
                object_status={"agent": {}},
            ),
        )
        return MettaGridConfig(game=game)
