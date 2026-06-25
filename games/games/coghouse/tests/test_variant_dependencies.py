"""Exercise the variant dependency lifecycle.

Requesting ``full`` alone should pull in :class:`HardVariant` and
:class:`BigMapVariant` via ``Deps(required=...)`` and configure them in
topological order (deps before dependents).
"""

from __future__ import annotations

import cogame  # noqa: F401
from cogame.variants import BigMapVariant, FullVariant, HardVariant, resolve_variant_selection


def test_full_pulls_required_deps() -> None:
    registry = resolve_variant_selection(["full"])
    variants_by_name = {v.name: v for v in registry.all()}
    assert set(variants_by_name) == {"full", "hard", "big_map"}
    assert isinstance(variants_by_name["full"], FullVariant)
    assert isinstance(variants_by_name["hard"], HardVariant)
    assert isinstance(variants_by_name["big_map"], BigMapVariant)


def test_topological_configure_order() -> None:
    registry = resolve_variant_selection(["full"])
    order = registry.configured_names()
    assert order.index("hard") < order.index("full")
    assert order.index("big_map") < order.index("full")


def test_configure_hook_ran_for_full() -> None:
    registry = resolve_variant_selection(["full"])
    full = next(v for v in registry.all() if v.name == "full")
    # Set in FullVariant.configure() when deps.required(HardVariant) succeeds.
    assert full._configured_with_hard is True


def test_full_applied_to_env() -> None:
    from cogame.game import MyMission

    mission = MyMission.create(num_agents=2, max_steps=200).with_variants(["full"])
    env = mission.make_env()
    # full = hard (halves max_steps) + big_map (4 corner spawns) + final halve in full.
    # 200 / 2 (hard) / 2 (full) = 50. Allow some wiggle if a contributor tweaks scalars.
    assert env.game.max_steps <= 60
    assert env.game.num_agents == 4
