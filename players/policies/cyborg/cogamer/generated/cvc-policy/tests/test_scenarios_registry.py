"""Scenario registry + @scenario decorator."""

from __future__ import annotations

import pytest

from cvc_policy.scenarios import Scenario, registry, scenario


@pytest.fixture(autouse=True)
def _clear_registry():
    from cvc_policy.scenarios import _REGISTRY

    before = dict(_REGISTRY)
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()
    _REGISTRY.update(before)


def test_scenario_dataclass_defaults() -> None:
    s = Scenario(name="x", tier=1, mission="machina_1")
    assert s.cogs == 1
    assert s.steps == 500
    assert s.seed == 42
    assert s.variants == ()
    assert s.policy_kwargs == {}
    assert s.mission_overrides == {}
    assert s.variant_overrides == {}
    assert s.setup is None
    assert s.assertions == []


def test_decorator_registers_by_name() -> None:
    @scenario
    def sample() -> Scenario:
        return Scenario(name="sample", tier=0, mission="machina_1")

    assert "sample" in registry()
    assert registry()["sample"].tier == 0


def test_decorator_name_must_match_function_or_explicit_name() -> None:
    @scenario
    def foo() -> Scenario:
        return Scenario(name="foo", tier=1, mission="machina_1")

    assert "foo" in registry()


def test_registry_sorted_by_tier_then_name() -> None:
    @scenario
    def bravo() -> Scenario:
        return Scenario(name="bravo", tier=1, mission="machina_1")

    @scenario
    def alpha() -> Scenario:
        return Scenario(name="alpha", tier=1, mission="machina_1")

    @scenario
    def smoke() -> Scenario:
        return Scenario(name="smoke", tier=0, mission="machina_1")

    names = list(registry().keys())
    # tier 0 first, then tier 1 alphabetized
    assert names == ["smoke", "alpha", "bravo"]


def test_duplicate_registration_raises() -> None:
    @scenario
    def dup() -> Scenario:
        return Scenario(name="dup", tier=1, mission="machina_1")

    with pytest.raises(ValueError, match="already registered"):

        @scenario
        def dup2() -> Scenario:  # noqa: F811
            return Scenario(name="dup", tier=1, mission="machina_1")
