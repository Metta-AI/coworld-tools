"""Pressure and conflict profile modifiers for diplomacy."""

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from mettagrid.config.event_config import EventConfig, periodic
from mettagrid.config.handler_config import updateTarget
from mettagrid.config.mettagrid_config import MettaGridConfig

from diplomacog.game import COUNTRY_HUBS, drop_named_handler, find_named_handler
from diplomacog.variants.discussion import DiscussionSessionsVariant


class CrisisSurgeVariant(CoGameMissionVariant):
    name: str = "crisis_surge"
    description: str = "Faster and stronger crisis waves across all country hubs."

    def dependencies(self) -> Deps:
        return Deps(required=[DiscussionSessionsVariant])

    @staticmethod
    def _halve_period(event: EventConfig, max_steps: int) -> None:
        if len(event.timesteps) < 2:
            return
        current_period = max(1, event.timesteps[1] - event.timesteps[0])
        event.timesteps = periodic(start=event.timesteps[0], period=max(1, current_period // 2), end=max_steps)

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        for event_name, event in env.game.events.items():
            if not event_name.endswith("_crisis_wave"):
                continue
            self._halve_period(event, env.game.max_steps)
            for mutation in event.mutations:
                deltas = getattr(mutation, "deltas", None)
                if deltas is None:
                    continue
                if "crisis" in deltas:
                    deltas["crisis"] += 1
                if "stability" in deltas:
                    deltas["stability"] -= 1


class SabotageHeavyVariant(CoGameMissionVariant):
    name: str = "sabotage_heavy"
    description: str = "More damaging sabotage and periodic covert pressure events."

    def dependencies(self) -> Deps:
        return Deps(required=[DiscussionSessionsVariant])

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        for hub in COUNTRY_HUBS:
            hub_cfg = env.game.objects.get(hub)
            if hub_cfg is None:
                continue
            sabotage_handler = find_named_handler(hub_cfg.on_use_handler, "sabotage_hub")
            if sabotage_handler is None:
                continue
            for mutation in sabotage_handler.mutations:
                deltas = getattr(mutation, "deltas", None)
                if deltas is None:
                    continue
                deltas["crisis"] = deltas.get("crisis", 0) + 1
                deltas["stability"] = deltas.get("stability", 0) - 1

        for idx, hub in enumerate(COUNTRY_HUBS):
            event_name = f"{hub}_black_ops"
            env.game.events[event_name] = EventConfig(
                name=event_name,
                target_query=f"type:{hub}",
                timesteps=periodic(start=10 + idx * 3, period=25, end=env.game.max_steps),
                mutations=[updateTarget({"crisis": 1, "stability": -1})],
                max_targets=1,
            )


class DetenteVariant(CoGameMissionVariant):
    name: str = "detente"
    description: str = "Lower conflict profile with slower crisis growth and no sabotage station."

    def dependencies(self) -> Deps:
        return Deps(required=[DiscussionSessionsVariant])

    @staticmethod
    def _stretch_period(event: EventConfig, max_steps: int) -> None:
        if len(event.timesteps) < 2:
            return
        current_period = max(1, event.timesteps[1] - event.timesteps[0])
        event.timesteps = periodic(start=event.timesteps[0], period=max(1, int(current_period * 1.75)), end=max_steps)

    def modify_env(self, mission, env: MettaGridConfig) -> None:
        env.game.objects.pop("sabotage_station", None)
        instance = getattr(env.game.map_builder, "instance", None)
        if instance is not None and hasattr(instance, "include_sabotage_station"):
            instance.include_sabotage_station = False

        env.game.render.assets.pop("sabotage_station", None)

        for hub_name in COUNTRY_HUBS:
            hub_cfg = env.game.objects.get(hub_name)
            if hub_cfg is None:
                continue
            hub_cfg.on_use_handler = drop_named_handler(hub_cfg.on_use_handler, "sabotage_hub")

        to_remove = [name for name in env.game.events if name.endswith("_black_ops")]
        for name in to_remove:
            env.game.events.pop(name, None)

        for event_name, event in env.game.events.items():
            if not event_name.endswith("_crisis_wave"):
                continue
            self._stretch_period(event, env.game.max_steps)
            for mutation in event.mutations:
                deltas = getattr(mutation, "deltas", None)
                if deltas is None:
                    continue
                if "crisis" in deltas:
                    deltas["crisis"] = max(1, deltas["crisis"] - 1)
                if "stability" in deltas:
                    deltas["stability"] += 1
