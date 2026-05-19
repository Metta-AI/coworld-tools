from cogames.game import get_game
from mettagrid.policy.policy import PolicySpec
from mettagrid.runner.rollout import run_episode_local

from diplomacog import make_diplomacog_env


def test_diplomacog_registers_with_cogames() -> None:
    import diplomacog.cogame  # noqa: F401

    game = get_game("diplomacog")

    assert game.name == "diplomacog"
    assert [mission.name for mission in game.missions] == ["basic"]


def test_diplomacog_recipe_exports_play_entrypoint() -> None:
    from diplomacog.recipe import play

    assert callable(play)


def test_diplomacog_recipe_builds_timed_events_for_requested_max_steps() -> None:
    from diplomacog.recipe import _make_play_env

    env, max_steps = _make_play_env(num_agents=None, cogs=6, max_steps=25, variants=["discussion_sessions"])

    assert max_steps == 25
    assert env.game.max_steps == 25
    assert env.game.events["mission_victory_check"].timesteps == [25]
    assert env.label == "diplomacog.basic.discussion_sessions"


def test_make_diplomacog_env_smoke() -> None:
    env = make_diplomacog_env(num_agents=6, max_steps=25, variants=["discussion_sessions"])

    assert env.game.num_agents == 6
    assert env.game.max_steps == 25
    assert env.label.startswith("diplomacog.")


def test_random_policy_rollout_smoke() -> None:
    env = make_diplomacog_env(num_agents=6, max_steps=10, variants=["discussion_sessions"])
    results, _ = run_episode_local(
        policy_specs=[PolicySpec(class_path="mettagrid.policy.random_agent.RandomMultiAgentPolicy")],
        assignments=[0] * env.game.num_agents,
        env=env,
        seed=3,
        render_mode="none",
    )

    assert results.steps == 10
    assert len(results.rewards) == env.game.num_agents


def test_scripted_policy_rollout_smoke() -> None:
    env = make_diplomacog_env(num_agents=6, max_steps=10, variants=["discussion_sessions"])
    results, _ = run_episode_local(
        policy_specs=[PolicySpec(class_path="diplomacog.agent.diplomacy_agent.policy.DiplomacyPolicy")],
        assignments=[0] * env.game.num_agents,
        env=env,
        seed=7,
        render_mode="none",
    )

    assert results.steps == 10
    assert len(results.rewards) == env.game.num_agents
