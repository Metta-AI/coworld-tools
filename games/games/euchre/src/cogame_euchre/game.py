"""Euchre: a 4-player trick-taking card game with teams.

All game logic is expressed as declarative mettagrid config (handlers, events,
mutations, filters). No Python wrapper or controller runs during simulation.

v1 simplifications:
- Single hand per episode (5 tricks)
- Fixed trump (random at deal time)
- Event-driven turns: active player advances when a card is played
- Trick winner leads next trick
- Follow-suit enforcement via per-suit agent counts
"""

from __future__ import annotations

import random

from mettagrid.config.action_config import ActionsConfig, ChangeVibeActionConfig, MoveActionConfig, NoopActionConfig
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.filter import (
    GameValueFilter,
    HandlerTarget,
    hasTag,
    isNot,
    query,
    targetHas,
)
from mettagrid.config.game_value import (
    ConstValue,
    InventoryValue,
    MaxGameValue,
    QueryInventoryValue,
    Scope,
    StatValue,
)
from mettagrid.config.handler_config import Handler, firstMatch
from mettagrid.config.mettagrid_config import (
    AgentConfig,
    GameConfig,
    GlobalObsConfig,
    GridObjectConfig,
    InventoryConfig,
    MettaGridConfig,
    ObsConfig,
    ResourceLimitsConfig,
    WallConfig,
)
from mettagrid.config.mutation import (
    StatsMutation,
    StatsTarget,
    addTag,
    logActorAgentStat,
    logStatToGame,
    queryDelta,
    queryDeposit,
    removeTag,
    updateActor,
    updateTarget,
    withdraw,
)
from mettagrid.config.render_config import RenderAsset, RenderConfig
from mettagrid.config.reward_config import reward
from mettagrid.config.tag import typeTag
from mettagrid.map_builder.ascii import AsciiMapBuilderConfig
from pydantic import Field

from cogame_euchre.framework import CoGame, CoGameMission, register_game

# ---------------------------------------------------------------------------
# Card definitions
# ---------------------------------------------------------------------------

SUITS = ("h", "d", "c", "s")
RANKS = ("9", "10", "j", "q", "k", "a")
SUIT_NAMES = {"h": "hearts", "d": "diamonds", "c": "clubs", "s": "spades"}
SAME_COLOR = {"h": "d", "d": "h", "c": "s", "s": "c"}
SUIT_ID = {"h": 1, "d": 2, "c": 3, "s": 4}

CARD_RESOURCES = [f"card_{rank}{suit}" for suit in SUITS for rank in RANKS]

# Per-suit count resources on agents (tracks how many cards of each suit remain in hand)
SUIT_COUNT_RESOURCES = [f"suit_{sid}" for sid in range(1, 5)]

# Game state resources
STATE_RESOURCES = [
    "card_power",
    "card_suit_id",
    "player_id",
    "team_id",
    "has_card",
    "cards_played",
    "led_suit",
    "trick_count_a",
    "trick_count_b",
]

ALL_RESOURCES = CARD_RESOURCES + SUIT_COUNT_RESOURCES + STATE_RESOURCES

DEFAULT_MAX_STEPS = 200

NUM_PLAYERS = 4
NUM_TRICKS = 5
CARDS_PER_HAND = 5
DECK_SIZE = 24

# Game stat used to track whose turn it is (1-based player ID).
CURRENT_PLAYER_STAT = StatValue(name="current_player", scope=Scope.GAME)


def compute_card_suit(card_resource: str, trump_suit: str) -> int:
    """Return the effective suit ID (1-4) of a card, accounting for bowers.

    The left bower (jack of same-color suit) plays as trump, not its printed suit.
    """
    name = card_resource[len("card_") :]
    suit = name[-1]
    rank = name[:-1]
    # Left bower belongs to the trump suit
    if rank == "j" and suit == SAME_COLOR[trump_suit]:
        return SUIT_ID[trump_suit]
    return SUIT_ID[suit]


def compute_card_power(card_resource: str, trump_suit: str) -> int:
    """Compute the trick-taking power of a card given the trump suit.

    Right bower (J of trump) = 106, Left bower (J of same color) = 105,
    Trump A=104..9=100, Non-trump A=14..9=9.
    """
    name = card_resource[len("card_") :]  # "9h", "10s", etc.
    suit = name[-1]
    rank = name[:-1]

    if rank == "j" and suit == trump_suit:
        return 106
    if rank == "j" and suit == SAME_COLOR[trump_suit]:
        return 105
    if suit == trump_suit:
        trump_ranks = {"a": 104, "k": 103, "q": 102, "10": 101, "9": 100}
        return trump_ranks[rank]
    base_ranks = {"a": 14, "k": 13, "q": 12, "j": 11, "10": 10, "9": 9}
    return base_ranks[rank]


