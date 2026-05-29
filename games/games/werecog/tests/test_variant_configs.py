from __future__ import annotations

from werecog.defaults import DEFAULT_DAY_STEPS, DEFAULT_NIGHT_STEPS
from werecog import WerecogMission
from werecog.variants.full import FullVariant
from werecog.variants.meetings import MeetingsVariant
from werecog.variants.render import RenderVariant
from werecog.variants.role_action_rewards import RoleActionRewardsVariant
from werecog.variants.roles import RolesVariant
from werecog.variants.survival_rewards import SurvivalRewardsVariant
from werecog.variants.timing import LONG_NIGHT_STEPS, SHORT_DAY_STEPS, SHORT_NIGHT_STEPS
from werecog.variants.voting import VotingVariant
from werecog.variants.win_conditions import WinConditionsVariant
from mettagrid.config.handler_config import AllOf, FirstMatch, Handler


def _make_env(variants: list, *, num_agents: int = 8, max_steps: int = 120):
    mission = WerecogMission.create(num_agents=num_agents, max_steps=max_steps).with_variants(variants)
    return mission.make_env()


def _handler_names(handler) -> set[str]:
    if handler is None:
        return set()
    if isinstance(handler, Handler):
        return {handler.name} if handler.name else set()
    if isinstance(handler, (FirstMatch, AllOf)):
        names = set()
        for nested in handler.handlers:
            names |= _handler_names(nested)
        return names
    return set()


def test_roles_variant_adds_private_role_observations() -> None:
    env = _make_env([RolesVariant()])

    assert "alive" in env.game.resource_names
    assert "villager" in env.game.resource_names
    assert "werewolf" in env.game.resource_names
    assert "role_werewolf" in env.game.obs.global_obs.obs
    assert "role_villager" in env.game.obs.global_obs.obs


def test_meetings_variant_isolated_tree_does_not_pull_full_game_surface() -> None:
    env = _make_env([MeetingsVariant()])

    assert {"vote_token", "day_phase", "night_phase", "day_vote_open", "night_hunt_open"}.issubset(set(env.game.resource_names))
    assert "meeting_bell" in env.game.objects
    assert "accusation" not in env.game.resource_names
    assert env.game.render.assets["agent"] == []


def test_voting_variant_adds_accusation_resource_and_handlers() -> None:
    env = _make_env([VotingVariant()])

    assert "accusation" in env.game.resource_names
    for agent in env.game.agents:
        assert {"execute_werewolf", "execute_villager", "accuse_player"}.issubset(_handler_names(agent.on_use_handler))


def test_win_conditions_variant_adds_resolution_events() -> None:
    env = _make_env([WinConditionsVariant()])

    assert {"villagers_win_check", "werewolves_win_check"}.issubset(set(env.game.events))


def test_reward_variants_add_only_reward_shaping() -> None:
    env = _make_env([SurvivalRewardsVariant(), RoleActionRewardsVariant()])

    assert any("survival" in agent.rewards for agent in env.game.agents)
    assert any(("hunt" in agent.rewards) or ("vote" in agent.rewards) for agent in env.game.agents)


def test_render_variant_adds_public_avatar_and_huds() -> None:
    env = _make_env([RenderVariant()])

    assert env.game.render.assets["agent"]
    assert {"alive", "vote_token", "suspicion", "day_phase", "night_phase", "day_vote_open", "night_hunt_open"}.issubset(env.game.render.agent_huds)


def test_full_variant_matches_default_env_surface() -> None:
    default_env = WerecogMission.create(num_agents=8, max_steps=120).make_env()
    explicit_env = _make_env([FullVariant()])

    assert default_env.game.resource_names == explicit_env.game.resource_names
    assert set(default_env.game.objects) == set(explicit_env.game.objects)
    assert default_env.game.render.assets == explicit_env.game.render.assets


def test_short_night_variant_reschedules_phase_events() -> None:
    mission = WerecogMission.create(num_agents=8, max_steps=120).with_variants(["short_night"])
    env = mission.make_env()

    assert mission.default_variant is None
    expected_period = SHORT_NIGHT_STEPS + DEFAULT_DAY_STEPS
    assert env.game.events["night_phase_start"].timesteps == list(range(0, mission.max_steps + 1, expected_period))
    assert env.game.events["night_hunt_open"].timesteps[0] == max(1, min(SHORT_NIGHT_STEPS - 1, SHORT_NIGHT_STEPS // 2))
    assert env.game.events["day_phase_start"].timesteps[0] == SHORT_NIGHT_STEPS
    assert env.game.events["day_vote_open"].timesteps[0] == SHORT_NIGHT_STEPS + max(1, min(DEFAULT_DAY_STEPS - 1, DEFAULT_DAY_STEPS // 3))


def test_long_night_variant_reschedules_phase_events() -> None:
    mission = WerecogMission.create(num_agents=8, max_steps=120).with_variants(["long_night"])
    env = mission.make_env()

    assert mission.default_variant is None
    assert env.game.events["night_hunt_open"].timesteps[0] == max(1, min(LONG_NIGHT_STEPS - 1, LONG_NIGHT_STEPS // 2))
    assert env.game.events["day_phase_start"].timesteps[0] == LONG_NIGHT_STEPS


def test_short_day_variant_reschedules_phase_period() -> None:
    mission = WerecogMission.create(num_agents=8, max_steps=120).with_variants(["short_day"])
    env = mission.make_env()

    assert mission.default_variant is None
    expected_period = DEFAULT_NIGHT_STEPS + SHORT_DAY_STEPS
    assert env.game.events["night_phase_start"].timesteps == list(range(0, mission.max_steps + 1, expected_period))
    assert env.game.events["day_vote_open"].timesteps[0] == DEFAULT_NIGHT_STEPS + max(1, min(SHORT_DAY_STEPS - 1, SHORT_DAY_STEPS // 3))


def test_meetings_variant_uses_fixed_observation_window() -> None:
    env = _make_env([MeetingsVariant()])

    assert "night_phase_werewolf_visibility" not in env.game.events
    assert "night_phase_villager_visibility" not in env.game.events
    assert {"night_phase_start", "day_phase_start"}.issubset(env.game.events)
