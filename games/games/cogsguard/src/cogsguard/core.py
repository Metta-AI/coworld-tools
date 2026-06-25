"""Core mission and variant lifecycle for CogsGuard."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from pydantic import Field, PrivateAttr
from typing_extensions import Self

from mettagrid.base_config import Config
from mettagrid.config.mettagrid_config import GridObjectConfig, MettaGridConfig
from mettagrid.map_builder.map_builder import AnyMapBuilderConfig

T = TypeVar("T", bound="CogsguardMissionVariant")


@dataclass
class Deps:
    required: list[type[CogsguardMissionVariant]] = field(default_factory=list)
    optional: list[type[CogsguardMissionVariant]] = field(default_factory=list)


class ResolvedDeps:
    def __init__(
        self,
        registry: VariantRegistry,
        declared_required: set[type[CogsguardMissionVariant]],
        declared_optional: set[type[CogsguardMissionVariant]],
    ) -> None:
        self._registry = registry
        self._declared_required = declared_required
        self._declared_optional = declared_optional

    def required(self, variant_type: type[T]) -> T:
        assert variant_type in self._declared_required, (
            f"required({variant_type.__name__}) not declared in dependencies(). "
            f"Declared required: {[t.__name__ for t in self._declared_required]}"
        )
        return self._registry.required(variant_type)

    def optional(self, variant_type: type[T]) -> T | None:
        assert variant_type in self._declared_optional, (
            f"optional({variant_type.__name__}) not declared in dependencies(). "
            f"Declared optional: {[t.__name__ for t in self._declared_optional]}"
        )
        return self._registry.optional(variant_type)


class VariantRegistry:
    def __init__(self, variants: list[CogsguardMissionVariant] | None = None) -> None:
        self._variants: dict[str, CogsguardMissionVariant] = {}
        self._configure_order: list[str] = []
        self._edges: list[tuple[str, str, str]] = []
        self._resolved_deps: dict[str, Deps] = {}
        if variants:
            for variant in variants:
                self._variants[variant.name] = variant

    def get(self, name: str) -> CogsguardMissionVariant | None:
        return self._variants.get(name)

    def all(self) -> list[CogsguardMissionVariant]:
        return list(self._variants.values())

    def configured(self) -> list[CogsguardMissionVariant]:
        return [self._variants[name] for name in self._configure_order]

    def configured_names(self) -> list[str]:
        return list(self._configure_order)

    def required(self, variant_type: type[T]) -> T:
        for variant in self._variants.values():
            if isinstance(variant, variant_type):
                return variant
        raise AssertionError(
            f"required({variant_type.__name__}) not found in registry. Available: {sorted(self._variants)}"
        )

    def optional(self, variant_type: type[T]) -> T | None:
        for variant in self._variants.values():
            if isinstance(variant, variant_type):
                return variant
        return None

    def has(self, name: str) -> bool:
        return name in self._variants

    def _resolve_dependencies(self) -> None:
        self._edges.clear()
        self._resolved_deps.clear()

        changed = True
        while changed:
            changed = False
            for name in list(self._variants):
                variant = self._variants[name]
                deps = variant.dependencies()
                self._resolved_deps[name] = deps

                for required_type in deps.required:
                    found = any(isinstance(existing, required_type) for existing in self._variants.values())
                    if not found:
                        new_variant = required_type()
                        self._variants[new_variant.name] = new_variant
                        changed = True

        for name, deps in self._resolved_deps.items():
            for required_type in deps.required:
                for variant in self._variants.values():
                    if isinstance(variant, required_type):
                        self._edges.append((name, variant.name, "required"))
                        break
            for optional_type in deps.optional:
                for variant in self._variants.values():
                    if isinstance(variant, optional_type):
                        self._edges.append((name, variant.name, "optional"))
                        break

    def _topological_order(self) -> list[str]:
        dep_names: dict[str, list[str]] = {name: [] for name in self._variants}
        seen_dep_names: dict[str, set[str]] = {name: set() for name in self._variants}
        for from_name, to_name, _kind in self._edges:
            if to_name in seen_dep_names[from_name]:
                continue
            seen_dep_names[from_name].add(to_name)
            dep_names[from_name].append(to_name)

        order: list[str] = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            assert name not in visiting, f"Circular dependency detected involving '{name}'"
            visiting.add(name)
            for dep in dep_names.get(name, ()):
                visit(dep)
            visiting.remove(name)
            visited.add(name)
            order.append(name)

        for name in list(self._variants):
            visit(name)

        return order

    def run_configure(self, variants: list[str], preferred_modules: Sequence[str] | None = None) -> None:
        for name in variants:
            if name not in self._variants:
                self._variants[name] = CogsguardMissionVariant.create(name, preferred_modules=preferred_modules)

        self._resolve_dependencies()
        self._configure_order = self._topological_order()

        for name in self._configure_order:
            variant = self._variants[name]
            deps = self._resolved_deps.get(name, Deps())
            variant.configure(ResolvedDeps(self, set(deps.required), set(deps.optional)))

    def apply_to_env(self, mission: CogsguardMission, env: MettaGridConfig) -> None:
        for name in self._configure_order:
            self._variants[name].modify_env(mission, env)

    def build_dependency_graph(self) -> list[tuple[str, str, str]]:
        self._resolve_dependencies()
        self._configure_order = self._topological_order()
        return list(self._edges)


class CvCStationConfig(Config):
    def station_cfg(self) -> GridObjectConfig:
        raise NotImplementedError("Subclasses must implement this method")


class CogsguardMissionVariant(Config, ABC):
    name: str
    description: str = Field(default="")

    _type_registry: ClassVar[dict[str, type[CogsguardMissionVariant]]] = {}
    _type_candidates: ClassVar[dict[str, list[type[CogsguardMissionVariant]]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        name_val = cls.__dict__.get("name")
        if isinstance(name_val, str) and name_val:
            CogsguardMissionVariant._type_registry[name_val] = cls
            CogsguardMissionVariant._type_candidates.setdefault(name_val, []).append(cls)

    @classmethod
    def create(cls, name: str, preferred_modules: Sequence[str] | None = None) -> CogsguardMissionVariant:
        candidates = cls._type_candidates.get(name)
        assert candidates is not None, f"Unknown variant '{name}'. Available: {sorted(cls._type_registry)}"
        if preferred_modules:
            for prefix in preferred_modules:
                for candidate in reversed(candidates):
                    if candidate.__module__.startswith(prefix):
                        return candidate()
        variant_cls = cls._type_registry.get(name)
        assert variant_cls is not None, f"Unknown variant '{name}'. Available: {sorted(cls._type_registry)}"
        return variant_cls()

    def dependencies(self) -> Deps:
        return Deps()

    def configure(self, deps: ResolvedDeps) -> None:
        pass

    def modify_env(self, mission: CogsguardMission, env: MettaGridConfig) -> None:
        pass

    def compat(self, mission: CogsguardMission) -> bool:
        return True


class CogsguardMission(Config, ABC):
    name: str
    description: str
    map_builder: AnyMapBuilderConfig
    num_cogs: int | None = None
    min_cogs: int = Field(default=1, ge=1)
    max_cogs: int = Field(default=1000, ge=1)
    default_variant: str | None = None
    sub_missions: list[str] = Field(default_factory=list)
    max_steps: int = Field(default=10000)

    _base_variants: dict[str, CogsguardMissionVariant] = PrivateAttr(default_factory=dict)
    _variant_registry: VariantRegistry = PrivateAttr(default_factory=VariantRegistry)

    def required_variant(self, variant_type: type[T]) -> T:
        return self._variant_registry.required(variant_type)

    def optional_variant(self, variant_type: type[T]) -> T | None:
        return self._variant_registry.optional(variant_type)

    def has_variant(self, name: str) -> bool:
        return self._variant_registry.has(name)

    @classmethod
    def variant_module_prefixes(cls) -> tuple[str, ...]:
        return ("cogsguard.",)

    def with_variants(self, variants: Sequence[str | CogsguardMissionVariant]) -> Self:
        copy = self.model_copy(deep=True)
        preferred_modules = copy.variant_module_prefixes()
        for variant in variants:
            if isinstance(variant, CogsguardMissionVariant):
                copy._base_variants[variant.name] = variant.model_copy(deep=True)
            else:
                copy._base_variants[variant] = CogsguardMissionVariant.create(
                    variant,
                    preferred_modules=preferred_modules,
                )
        return copy

    def with_cogs(self, cogs: int) -> Self:
        return self.model_copy(deep=True, update={"num_cogs": cogs})

    @abstractmethod
    def make_base_env(self) -> MettaGridConfig:
        ...

    def make_env(self) -> MettaGridConfig:
        self._variant_registry = VariantRegistry(list(self._base_variants.values()))
        extra_names = [name for name in self._variant_registry._variants if name != self.default_variant]
        default = [self.default_variant] if self.default_variant else []
        self._variant_registry.run_configure([*default, *extra_names], preferred_modules=self.variant_module_prefixes())

        env = self.make_base_env()
        self._variant_registry.apply_to_env(self, env)
        env.label = self.full_name()
        return env

    def full_name(self) -> str:
        return self.name


class CogsguardGame:
    def __init__(
        self,
        name: str,
        missions: Sequence[CogsguardMission],
        variants: Sequence[CogsguardMissionVariant],
        eval_missions: Sequence[CogsguardMission] | None = None,
    ) -> None:
        self.name = name
        self.missions = list(missions)
        self.variant_registry = VariantRegistry(list(variants))
        self.eval_missions = list(eval_missions) if eval_missions else []


_GAMES: dict[str, CogsguardGame] = {}


def register_game(game: CogsguardGame) -> None:
    _GAMES[game.name] = game


def get_game(name: str) -> CogsguardGame:
    if name not in _GAMES:
        raise ValueError(f"Unknown game '{name}'. Available: {', '.join(sorted(_GAMES))}")
    return _GAMES[name]


def find_mission(game: CogsguardGame, mission_name: str, *, include_evals: bool = False) -> CogsguardMission:
    parts = mission_name.split(".", 1)
    base_name = parts[0]
    sub_name = parts[1] if len(parts) > 1 else None

    if base_name == "evals" and sub_name is not None:
        for mission in game.eval_missions:
            if mission.name == sub_name:
                return mission
        available = [mission.name for mission in game.eval_missions]
        raise ValueError(f"Unknown eval mission '{sub_name}'. Available: {', '.join(available)}")

    search = [*game.missions, *game.eval_missions] if include_evals else list(game.missions)
    for mission in search:
        if mission.name == base_name:
            if sub_name is None:
                return mission
            if sub_name not in mission.sub_missions:
                available = ", ".join(mission.sub_missions) if mission.sub_missions else "none"
                raise ValueError(f"Unknown sub-mission '{sub_name}' for '{base_name}'. Available: {available}")
            variant = game.variant_registry.get(sub_name)
            assert variant is not None, f"Sub-mission variant '{sub_name}' not in game registry"
            return mission.with_variants([variant])
    available = [mission.name for mission in search]
    raise ValueError(f"Unknown mission '{base_name}'. Available: {', '.join(available)}")