# ---------------------------------------------------------------------------
# Map layout
# ---------------------------------------------------------------------------

CARD_SLOT_CHARS = "abcdefghijklmnopqrst"  # 20 card slots
PLAY_SLOT_CHARS = "1234"
CONTROLLER_CHAR = "K"

# Spawn positions ordered top-to-bottom, left-to-right (engine scan order).
# The agent configs list must match this order.
# Scan order: (2,6)=P2, (9,1)=P1, (9,11)=P3, (12,6)=P0
SPAWN_ORDER = [2, 1, 3, 0]  # player indices in map scan order

MAP_DATA = [
    "#############",
    "#...klmno...#",
    "#.....@.....#",
    "#...........#",
    "#...........#",
    "#f....3....p#",
    "#g...2K4...q#",
    "#h....1....r#",
    "#i.........s#",
    "#j.........t#",
    "#.@.......@.#",
    "#...........#",
    "#.....@.....#",
    "#...abcde...#",
    "#############",
]


def _build_char_to_map_name() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for i, ch in enumerate(CARD_SLOT_CHARS):
        player = i // CARDS_PER_HAND
        slot = i % CARDS_PER_HAND
        mapping[ch] = f"card_slot_p{player}_{slot}"
    for i, ch in enumerate(PLAY_SLOT_CHARS):
        mapping[ch] = f"play_slot_{i}"
    mapping[CONTROLLER_CHAR] = "controller"
    return mapping


# ---------------------------------------------------------------------------
# Filters: "is it this player's turn?"
# ---------------------------------------------------------------------------


def _is_current_player_filters() -> list:
    """Filters that pass only when actor's player_id == current_player game stat.

    Uses two dynamic GameValueFilters to express equality:
      player_id >= current_player AND current_player >= player_id
    """
    return [
        GameValueFilter(
            filter_type="game_value",
            target=HandlerTarget.ACTOR,
            value=InventoryValue(item="player_id"),
            min=CURRENT_PLAYER_STAT,
        ),
        GameValueFilter(
            filter_type="game_value",
            target=HandlerTarget.ACTOR,
            value=CURRENT_PLAYER_STAT,
            min=InventoryValue(item="player_id"),
        ),
    ]


# ---------------------------------------------------------------------------
# Object configs
# ---------------------------------------------------------------------------


def _controller_config() -> GridObjectConfig:
    return GridObjectConfig(
        name="controller",
        inventory=InventoryConfig(
            initial={
                "cards_played": 0,
                "led_suit": 0,
                "trick_count_a": 0,
                "trick_count_b": 0,
            },
        ),
    )


PLAY_SLOT_TAG = "role:play_slot"


def _play_slot_config(slot_idx: int) -> GridObjectConfig:
    return GridObjectConfig(
        name=f"play_slot_{slot_idx}",
        tags=[PLAY_SLOT_TAG],
        inventory=InventoryConfig(
            initial={"card_power": 0, "team_id": 0, "player_id": 0},
        ),
    )


