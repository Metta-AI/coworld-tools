from cogames.variants import VariantRegistry
from metta.games.games import make_game
from hungercog.tree_curriculum import (
    HUNGER_MECHANICS,
    HungerTreeTaskGenerator,
)
from hungercog.game import register_with_metta
from metta.rl.curriculum.curriculum import DiscreteRandomConfig
from metta.rl.curriculum.tree_curriculum import build_tree_nodes, make_tree_curriculum

_HUNGER_PREFIXES = ("hungercog.",)

register_with_metta()


def test_hunger_tree_nodes_are_dependency_closed_and_multi_depth() -> None:
    nodes = build_tree_nodes(game="hungercog", mechanics=HUNGER_MECHANICS)
    assert nodes

    depths = {node.depth for node in nodes}
    assert min(depths) == 1
    assert max(depths) >= 3

    seen: set[tuple[str, ...]] = set()
    for node in nodes:
        assert node.variants not in seen
        seen.add(node.variants)

        registry = VariantRegistry()
        registry.run_configure(list(node.mechanics), preferred_modules=_HUNGER_PREFIXES)
        resolved = tuple(registry._configure_order)
        assert node.variants == resolved


def test_hunger_tree_task_generator_scopes_env_to_full_hunger_interface() -> None:
    generator = HungerTreeTaskGenerator.Config(
        num_agents=8,
        max_steps=250,
        max_combination_size=2,
    ).create()

    task_env = generator.get_task(0).config
    full_env = make_game(
        "hungercog",
        num_agents=8,
        max_steps=250,
        variants=HUNGER_MECHANICS,
    )

    assert task_env.game.resource_names == full_env.game.resource_names
    assert task_env.game.id_map().tag_names() == full_env.game.id_map().tag_names()
    assert task_env.game.actions.actions() == full_env.game.actions.actions()

    # Interface order must stay stable across tasks so feature ids remain consistent.
    for task_id in range(1, 8):
        next_env = generator.get_task(task_id).config
        assert next_env.game.resource_names == full_env.game.resource_names
        assert next_env.game.id_map().tag_names() == full_env.game.id_map().tag_names()


def test_hunger_tree_curriculum_defaults_to_discrete_random() -> None:
    curriculum = make_tree_curriculum(
        game="hungercog",
        mechanics=HUNGER_MECHANICS,
        num_agents=8,
        max_steps=250,
        interface_variants=HUNGER_MECHANICS,
        task_generator_config_cls=HungerTreeTaskGenerator.Config,
    )
    assert isinstance(curriculum.algorithm_config, DiscreteRandomConfig)
    assert curriculum.task_generator.generator_cls() is HungerTreeTaskGenerator


def test_hunger_tree_curriculum_keeps_full_interface_with_subset_mechanics() -> None:
    curriculum = make_tree_curriculum(
        game="hungercog",
        mechanics=["digest"],
        num_agents=8,
        max_steps=250,
        max_combination_size=1,
        interface_variants=HUNGER_MECHANICS,
        task_generator_config_cls=HungerTreeTaskGenerator.Config,
    )
    generator = curriculum.task_generator.create()

    task_env = generator.get_task(0).config
    full_env = make_game(
        "hungercog",
        num_agents=8,
        max_steps=250,
        variants=HUNGER_MECHANICS,
    )

    assert task_env.game.resource_names == full_env.game.resource_names
    assert task_env.game.id_map().tag_names() == full_env.game.id_map().tag_names()
    assert task_env.game.actions.actions() == full_env.game.actions.actions()
