"""Scripted policy for the Overcogged game."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

from overcogged.game.game import (
    BASE_AGENT_RESOURCES,
    CHOP_MEAT_PROGRESS,
    CHOP_VEG_PROGRESS,
    CHOPPED_MEAT,
    CHOPPED_VEG,
    CLEAN_PLATE,
    DIRTY_PLATE,
    DISH_RESOURCE_BY_RECIPE,
    FRYER_FRIES_BURNED,
    FRYER_FRIES_COOKING,
    FRYER_FRIES_READY,
    MEAT,
    POT_SOUP_BURNED,
    POT_SOUP_COOKING,
    POT_SOUP_READY,
    QUEUE_FRIES,
    QUEUE_RESOURCE_BY_RECIPE,
    QUEUE_SALAD,
    QUEUE_SOUP,
    VEG,
    WASH_PROGRESS,
)

from .entity_map import Entity, EntityMap
from .navigator import Navigator, manhattan, move_toward
from .obs_parser import ObsParser

RecipeName = Literal["salad", "soup", "fries"]
RoleName = Literal["all_rounder", "prep", "cook", "server"]
StationTask = Literal["chop_veg", "chop_meat", "wash"]
QUEUE_RECIPE_PRIORITY: tuple[RecipeName, ...] = ("soup", "fries", "salad")
TICKET_RECIPE_BY_NAME: dict[str, RecipeName] = {recipe: recipe for recipe in QUEUE_RECIPE_PRIORITY}
KITCHEN_SEARCH_ANCHOR = (10, 11)
KITCHEN_SEARCH_CENTER = (11, 11)


@dataclass
class OvercookedAgentState:
    agent_id: int
    role: RoleName
    step: int = 0
    position: tuple[int, int] = (0, 0)
    inventory: dict[str, int] = field(default_factory=dict)
    entity_map: EntityMap = field(default_factory=EntityMap)
    navigator: Navigator = field(default_factory=Navigator)
    recipe_preference: RecipeName = "salad"
    board_last_seen_step: int = 0
    last_pos: tuple[int, int] | None = None
    last_action: str = "noop"
    failed_moves: int = 0
    fries_bootstrap_done: bool = False
    active_station_task: StationTask | None = None
    current_task: str = ""


class OvercookedBrain(StatefulPolicyImpl[OvercookedAgentState]):
    def __init__(self, pei: PolicyEnvInterface, agent_id: int) -> None:
        self._agent_id = agent_id
        self._num_agents = pei.num_agents
        self._role = _assign_role(agent_id, pei.num_agents)
        self._talk_enabled = pei.talk.enabled
        self._obs_parser = ObsParser(pei)

    def initial_agent_state(self) -> OvercookedAgentState:
        return OvercookedAgentState(
            agent_id=self._agent_id,
            role=self._role,
            navigator=Navigator(preferred_direction=_preferred_direction(self._agent_id)),
        )

    def step_with_state(
        self,
        obs: AgentObservation,
        state: OvercookedAgentState,
    ) -> tuple[Action, OvercookedAgentState]:
        state.step += 1
        state.current_task = ""

        parsed, visible = self._obs_parser.parse(obs, fallback_position=state.position)
        state.position = parsed.position
        state.inventory = parsed.inventory
        state.entity_map.update_from_observation(
            state.position,
            self._obs_parser.obs_half_h,
            self._obs_parser.obs_half_w,
            visible,
            state.step,
        )

        if state.last_pos is not None and state.last_action.startswith("move_") and state.position == state.last_pos:
            state.failed_moves += 1
        else:
            state.failed_moves = 0

        if state.failed_moves >= 4:
            if _holding_servable_dish(state.inventory):
                action = self._route_to_station(state, "serving_station")
            else:
                state.current_task = "unstick"
                action = state.navigator.explore(state.position, state.entity_map, bias="south")
        else:
            action = self._choose_action(state)

        if not state.current_task:
            state.current_task = _action_task_label(action.name)

        self._infos = {
            "current_task": state.current_task,
            "current_action": action.name,
            "focus_recipe": state.recipe_preference,
            "role": state.role,
        }
        if state.active_station_task is not None:
            self._infos["station_task"] = state.active_station_task

        state.last_pos = state.position
        state.last_action = action.name
        return Action(
            name=action.name,
            vibe=action.vibe,
            talk=state.current_task if self._talk_enabled else None,
        ), state

    def _choose_action(self, state: OvercookedAgentState) -> Action:
        board_visible = self._has_visible_object(state, "order_board")
        board_inventory = self._latest_object_inventory(state, "order_board")
        chop_inventory = self._latest_object_inventory(state, "chopping_station")
        cook_inventory = self._latest_object_inventory(state, "cooking_station")
        fryer_inventory = self._latest_object_inventory(state, "fryer_station")
        wash_inventory = self._latest_object_inventory(state, "wash_station")
        active_recipe = state.recipe_preference

        if board_visible:
            active_recipe = _active_recipe(board_inventory, state.recipe_preference)
            state.recipe_preference = active_recipe
            state.board_last_seen_step = state.step
        if self._num_agents == 1 and board_inventory.get(QUEUE_SALAD, 0) > 0:
            active_recipe = "salad"
            state.recipe_preference = active_recipe
        hot_station_urgent = (
            cook_inventory.get(POT_SOUP_READY, 0) > 0
            or cook_inventory.get(POT_SOUP_BURNED, 0) > 0
            or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0
            or fryer_inventory.get(FRYER_FRIES_BURNED, 0) > 0
        )

        if state.active_station_task == "wash":
            if wash_inventory.get(WASH_PROGRESS, 0) > 0 or state.inventory.get(DIRTY_PLATE, 0) > 0:
                return self._route_to_station(state, "wash_station")
            state.active_station_task = None
        elif state.active_station_task == "chop_veg":
            if hot_station_urgent and state.inventory.get(CHOPPED_VEG, 0) == 0:
                state.active_station_task = None
            elif state.inventory.get(CHOPPED_VEG, 0) > 0:
                state.active_station_task = None
            elif chop_inventory.get(CHOP_VEG_PROGRESS, 0) > 0 or state.inventory.get(VEG, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            else:
                state.active_station_task = None
        elif state.active_station_task == "chop_meat":
            if hot_station_urgent and state.inventory.get(CHOPPED_MEAT, 0) == 0:
                state.active_station_task = None
            elif state.inventory.get(CHOPPED_MEAT, 0) > 0:
                state.active_station_task = None
            elif chop_inventory.get(CHOP_MEAT_PROGRESS, 0) > 0 or state.inventory.get(MEAT, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            else:
                state.active_station_task = None

        board_refresh_interval = _board_refresh_interval(state.role, self._num_agents)
        needs_initial_board_refresh = board_refresh_interval is not None and state.board_last_seen_step == 0
        board_refresh_due = (
            board_refresh_interval is not None and state.step - state.board_last_seen_step > board_refresh_interval
        )
        if (
            (needs_initial_board_refresh or board_refresh_due)
            and not _holding_any_item(state.inventory)
            and not hot_station_urgent
        ):
            return self._route_to_station(state, "order_board")

        inv = state.inventory
        if inv.get(DIRTY_PLATE, 0) > 0:
            return self._commit_station_task(state, "wash", "wash_station")
        if _holding_servable_dish(inv):
            held_recipe = _held_dish_recipe(inv)
            if held_recipe is None:
                return self._route_to_station(state, "serving_station")
            if not _recipe_has_active_ticket(board_inventory, held_recipe):
                return self._route_to_station(state, "order_board")
            return self._route_to_station(state, "serving_station")

        role_action: Action | None = None
        if state.role == "server":
            role_action = self._server_action(
                state,
                board_inventory,
                chop_inventory,
                cook_inventory,
                fryer_inventory,
                active_recipe,
            )
        elif state.role == "cook":
            role_action = self._cook_action(
                state,
                board_inventory,
                chop_inventory,
                cook_inventory,
                fryer_inventory,
                active_recipe,
            )
        elif state.role == "prep":
            role_action = self._prep_action(state, board_inventory, chop_inventory, cook_inventory, active_recipe)
        elif state.role == "all_rounder":
            role_action = self._all_rounder_action(
                state,
                board_inventory,
                chop_inventory,
                cook_inventory,
                fryer_inventory,
                active_recipe,
            )

        if role_action is not None:
            return role_action

        if (
            self._num_agents >= 3
            and state.role == "prep"
            and (cook_inventory.get(POT_SOUP_READY, 0) > 0 or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0)
        ):
            return self._route_to_station(state, "order_board")

        return self._recipe_action(state, active_recipe, chop_inventory, cook_inventory, fryer_inventory)

    def _server_action(
        self,
        state: OvercookedAgentState,
        board_inventory: dict[str, int],
        chop_inventory: dict[str, int],
        cook_inventory: dict[str, int],
        fryer_inventory: dict[str, int],
        active_recipe: RecipeName,
    ) -> Action | None:
        inv = state.inventory
        queue_fries = board_inventory.get(QUEUE_FRIES, 0)
        queue_soup = board_inventory.get(QUEUE_SOUP, 0)
        visible_ticket_recipe = _visible_ticket_recipe(board_inventory)

        if _holding_servable_dish(inv):
            return self._route_to_station(state, "serving_station")
        if inv.get(CHOPPED_MEAT, 0) > 0:
            if cook_inventory.get(POT_SOUP_READY, 0) > 0 or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0:
                return self._route_to_empty_counter(state)
            return self._route_to_station(state, "cooking_station")
        if inv.get(CHOPPED_VEG, 0) > 0:
            if cook_inventory.get(POT_SOUP_READY, 0) > 0 or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0:
                return self._route_to_empty_counter(state)
            if visible_ticket_recipe == "salad" or _should_prioritize_salad(active_recipe, board_inventory):
                return self._route_to_station(state, "chopping_station")
            if queue_fries >= queue_soup:
                return self._route_to_station(state, "fryer_station")
            return self._route_to_station(state, "cooking_station")
        if inv.get(VEG, 0) > 0 or inv.get(MEAT, 0) > 0:
            if cook_inventory.get(POT_SOUP_READY, 0) > 0 or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0:
                return self._route_to_empty_counter(state)
            return self._route_to_chopping_station(state, active_recipe)

        if fryer_inventory.get(FRYER_FRIES_READY, 0) > 0 and queue_fries > 0:
            if inv.get(CLEAN_PLATE, 0) == 0:
                return self._route_to_source(state, "plate_station", CLEAN_PLATE)
            return self._route_to_station(state, "fryer_station")
        if cook_inventory.get(POT_SOUP_READY, 0) > 0:
            if inv.get(CLEAN_PLATE, 0) == 0:
                return self._route_to_source(state, "plate_station", CLEAN_PLATE)
            return self._route_to_station(state, "cooking_station")
        if visible_ticket_recipe == "salad" or _should_prioritize_salad(active_recipe, board_inventory):
            return self._salad_action(state, chop_inventory)

        if queue_fries > 0 and (
            fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0 or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0
        ):
            return self._route_to_station(state, "fryer_station")
        if queue_soup > 0 and (
            cook_inventory.get(POT_SOUP_COOKING, 0) > 0
            or cook_inventory.get(POT_SOUP_READY, 0) > 0
            or cook_inventory.get(CHOPPED_VEG, 0) > 0
            or cook_inventory.get(CHOPPED_MEAT, 0) > 0
        ):
            return self._route_to_station(state, "cooking_station")

        if _pending_orders(board_inventory) > 0:
            return self._route_to_station(state, "order_board")
        return None

    def _cook_action(
        self,
        state: OvercookedAgentState,
        board_inventory: dict[str, int],
        chop_inventory: dict[str, int],
        cook_inventory: dict[str, int],
        fryer_inventory: dict[str, int],
        active_recipe: RecipeName,
    ) -> Action | None:
        inv = state.inventory
        queue_soup = board_inventory.get(QUEUE_SOUP, 0)
        queue_fries = board_inventory.get(QUEUE_FRIES, 0)
        fryer_has_activity = (
            fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0
            or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0
            or fryer_inventory.get(FRYER_FRIES_BURNED, 0) > 0
        )

        # Ensure we exercise fryer flow at least once on high-pressure layouts.
        # This avoids getting stuck in a soup-only local optimum when fries are queued.
        if not state.fries_bootstrap_done:
            if fryer_has_activity:
                state.fries_bootstrap_done = True
            elif queue_fries > 0 and state.step <= 120:
                return self._recipe_action(state, "fries", chop_inventory, cook_inventory, fryer_inventory)
            elif queue_fries > 0:
                state.fries_bootstrap_done = True

        # Ready dishes are the highest-priority service path.
        # Fetch a plate immediately so ready timers do not convert into burns.
        if (
            (cook_inventory.get(POT_SOUP_READY, 0) > 0 and queue_soup > 0)
            or (fryer_inventory.get(FRYER_FRIES_READY, 0) > 0 and queue_fries > 0)
        ) and inv.get(CLEAN_PLATE, 0) == 0:
            return self._route_to_source(state, "plate_station", CLEAN_PLATE)

        if cook_inventory.get(POT_SOUP_BURNED, 0) > 0:
            return self._route_to_station(state, "cooking_station")
        if fryer_inventory.get(FRYER_FRIES_BURNED, 0) > 0:
            return self._route_to_station(state, "fryer_station")

        if fryer_inventory.get(FRYER_FRIES_READY, 0) > 0 and inv.get(CLEAN_PLATE, 0) > 0 and queue_fries > 0:
            return self._route_to_station(state, "fryer_station")
        if cook_inventory.get(POT_SOUP_READY, 0) > 0 and inv.get(CLEAN_PLATE, 0) > 0:
            return self._route_to_station(state, "cooking_station")
        if fryer_inventory.get(FRYER_FRIES_READY, 0) > 0 and inv.get(CLEAN_PLATE, 0) > 0:
            return self._route_to_station(state, "fryer_station")

        if (
            queue_fries > 0
            and fryer_inventory.get(FRYER_FRIES_COOKING, 0) == 0
            and fryer_inventory.get(FRYER_FRIES_READY, 0) == 0
        ):
            return self._recipe_action(state, "fries", chop_inventory, cook_inventory, fryer_inventory)

        if active_recipe == "soup" and (
            queue_soup > 0
            or cook_inventory.get(POT_SOUP_COOKING, 0) > 0
            or cook_inventory.get(POT_SOUP_READY, 0) > 0
            or cook_inventory.get(CHOPPED_VEG, 0) > 0
            or cook_inventory.get(CHOPPED_MEAT, 0) > 0
        ):
            return self._recipe_action(state, "soup", chop_inventory, cook_inventory, fryer_inventory)
        if active_recipe == "fries" and (
            queue_fries > 0
            or fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0
            or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0
        ):
            return self._recipe_action(state, "fries", chop_inventory, cook_inventory, fryer_inventory)

        if queue_fries > queue_soup and (queue_fries > 0 or fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0):
            return self._recipe_action(state, "fries", chop_inventory, cook_inventory, fryer_inventory)
        if (
            queue_soup > 0
            or cook_inventory.get(POT_SOUP_COOKING, 0) > 0
            or cook_inventory.get(POT_SOUP_READY, 0) > 0
            or cook_inventory.get(CHOPPED_VEG, 0) > 0
            or cook_inventory.get(CHOPPED_MEAT, 0) > 0
        ):
            return self._recipe_action(state, "soup", chop_inventory, cook_inventory, fryer_inventory)
        if queue_fries > 0 or fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0:
            return self._recipe_action(state, "fries", chop_inventory, cook_inventory, fryer_inventory)
        return None

    def _prep_action(
        self,
        state: OvercookedAgentState,
        board_inventory: dict[str, int],
        chop_inventory: dict[str, int],
        cook_inventory: dict[str, int],
        active_recipe: RecipeName,
    ) -> Action | None:
        inv = state.inventory

        if inv.get(VEG, 0) > 0 or inv.get(MEAT, 0) > 0:
            return self._route_to_chopping_station(state, active_recipe)
        if inv.get(CHOPPED_MEAT, 0) > 0:
            return self._route_to_station(state, "cooking_station")
        if inv.get(CHOPPED_VEG, 0) > 0:
            if _should_prioritize_salad(active_recipe, board_inventory):
                return self._route_to_station(state, "chopping_station")
            if board_inventory.get(QUEUE_FRIES, 0) > board_inventory.get(QUEUE_SOUP, 0):
                return self._route_to_station(state, "fryer_station")
            return self._route_to_station(state, "cooking_station")
        if inv.get(CLEAN_PLATE, 0) > 0:
            return self._route_to_empty_counter(state)

        queue_salad = board_inventory.get(QUEUE_SALAD, 0)
        queue_soup = board_inventory.get(QUEUE_SOUP, 0)
        queue_fries = board_inventory.get(QUEUE_FRIES, 0)
        soup_active = (
            cook_inventory.get(POT_SOUP_COOKING, 0) > 0
            or cook_inventory.get(POT_SOUP_READY, 0) > 0
            or cook_inventory.get(CHOPPED_VEG, 0) > 0
            or cook_inventory.get(CHOPPED_MEAT, 0) > 0
        )

        # Keep soup mechanics live under tighter release layouts. When soup is
        # queued but no pot is active, prep should assemble soup ingredients
        # instead of letting salad/fries permanently dominate the station loop.
        if queue_soup > 0 and not soup_active:
            if chop_inventory.get(CHOPPED_VEG, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            if queue_soup > queue_salad:
                return self._route_to_source(state, "veg_station", VEG)
        if cook_inventory.get(CHOPPED_VEG, 0) > 0 and cook_inventory.get(CHOPPED_MEAT, 0) == 0:
            if chop_inventory.get(CHOPPED_MEAT, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            return self._route_to_source(state, "meat_station", MEAT)
        if cook_inventory.get(CHOPPED_MEAT, 0) > 0 and cook_inventory.get(CHOPPED_VEG, 0) == 0:
            if chop_inventory.get(CHOPPED_VEG, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            return self._route_to_source(state, "veg_station", VEG)

        # Under fries pressure, prep should push chopped veg to the fryer directly
        # so fries are not starved behind soup-only meat preparation.
        if queue_fries > queue_soup:
            if chop_inventory.get(CHOPPED_VEG, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            return self._route_to_source(state, "veg_station", VEG)

        if _should_prioritize_salad(active_recipe, board_inventory):
            return self._salad_action(state, chop_inventory)
        return None

    def _all_rounder_action(
        self,
        state: OvercookedAgentState,
        board_inventory: dict[str, int],
        chop_inventory: dict[str, int],
        cook_inventory: dict[str, int],
        fryer_inventory: dict[str, int],
        active_recipe: RecipeName,
    ) -> Action | None:
        if self._num_agents == 1:
            return None

        if state.inventory.get(DIRTY_PLATE, 0) > 0:
            return self._commit_station_task(state, "wash", "wash_station")

        server_action = self._server_action(
            state,
            board_inventory,
            chop_inventory,
            cook_inventory,
            fryer_inventory,
            active_recipe,
        )
        if server_action is not None:
            return server_action

        prep_action = self._prep_action(state, board_inventory, chop_inventory, cook_inventory, active_recipe)
        if prep_action is not None and _should_prioritize_salad(active_recipe, board_inventory):
            return prep_action

        cook_action = self._cook_action(
            state,
            board_inventory,
            chop_inventory,
            cook_inventory,
            fryer_inventory,
            active_recipe,
        )
        if cook_action is not None and (
            board_inventory.get(QUEUE_SOUP, 0) > 0
            or board_inventory.get(QUEUE_FRIES, 0) > 0
            or cook_inventory.get(POT_SOUP_COOKING, 0) > 0
            or fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0
        ):
            return cook_action

        if prep_action is not None:
            return prep_action
        return cook_action

    def _recipe_action(
        self,
        state: OvercookedAgentState,
        recipe: RecipeName,
        chop_inventory: dict[str, int],
        cook_inventory: dict[str, int],
        fryer_inventory: dict[str, int],
    ) -> Action:
        inv = state.inventory

        if recipe == "soup":
            if cook_inventory.get(POT_SOUP_BURNED, 0) > 0:
                return self._route_to_station(state, "cooking_station")

            if cook_inventory.get(POT_SOUP_READY, 0) > 0:
                if inv.get(CLEAN_PLATE, 0) > 0:
                    return self._route_to_station(state, "cooking_station")
                if _holding_any_item(inv):
                    return self._route_to_empty_counter(state)
                return self._route_to_source(state, "plate_station", CLEAN_PLATE)
            if self._num_agents == 1 and cook_inventory.get(POT_SOUP_COOKING, 0) > 0:
                if inv.get(CLEAN_PLATE, 0) > 0:
                    return self._route_to_station(state, "cooking_station")
                if _holding_any_item(inv):
                    return self._route_to_empty_counter(state)
                return self._route_to_source(state, "plate_station", CLEAN_PLATE)

            if inv.get(CHOPPED_VEG, 0) > 0 or inv.get(CHOPPED_MEAT, 0) > 0:
                return self._route_to_station(state, "cooking_station")
            if cook_inventory.get(CHOPPED_VEG, 0) > 0 and cook_inventory.get(CHOPPED_MEAT, 0) > 0:
                return self._route_to_station(state, "cooking_station")
            if inv.get(VEG, 0) > 0 or inv.get(MEAT, 0) > 0:
                return self._route_to_chopping_station(state, "soup")
            if inv.get(CLEAN_PLATE, 0) > 0:
                if (
                    cook_inventory.get(POT_SOUP_COOKING, 0) > 0
                    or cook_inventory.get(POT_SOUP_READY, 0) > 0
                    or cook_inventory.get(CHOPPED_VEG, 0) > 0
                    or cook_inventory.get(CHOPPED_MEAT, 0) > 0
                ):
                    return self._route_to_station(state, "cooking_station")
                return self._route_to_empty_counter(state)
            if cook_inventory.get(CHOPPED_VEG, 0) > 0:
                if chop_inventory.get(CHOPPED_MEAT, 0) > 0:
                    return self._route_to_station(state, "chopping_station")
                return self._route_to_source(state, "meat_station", MEAT)
            if cook_inventory.get(CHOPPED_MEAT, 0) > 0:
                if chop_inventory.get(CHOPPED_VEG, 0) > 0:
                    return self._route_to_station(state, "chopping_station")
                return self._route_to_source(state, "veg_station", VEG)
            if chop_inventory.get(CHOPPED_VEG, 0) > 0 or chop_inventory.get(CHOPPED_MEAT, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            return self._route_to_source(state, "veg_station", VEG)

        if recipe == "fries":
            if fryer_inventory.get(FRYER_FRIES_BURNED, 0) > 0:
                return self._route_to_station(state, "fryer_station")

            if fryer_inventory.get(FRYER_FRIES_READY, 0) > 0:
                if inv.get(CLEAN_PLATE, 0) > 0:
                    return self._route_to_station(state, "fryer_station")
                if _holding_any_item(inv):
                    return self._route_to_empty_counter(state)
                return self._route_to_source(state, "plate_station", CLEAN_PLATE)
            if self._num_agents == 1 and fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0:
                if inv.get(CLEAN_PLATE, 0) > 0:
                    return self._route_to_station(state, "fryer_station")
                if _holding_any_item(inv):
                    return self._route_to_empty_counter(state)
                return self._route_to_source(state, "plate_station", CLEAN_PLATE)

            if inv.get(CHOPPED_VEG, 0) > 0:
                return self._route_to_station(state, "fryer_station")
            if inv.get(VEG, 0) > 0:
                return self._route_to_chopping_station(state, "fries")
            if inv.get(CLEAN_PLATE, 0) > 0:
                if fryer_inventory.get(FRYER_FRIES_COOKING, 0) > 0 or fryer_inventory.get(FRYER_FRIES_READY, 0) > 0:
                    return self._route_to_station(state, "fryer_station")
                return self._route_to_empty_counter(state)
            if chop_inventory.get(CHOPPED_VEG, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            return self._route_to_source(state, "veg_station", VEG)

        return self._salad_action(state, chop_inventory)

    def _salad_action(self, state: OvercookedAgentState, chop_inventory: dict[str, int]) -> Action:
        inv = state.inventory

        if inv.get(CLEAN_PLATE, 0) > 0:
            if chop_inventory.get(CHOPPED_VEG, 0) > 0:
                return self._route_to_station(state, "chopping_station")
            return self._route_to_empty_counter(state)
        if inv.get(CHOPPED_VEG, 0) > 0:
            return self._route_to_station(state, "chopping_station")
        if inv.get(VEG, 0) > 0 or inv.get(MEAT, 0) > 0:
            return self._route_to_chopping_station(state, "salad")
        if _holding_any_item(inv):
            return self._route_to_empty_counter(state)
        if chop_inventory.get(CHOPPED_VEG, 0) > 0:
            return self._route_to_source(state, "plate_station", CLEAN_PLATE)
        return self._route_to_source(state, "veg_station", VEG)

    def _latest_object_inventory(self, state: OvercookedAgentState, object_type: str) -> dict[str, int]:
        entities = state.entity_map.find(object_type)
        if not entities:
            return {}
        entities.sort(key=lambda pair: pair[1].last_seen, reverse=True)
        return entities[0][1].properties

    def _has_visible_object(self, state: OvercookedAgentState, object_type: str) -> bool:
        return any(entity.last_seen == state.step for _, entity in state.entity_map.find(object_type))

    def _nearest_counter(
        self,
        state: OvercookedAgentState,
        predicate: Callable[[dict[str, int]], bool],
    ) -> tuple[tuple[int, int], Entity] | None:
        best: tuple[tuple[int, int], Entity] | None = None
        best_d = float("inf")
        for pos, entity in state.entity_map.find("wall"):
            if not predicate(entity.properties):
                continue
            dist = manhattan(state.position, pos)
            if dist < best_d:
                best = (pos, entity)
                best_d = dist
        return best

    def _route_to_position(self, state: OvercookedAgentState, target_pos: tuple[int, int], *, label: str) -> Action:
        state.current_task = label
        if manhattan(state.position, target_pos) == 1:
            return move_toward(state.position, target_pos)
        return state.navigator.get_action(
            state.position,
            target_pos,
            state.entity_map,
            reach_adjacent=True,
        )

    def _route_to_empty_counter(self, state: OvercookedAgentState) -> Action:
        counter = self._nearest_counter(state, lambda inventory: not _holding_any_item(inventory))
        if counter is None:
            state.current_task = "find counter"
            return state.navigator.explore(state.position, state.entity_map, bias="west")
        held = _held_item_resource(state.inventory)
        label = "stash item" if held is None else f"stash {held.replace('_', ' ')}"
        return self._route_to_position(state, counter[0], label=label)

    def _route_to_source(self, state: OvercookedAgentState, station_type: str, resource_name: str) -> Action:
        counter = self._nearest_counter(state, lambda inventory: inventory.get(resource_name, 0) > 0)
        if counter is not None:
            label = f"grab {resource_name.replace('_', ' ')}"
            return self._route_to_position(state, counter[0], label=label)
        return self._route_to_station(state, station_type)

    def _route_to_station(self, state: OvercookedAgentState, station_type: str) -> Action:
        state.current_task = _station_task_label(
            station_type,
            inventory=state.inventory,
            active_station_task=state.active_station_task,
            cook_inventory=self._latest_object_inventory(state, "cooking_station"),
            fryer_inventory=self._latest_object_inventory(state, "fryer_station"),
        )
        nearest = state.entity_map.find_nearest(state.position, station_type)
        if nearest is None:
            return self._explore_for_station(state, station_type)

        target_pos = nearest[0]
        if manhattan(state.position, target_pos) == 1:
            return move_toward(state.position, target_pos)

        return state.navigator.get_action(
            state.position,
            target_pos,
            state.entity_map,
            reach_adjacent=True,
        )

    def _explore_for_station(self, state: OvercookedAgentState, station_type: str) -> Action:
        state.current_task = f"find {_station_display_name(station_type)}"
        if (
            self._num_agents >= 3
            and manhattan(state.position, KITCHEN_SEARCH_CENTER) >= 5
            and manhattan(state.position, KITCHEN_SEARCH_ANCHOR) > 2
        ):
            return state.navigator.get_action(state.position, KITCHEN_SEARCH_ANCHOR, state.entity_map)
        return state.navigator.explore(state.position, state.entity_map, bias="north")

    def _commit_station_task(self, state: OvercookedAgentState, task: StationTask, station_type: str) -> Action:
        state.active_station_task = task
        return self._route_to_station(state, station_type)

    def _route_to_chopping_station(self, state: OvercookedAgentState, recipe: RecipeName) -> Action:
        inv = state.inventory
        if recipe == "soup" and inv.get(MEAT, 0) > 0 and inv.get(CHOPPED_MEAT, 0) == 0:
            return self._commit_station_task(state, "chop_meat", "chopping_station")
        if inv.get(VEG, 0) > 0:
            return self._commit_station_task(state, "chop_veg", "chopping_station")
        if inv.get(MEAT, 0) > 0:
            return self._commit_station_task(state, "chop_meat", "chopping_station")
        return self._route_to_station(state, "chopping_station")


class OvercookedPolicy(MultiAgentPolicy):
    """Scripted policy URI: metta://policy/overcogged_agent."""

    short_names = ["overcogged_agent"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", **kwargs: object) -> None:
        super().__init__(policy_env_info, device=device)
        self._agents: dict[int, StatefulAgentPolicy[OvercookedAgentState]] = {}

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[OvercookedAgentState]:
        if agent_id not in self._agents:
            brain = OvercookedBrain(self._policy_env_info, agent_id)
            self._agents[agent_id] = StatefulAgentPolicy(brain, self._policy_env_info, agent_id=agent_id)
        return self._agents[agent_id]


def _active_recipe(board_inventory: dict[str, int], fallback: RecipeName) -> RecipeName:
    visible_ticket_recipe = _visible_ticket_recipe(board_inventory)
    if visible_ticket_recipe is not None:
        return visible_ticket_recipe

    queue_values = [
        (recipe, board_inventory.get(QUEUE_RESOURCE_BY_RECIPE[recipe], 0)) for recipe in QUEUE_RECIPE_PRIORITY
    ]
    queue_values.sort(key=lambda item: item[1], reverse=True)
    if queue_values[0][1] > 0:
        return queue_values[0][0]
    return fallback


def _holding_servable_dish(inventory: dict[str, int]) -> bool:
    return any(inventory.get(resource, 0) > 0 for resource in DISH_RESOURCE_BY_RECIPE.values())


def _held_dish_recipe(inventory: dict[str, int]) -> RecipeName | None:
    for recipe, resource in DISH_RESOURCE_BY_RECIPE.items():
        if inventory.get(resource, 0) > 0:
            return recipe
    return None


def _holding_any_item(inventory: dict[str, int]) -> bool:
    return any(inventory.get(resource, 0) > 0 for resource in BASE_AGENT_RESOURCES)


def _held_item_resource(inventory: dict[str, int]) -> str | None:
    for resource in BASE_AGENT_RESOURCES:
        if inventory.get(resource, 0) > 0:
            return resource
    return None


def _visible_ticket_recipe(board_inventory: dict[str, int]) -> RecipeName | None:
    active_tickets: list[tuple[int, RecipeName]] = []
    for resource_name, value in board_inventory.items():
        if value <= 0 or not resource_name.startswith("ticket_"):
            continue

        parts = resource_name.split("_")
        if len(parts) < 3:
            continue

        try:
            idx = int(parts[1])
        except ValueError:
            continue

        recipe = TICKET_RECIPE_BY_NAME.get(parts[2])
        if recipe is not None:
            active_tickets.append((idx, recipe))

    if not active_tickets:
        return None

    active_tickets.sort(key=lambda item: item[0])
    return active_tickets[0][1]


def _should_prioritize_salad(active_recipe: RecipeName, board_inventory: dict[str, int]) -> bool:
    if board_inventory.get(QUEUE_SALAD, 0) <= 0:
        return False
    if active_recipe == "salad":
        return True
    return board_inventory.get(QUEUE_SOUP, 0) <= 0 and board_inventory.get(QUEUE_FRIES, 0) <= 0


def _pending_orders(board_inventory: dict[str, int]) -> int:
    return sum(board_inventory.get(QUEUE_RESOURCE_BY_RECIPE[recipe], 0) for recipe in QUEUE_RECIPE_PRIORITY)


def _recipe_has_active_ticket(board_inventory: dict[str, int], recipe: RecipeName) -> bool:
    return board_inventory.get(QUEUE_RESOURCE_BY_RECIPE[recipe], 0) > 0


def _station_task_label(
    station_type: str,
    *,
    inventory: dict[str, int],
    active_station_task: StationTask | None,
    cook_inventory: dict[str, int],
    fryer_inventory: dict[str, int],
) -> str:
    if station_type == "order_board":
        return "check orders"
    if station_type == "serving_station":
        return "serve order"
    if station_type == "plate_station":
        return "grab plate"
    if station_type == "wash_station":
        return "wash plate"
    if station_type == "veg_station":
        return "fetch veg"
    if station_type == "meat_station":
        return "fetch meat"
    if station_type == "chopping_station":
        if active_station_task == "chop_meat":
            return "chop meat"
        if active_station_task == "chop_veg":
            return "chop veg"
        if inventory.get(MEAT, 0) > 0 and inventory.get(CHOPPED_MEAT, 0) == 0 and inventory.get(VEG, 0) == 0:
            return "chop meat"
        if inventory.get(VEG, 0) > 0 and inventory.get(CHOPPED_VEG, 0) == 0:
            return "chop veg"
        if inventory.get(CHOPPED_VEG, 0) > 0:
            return "stage veg"
        if inventory.get(CLEAN_PLATE, 0) > 0:
            return "plate salad"
        return "prep ingredients"
    if station_type == "cooking_station":
        if cook_inventory.get(POT_SOUP_BURNED, 0) > 0:
            return "clear burned soup"
        if cook_inventory.get(POT_SOUP_READY, 0) > 0 and inventory.get(CLEAN_PLATE, 0) > 0:
            return "plate soup"
        if inventory.get(CHOPPED_VEG, 0) > 0 or inventory.get(CHOPPED_MEAT, 0) > 0:
            return "load soup"
        if cook_inventory.get(CHOPPED_VEG, 0) > 0 or cook_inventory.get(CHOPPED_MEAT, 0) > 0:
            return "start soup"
        return "check soup"
    if station_type == "fryer_station":
        if fryer_inventory.get(FRYER_FRIES_BURNED, 0) > 0:
            return "clear burned fries"
        if fryer_inventory.get(FRYER_FRIES_READY, 0) > 0 and inventory.get(CLEAN_PLATE, 0) > 0:
            return "plate fries"
        if inventory.get(CHOPPED_VEG, 0) > 0:
            return "start fries"
        return "check fries"
    return _station_display_name(station_type)


def _station_display_name(station_type: str) -> str:
    if station_type == "order_board":
        return "order board"
    if station_type.endswith("_station"):
        return station_type.removesuffix("_station").replace("_", " ")
    return station_type.replace("_", " ")


def _action_task_label(action_name: str) -> str:
    if action_name == "noop":
        return "wait"
    return action_name.replace("_", " ")


def _assign_role(agent_id: int, num_agents: int) -> RoleName:
    if num_agents <= 1:
        return "all_rounder"
    if num_agents == 2:
        return "cook" if agent_id == 0 else "server"
    if num_agents == 3:
        roles: tuple[RoleName, ...] = ("prep", "cook", "server")
        return roles[agent_id]
    if agent_id == 0:
        return "prep"
    if agent_id == 1:
        return "cook"
    if agent_id == 2:
        return "server"
    return "all_rounder"


def _board_refresh_interval(role: RoleName, num_agents: int) -> int | None:
    if num_agents == 1:
        return 18
    if role == "server":
        return 24
    return None


def _preferred_direction(agent_id: int) -> str:
    preferred_directions = ("east", "west", "north", "north")
    return preferred_directions[agent_id % len(preferred_directions)]