def _card_slot_config(
    player: int,
    slot_idx: int,
    card_resource: str,
    card_power: int,
    card_suit_id: int,
) -> GridObjectConfig:
    """Card slot holding one dealt card. On use: transfer card to play area
    and advance the turn to the next player.

    Follow-suit: if the led suit is set and the agent holds cards of that suit,
    only cards matching the led suit can be played.
    """
    team = player % 2  # P0,P2 = team 0; P1,P3 = team 1
    player_id = player + 1  # 1-based
    initial: dict[str, int] = {
        card_resource: 1,
        "card_power": card_power,
        "card_suit_id": card_suit_id,
        "has_card": 1,
    }

    play_q = query(typeTag(f"play_slot_{player}"))
    controller_q = query(typeTag("controller"))
    card_transfer = {card_resource: 1, "card_power": card_power}
    slot_drain = {card_resource: 1, "card_power": card_power, "card_suit_id": card_suit_id, "has_card": 1}

    # --- Follow-suit filter ---
    # The led suit is stored on the controller. This card can be played if:
    #   (a) no suit led yet (first play of trick), OR
    #   (b) this card's suit matches the led suit, OR
    #   (c) the agent has no cards of the led suit
    led_suit_value = QueryInventoryValue(query=controller_q, item="led_suit")
    suit_count_resource = f"suit_{card_suit_id}"

    # (a) led_suit == 0: no suit has been led
    no_suit_led = isNot(
        GameValueFilter(filter_type="game_value", target=HandlerTarget.TARGET, value=led_suit_value, min=1)
    )
    # (b) card_suit_id == led_suit (equality via two >= checks)
    card_suit_const = ConstValue(value=float(card_suit_id))
    card_matches_led = [
        GameValueFilter(
            filter_type="game_value", target=HandlerTarget.TARGET, value=card_suit_const, min=led_suit_value
        ),
        GameValueFilter(
            filter_type="game_value", target=HandlerTarget.TARGET, value=led_suit_value, min=card_suit_const
        ),
    ]
    # Follow-suit uses FirstMatch handler dispatch:
    # 1. play_card_lead: first card of trick (no led suit) → set led_suit
    # 2. play_card_follow: card matches led suit → play it
    # 3. play_card_void_{1-4}: for each possible led suit, if agent is void → play any card

    common_filters = [
        *_is_current_player_filters(),
        targetHas({"has_card": 1}),
        GameValueFilter(
            filter_type="game_value", target=HandlerTarget.ACTOR, value=InventoryValue(item="player_id"), min=player_id
        ),
        isNot(
            GameValueFilter(
                filter_type="game_value",
                target=HandlerTarget.ACTOR,
                value=InventoryValue(item="player_id"),
                min=player_id + 1,
            )
        ),
    ]

    common_mutations = [
        withdraw(slot_drain, remove_when_empty=True),
        queryDeposit(play_q, card_transfer),
        queryDelta(play_q, {"team_id": team + 1, "player_id": player_id}),
        queryDelta(controller_q, {"cards_played": 1}),
        # Decrement agent's suit count
        updateActor({suit_count_resource: -1}),
        logStatToGame("current_player"),
        logActorAgentStat("cards_played"),
        logStatToGame("cards_played"),
    ]

    handlers: list[Handler] = [
        # First card of trick: no suit led, so set led_suit.
        Handler(
            name="play_card_lead",
            filters=[
                *common_filters,
                no_suit_led,  # cards_played == 0 on controller (no led suit)
            ],
            mutations=[
                *common_mutations,
                # Set led_suit on controller to this card's suit
                queryDelta(controller_q, {"led_suit": card_suit_id}),
            ],
        ),
        # Subsequent cards: must follow suit if able.
        Handler(
            name="play_card_follow",
            filters=[
                *common_filters,
                *card_matches_led,
            ],
            mutations=list(common_mutations),
        ),
    ]

    # Handlers 3-6: Void in led suit (one per possible led suit value).
    for sid in range(1, 5):
        sv = ConstValue(value=float(sid))
        handlers.append(
            Handler(
                name=f"play_card_void_{sid}",
                filters=[
                    *common_filters,
                    # led_suit == sid
                    GameValueFilter(
                        filter_type="game_value", target=HandlerTarget.TARGET, value=led_suit_value, min=sv
                    ),
                    GameValueFilter(
                        filter_type="game_value", target=HandlerTarget.TARGET, value=sv, min=led_suit_value
                    ),
                    # actor has 0 cards of suit sid
                    isNot(
                        GameValueFilter(
                            filter_type="game_value",
                            target=HandlerTarget.ACTOR,
                            value=InventoryValue(item=f"suit_{sid}"),
                            min=1,
                        )
                    ),
                ],
                mutations=list(common_mutations),
            )
        )

    return GridObjectConfig(
        name=f"card_slot_p{player}_{slot_idx}",
        inventory=InventoryConfig(initial=initial),
        on_use_handler=firstMatch(handlers),
    )


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def _game_flow_events(max_steps: int) -> dict[str, EventConfig]:
    """Events that drive the game: init, turn wrap-around, trick eval, scoring."""
    events: dict[str, EventConfig] = {}
    controller_q = query(typeTag("controller"))
    every_tick = periodic(start=0, period=1, end=max_steps)

    # --- Initialize current_player to 1 at step 0 ---
    events["init_current_player"] = EventConfig(
        name="init_current_player",
        target_query=typeTag("controller"),
        timesteps=[0],
        mutations=[logStatToGame("current_player", delta=1)],
    )

    # --- Active player tag ---
    # Every tick: remove "current_player" tag from all agents, then add
    # it to the agent whose player_id matches current_player game stat.
    events["clear_current_player_tag"] = EventConfig(
        name="clear_current_player_tag",
        target_query=query(PLAYER_TAG),
        timesteps=every_tick,
        filters=[hasTag("current_player")],
        mutations=[removeTag("current_player")],
    )
    events["set_current_player_tag"] = EventConfig(
        name="set_current_player_tag",
        target_query=query(PLAYER_TAG),
        timesteps=every_tick,
        filters=[
            GameValueFilter(
                filter_type="game_value",
                target=HandlerTarget.TARGET,
                value=InventoryValue(item="player_id"),
                min=CURRENT_PLAYER_STAT,
            ),
            GameValueFilter(
                filter_type="game_value",
                target=HandlerTarget.TARGET,
                value=CURRENT_PLAYER_STAT,
                min=InventoryValue(item="player_id"),
            ),
        ],
        mutations=[addTag("current_player")],
        max_targets=1,
    )

    # --- Wrap current_player: 5 → 1 ---
    # After player 4 plays, current_player increments to 5.
    # This event fires every tick and subtracts 4 when >= 5.
    events["wrap_current_player"] = EventConfig(
        name="wrap_current_player",
        target_query=typeTag("controller"),
        timesteps=every_tick,
        filters=[
            GameValueFilter(
                filter_type="game_value",
                target=HandlerTarget.TARGET,
                value=CURRENT_PLAYER_STAT,
                min=5,
            ),
        ],
        mutations=[logStatToGame("current_player", delta=-4)],
    )

    # --- Trick evaluation ---
    # When cards_played reaches 4, find the play slot with the highest
    # card_power and award the trick to that team. Then bump cards_played
    # to 5 so the reset event fires next tick.
    max_played_power = MaxGameValue(
        values=[
            QueryInventoryValue(query=query(typeTag(f"play_slot_{i}")), item="card_power") for i in range(NUM_PLAYERS)
        ]
    )

    cards_played_gte_4 = GameValueFilter(
        filter_type="game_value",
        target=HandlerTarget.TARGET,
        value=QueryInventoryValue(query=controller_q, item="cards_played"),
        min=4,
    )

    # Winner is team A (team_id == 1 on play slot)
    # Prefixed with "a_" so trick eval fires before resets (alphabetical order).
    events["a_trick_winner_a"] = EventConfig(
        name="a_trick_winner_a",
        target_query=PLAY_SLOT_TAG,
        timesteps=every_tick,
        filters=[
            cards_played_gte_4,
            targetHas({"card_power": 1}),
            targetHas({"team_id": 1}),
            isNot(targetHas({"team_id": 2})),
            GameValueFilter(
                filter_type="game_value",
                target=HandlerTarget.TARGET,
                value=InventoryValue(item="card_power"),
                min=max_played_power,
            ),
        ],
        mutations=[
            queryDelta(controller_q, {"trick_count_a": 1}),
            logStatToGame("tricks_won_a"),
            # Winner leads next trick: set current_player to winner's player_id
            StatsMutation(stat="current_player", target=StatsTarget.GAME, source=InventoryValue(item="player_id")),
            # Bump cards_played to 5 so reset fires next tick
            queryDelta(controller_q, {"cards_played": 1}),
        ],
        max_targets=1,
        fallback="a_trick_winner_b",
    )

    # Winner is team B (team_id == 2)
    # Only fires as fallback from trick_winner_a (no own timesteps).
    events["a_trick_winner_b"] = EventConfig(
        name="a_trick_winner_b",
        target_query=PLAY_SLOT_TAG,
        timesteps=[],
        filters=[
            cards_played_gte_4,
            targetHas({"card_power": 1}),
            targetHas({"team_id": 2}),
            GameValueFilter(
                filter_type="game_value",
                target=HandlerTarget.TARGET,
                value=InventoryValue(item="card_power"),
                min=max_played_power,
            ),
        ],
        mutations=[
            queryDelta(controller_q, {"trick_count_b": 1}),
            logStatToGame("tricks_won_b"),
            StatsMutation(stat="current_player", target=StatsTarget.GAME, source=InventoryValue(item="player_id")),
            queryDelta(controller_q, {"cards_played": 1}),
        ],
        max_targets=1,
    )

    # --- Reset play area when cards_played >= 5 (after eval bumped it) ---
    cards_played_gte_5 = GameValueFilter(
        filter_type="game_value",
        target=HandlerTarget.TARGET,
        value=QueryInventoryValue(query=controller_q, item="cards_played"),
        min=5,
    )
    for slot in range(NUM_PLAYERS):
        events[f"b_reset_play_slot_{slot}"] = EventConfig(
            name=f"b_reset_play_slot_{slot}",
            target_query=typeTag(f"play_slot_{slot}"),
            timesteps=every_tick,
            filters=[cards_played_gte_5],
            mutations=[
                updateTarget(
                    {
                        "card_power": -9999,
                        "team_id": -9999,
                        "player_id": -9999,
                        **{cr: -9999 for cr in CARD_RESOURCES},
                    }
                ),
            ],
        )
    events["c_reset_cards_played"] = EventConfig(
        name="c_reset_cards_played",
        target_query=typeTag("controller"),
        timesteps=every_tick,
        filters=[targetHas({"cards_played": 5})],
        mutations=[updateTarget({"cards_played": -9999, "led_suit": -9999})],
    )

    # --- End-of-hand scoring ---
    score_step = max_steps - 1
    events["score_a_normal"] = EventConfig(
        name="score_a_normal",
        target_query=typeTag("controller"),
        timesteps=[score_step],
        filters=[targetHas({"trick_count_a": 3})],
        mutations=[logStatToGame("score_a")],
    )
    events["score_a_march"] = EventConfig(
        name="score_a_march",
        target_query=typeTag("controller"),
        timesteps=[score_step],
        filters=[targetHas({"trick_count_a": 5})],
        mutations=[logStatToGame("score_a")],
    )
    events["score_b_normal"] = EventConfig(
        name="score_b_normal",
        target_query=typeTag("controller"),
        timesteps=[score_step],
        filters=[targetHas({"trick_count_b": 3})],
        mutations=[logStatToGame("score_b")],
    )
    events["score_b_march"] = EventConfig(
        name="score_b_march",
        target_query=typeTag("controller"),
        timesteps=[score_step],
        filters=[targetHas({"trick_count_b": 5})],
        mutations=[logStatToGame("score_b")],
    )

    return events


