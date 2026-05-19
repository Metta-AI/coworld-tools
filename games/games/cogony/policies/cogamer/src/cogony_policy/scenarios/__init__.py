"""Scenario registry, dataclass, and `@scenario` decorator.

Scenarios are factories: zero-arg callables returning a `Scenario`.
The `@scenario` decorator calls the factory eagerly, registers the
resulting `Scenario` keyed by its `name`, and returns the factory
unchanged so test code can still call it.

`registry()` returns a dict sorted by `(tier, name)` for stable
listing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# Forward declarations — imported lazily to avoid cycles during scenario
# module import. Actual types live in _run.py / assertions.py.
Run = Any
AssertResult = Any
Env = Any

ScenarioFactory = Callable[[], "Scenario"]


@dataclass
class Scenario:
    name: str
    tier: int
    mission: str
    variants: tuple[str, ...] = ()
    cogs: int = 1
    steps: int = 500
    seed: int = 42
    policy_kwargs: dict[str, Any] = field(default_factory=dict)
    mission_overrides: dict[str, Any] = field(default_factory=dict)
    variant_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    tps: float = 0.0
    setup: Callable[[Any], None] | None = None
    assertions: list[Callable[[Any], Any]] = field(default_factory=list)


_REGISTRY: dict[str, Scenario] = {}


def scenario(factory: ScenarioFactory) -> ScenarioFactory:
    """Decorator: invoke the factory and register the resulting Scenario."""
    s = factory()
    if not isinstance(s, Scenario):
        raise TypeError(
            f"@scenario factory {factory.__name__!r} must return a Scenario, got {type(s).__name__}"
        )
    if s.name in _REGISTRY:
        raise ValueError(f"scenario {s.name!r} already registered")
    _REGISTRY[s.name] = s
    return factory


def registry() -> dict[str, Scenario]:
    """Return registered scenarios sorted by (tier, name)."""
    return dict(sorted(_REGISTRY.items(), key=lambda kv: (kv[1].tier, kv[0])))


__all__ = ["Scenario", "scenario", "registry"]
