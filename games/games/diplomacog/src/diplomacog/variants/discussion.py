"""Talk-driven discussion session modifiers for diplomacy."""

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.config.event_config import EventConfig
from mettagrid.config.game_value import QueryInventoryValue
from mettagrid.config.handler_config import Handler, allOf, updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig, TalkConfig
from mettagrid.config.mutation.stats_mutation import StatsMutation

from diplomacog.game import (
    CAMPAIGN_YEAR_LENGTH,
    SPRING_ORDERS_LENGTH,
    SPRING_RETREAT_LENGTH,
    campaign_anchor_hub,
    campaign_anchor_query,
)
from diplomacog.variants.mechanics import CoreVariant

DISCUSSION_PHASE_RESOURCE = "phase_discussion"
DISCUSSION_WINDOW_STEPS = 8
DISCUSSION_TALK_COOLDOWN_STEPS = 1
DISCUSSION_OBS_WIDTH = 15
DISCUSSION_OBS_HEIGHT = 15
DISCUSSION_NUM_TOKENS = 1200


class DiscussionSessionsVariant(CoGameMissionVariant):
    name: str = "discussion_sessions"
    description: str = "Enable talk-driven summit windows around the diplomacy station before major pushes."

    def dependencies(self) -> Deps:
        return Deps(required=[CoreVariant])

    def modify_mission(self, mission) -> None:
        if hasattr(mission, "spawn_focus"):
            mission.spawn_focus = "summit"

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        if DISCUSSION_PHASE_RESOURCE not in env.game.resource_names:
            env.game.resource_names.append(DISCUSSION_PHASE_RESOURCE)

        # Summit windows should be dense enough for two-turn negotiations without consuming a quarter
        # of each campaign year.
        env.game.talk = TalkConfig(enabled=True, max_length=140, cooldown_steps=DISCUSSION_TALK_COOLDOWN_STEPS)
        # Packed coordinates currently cap observation windows at 15x15.
        env.game.obs.width = max(env.game.obs.width, DISCUSSION_OBS_WIDTH)
        env.game.obs.height = max(env.game.obs.height, DISCUSSION_OBS_HEIGHT)
        env.game.obs.num_tokens = max(env.game.obs.num_tokens, DISCUSSION_NUM_TOKENS)

        anchor_hub = env.game.objects.get(campaign_anchor_hub())
        if anchor_hub is not None:
            anchor_hub.inventory.initial.setdefault(DISCUSSION_PHASE_RESOURCE, 0)

        anchor_query = campaign_anchor_query()
        env.game.obs.global_obs.obs["global.phase_discussion"] = QueryInventoryValue(
            query=anchor_query,
            item=DISCUSSION_PHASE_RESOURCE,
        )
        env.game.on_tick = allOf(
            [
                env.game.on_tick,
                Handler(
                    name="track_phase_discussion",
                    mutations=[
                        StatsMutation(
                            stat="diplomacy/phase_discussion",
                            source=QueryInventoryValue(query=anchor_query, item=DISCUSSION_PHASE_RESOURCE),
                        )
                    ],
                ),
            ]
        )

        for year_idx, year_start in enumerate(range(0, env.game.max_steps + 1, CAMPAIGN_YEAR_LENGTH)):
            self._add_discussion_window(
                env,
                name=f"campaign_{year_idx}_spring_discussion",
                start_step=year_start,
            )

            fall_orders_start = year_start + SPRING_ORDERS_LENGTH + SPRING_RETREAT_LENGTH
            self._add_discussion_window(
                env,
                name=f"campaign_{year_idx}_fall_discussion",
                start_step=fall_orders_start,
            )

    @staticmethod
    def _add_discussion_window(env: MettaGridConfig, *, name: str, start_step: int) -> None:
        end_step = start_step + DISCUSSION_WINDOW_STEPS
        if start_step > env.game.max_steps or end_step > env.game.max_steps:
            return

        env.game.events[f"{name}_start"] = EventConfig(
            name=f"{name}_start",
            target_query=campaign_anchor_query(),
            timesteps=[start_step],
            mutations=[updateTarget({DISCUSSION_PHASE_RESOURCE: 1})],
            max_targets=1,
        )

        env.game.events[f"{name}_end"] = EventConfig(
            name=f"{name}_end",
            target_query=campaign_anchor_query(),
            timesteps=[end_step],
            mutations=[updateTarget({DISCUSSION_PHASE_RESOURCE: -1})],
            max_targets=1,
        )