# ---------------------------------------------------------------------------
# Render config
# ---------------------------------------------------------------------------


def _render_config() -> RenderConfig:
    assets: dict[str, list[RenderAsset]] = {}
    # Card face rules: show the card face based on which card resource is present.
    # Used for both hand slots and play slots.
    card_face_rules: list[RenderAsset] = [RenderAsset(asset=cr, resources={cr: 1}) for cr in CARD_RESOURCES]
    for player in range(NUM_PLAYERS):
        for slot in range(CARDS_PER_HAND):
            name = f"card_slot_p{player}_{slot}"
            assets[name] = [*card_face_rules, RenderAsset(asset="card_slot")]
    for i in range(NUM_PLAYERS):
        assets[f"play_slot_{i}"] = [*card_face_rules, RenderAsset(asset="play_slot")]
    assets["controller"] = [RenderAsset(asset="controller")]
    return RenderConfig(assets=assets)


# ---------------------------------------------------------------------------
# Agent configs
# ---------------------------------------------------------------------------

PLAYER_TAG = "role:player"


def _agent_config(player: int, suit_counts: dict[int, int] | None = None) -> AgentConfig:
    """Players 0,2 are team A; players 1,3 are team B.

    All agents share team_id=0 and name="agent" for MettaScope compat.
    Team logic is handled via the player_id resource and game events.

    suit_counts: {suit_id: count} for follow-suit tracking.
    """
    team = player % 2
    player_id = player + 1
    initial: dict[str, int] = {"player_id": player_id}
    if suit_counts:
        for sid, count in suit_counts.items():
            initial[f"suit_{sid}"] = count
    return AgentConfig(
        name="agent",
        team_id=0,
        tags=[PLAYER_TAG],
        inventory=InventoryConfig(
            initial=initial,
            limits={
                "carry": ResourceLimitsConfig(
                    base=200,
                    max=200,
                    resources=CARD_RESOURCES + ["card_power"],
                ),
            },
        ),
        rewards={
            "team_tricks": reward(
                StatValue(
                    name=f"tricks_won_{'a' if team == 0 else 'b'}",
                    scope=Scope.GAME,
                ),
                weight=0.2,
            ),
            "team_score": reward(
                StatValue(
                    name=f"score_{'a' if team == 0 else 'b'}",
                    scope=Scope.GAME,
                ),
                weight=1.0,
            ),
        },
    )


# ---------------------------------------------------------------------------
# Mission class
# ---------------------------------------------------------------------------


class EuchreMission(CoGameMission):
    """Euchre 4-player trick-taking card game mission."""

    name: str = "basic"
    description: str = "Euchre trick-taking card game"
    max_steps: int = Field(default=DEFAULT_MAX_STEPS)
    seed: int | None = Field(default=None, description="Random seed for card dealing")

    @classmethod
    def create(cls, num_agents: int = NUM_PLAYERS, max_steps: int = DEFAULT_MAX_STEPS) -> EuchreMission:
        assert num_agents == NUM_PLAYERS, f"Euchre requires exactly {NUM_PLAYERS} players, got {num_agents}"
        return cls(
            name="basic",
            description="Euchre trick-taking card game",
            map_builder=AsciiMapBuilderConfig(
                map_data=MAP_DATA,
                char_to_map_name=_build_char_to_map_name(),
            ),
            num_cogs=NUM_PLAYERS,
            min_cogs=NUM_PLAYERS,
            max_cogs=NUM_PLAYERS,
            max_steps=max_steps,
        )

    @classmethod
    def variant_module_prefixes(cls) -> tuple[str, ...]:
        return ("cogame_euchre.variants.",)

    def make_base_env(self) -> MettaGridConfig:
        rng = random.Random(self.seed)

        # Shuffle and deal
        deck = list(CARD_RESOURCES)
        rng.shuffle(deck)
        hands: list[list[str]] = [deck[i * CARDS_PER_HAND : (i + 1) * CARDS_PER_HAND] for i in range(NUM_PLAYERS)]
        trump_suit = deck[NUM_PLAYERS * CARDS_PER_HAND][-1]

        resource_names = list(ALL_RESOURCES)

        # Compute per-player suit counts for follow-suit tracking
        player_suit_counts: list[dict[int, int]] = []
        for player in range(NUM_PLAYERS):
            counts: dict[int, int] = {}
            for card in hands[player]:
                sid = compute_card_suit(card, trump_suit)
                counts[sid] = counts.get(sid, 0) + 1
            player_suit_counts.append(counts)

        objects: dict[str, GridObjectConfig] = {}
        objects["wall"] = WallConfig()
        objects["controller"] = _controller_config()
        for i in range(NUM_PLAYERS):
            objects[f"play_slot_{i}"] = _play_slot_config(i)
        for player in range(NUM_PLAYERS):
            for slot_idx, card in enumerate(hands[player]):
                power = compute_card_power(card, trump_suit)
                suit_id = compute_card_suit(card, trump_suit)
                obj = _card_slot_config(player, slot_idx, card, power, suit_id)
                objects[obj.name] = obj

        events = _game_flow_events(self.max_steps)
        tags = [PLAYER_TAG, PLAY_SLOT_TAG, "current_player"]

        game = GameConfig(
            map_builder=AsciiMapBuilderConfig(
                map_data=MAP_DATA,
                char_to_map_name=_build_char_to_map_name(),
            ),
            max_steps=self.max_steps,
            num_agents=NUM_PLAYERS,
            resource_names=resource_names,
            obs=ObsConfig(
                width=7,
                height=7,
                global_obs=GlobalObsConfig(obs={"current_player": CURRENT_PLAYER_STAT}),
            ),
            actions=ActionsConfig(
                move=MoveActionConfig(),
                noop=NoopActionConfig(),
                change_vibe=ChangeVibeActionConfig(enabled=False, vibes=[]),
            ),
            agents=[_agent_config(p, player_suit_counts[p]) for p in SPAWN_ORDER],
            objects=objects,
            events=events,
            tags=tags,
            render=_render_config(),
        )

        return MettaGridConfig(game=game)


# ---------------------------------------------------------------------------
# CoGame wrapper + registration
# ---------------------------------------------------------------------------


class EuchreCoGame(CoGame):
    """Framework-facing handle for the Euchre card game."""

    def __init__(self) -> None:
        # Local import to avoid a circular dependency at module import time
        # (variants/__init__.py may eventually import from game.py).
        from cogame_euchre.variants import ALL_VARIANT_TYPES

        super().__init__(
            name="euchre",
            missions=[EuchreMission.create()],
            variants=[cls() for cls in ALL_VARIANT_TYPES],
        )


register_game(EuchreCoGame())
