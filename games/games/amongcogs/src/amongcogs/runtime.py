"""Local game registry for the standalone AmongCogs package."""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from typing import Any

from cogames.game import CoGame
from mettagrid.config.mettagrid_config import MettaGridConfig

GAMES: dict[str, dict[str, Any]] = {}


def register(
    name: str,
    mission_class: type | None = None,
    *,
    mission_factory: Callable[[int, int], Any] | None = None,
    parse_variants: Callable[[list[str]], list] | None = None,
    cogame: CoGame | None = None,
    policy_uri: str | None = None,
    policy_packages: Sequence[str] | None = None,
) -> None:
    """Register a local game for standalone play and testing."""
    if mission_factory is None:
        assert mission_class is not None, "mission_class or mission_factory is required"
        mission_factory = mission_class.create

    GAMES[name] = {
        "mission_class": mission_class,
        "mission_factory": mission_factory,
        "parse_variants": parse_variants,
        "cogame": cogame,
        "policy_uri": policy_uri,
        "policy_packages": list(policy_packages or []),
    }


def make_game(
    game: str,
    num_agents: int = 40,
    cogs: int | None = None,
    max_steps: int | None = None,
    variants: Sequence[str] | None = None,
    **kwargs: Any,
) -> MettaGridConfig:
    """Create an AmongCogs environment by name."""
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected make_game kwargs: {unexpected}")
    if game not in GAMES:
        raise ValueError(f"Unknown game {game!r}. Available: {list(GAMES)}")

    n = cogs if cogs is not None else num_agents
    info = GAMES[game]
    mission_cls = info.get("mission_class")
    mission_factory = info["mission_factory"]
    if max_steps is None:
        max_steps = _default_max_steps(mission_cls)
    mission = mission_factory(n, max_steps)

    requested_variant_names: list[str] = []
    seen_variant_names: set[str] = set()
    for raw_name in variants or []:
        if not isinstance(raw_name, str):
            raise TypeError(f"Game variants must be strings, got {type(raw_name).__name__}")
        name = raw_name.strip()
        if not name or name in seen_variant_names:
            continue
        seen_variant_names.add(name)
        requested_variant_names.append(name)

    variant_names = list(requested_variant_names)
    if not variant_names and not _mission_owns_default_variants(mission, info):
        variant_names = _default_variant_names(mission)
    if variant_names:
        mission = mission.with_variants(_resolve_variants(info, variant_names))

    env = mission.make_env()
    env = env.model_copy(deep=True) if hasattr(env, "model_copy") else copy.deepcopy(env)
    if not env.label:
        env.label = mission.full_name()

    legacy_variants = _legacy_variants(mission, info)
    if legacy_variants is not None:
        for variant in legacy_variants:
            variant.modify_env(mission, env)

    if legacy_variants is not None and env.label == mission.full_name():
        for variant_name in _configured_variant_names(mission):
            env.label += f".{variant_name}"
    elif requested_variant_names and env.label == mission.full_name():
        for variant_name in requested_variant_names:
            env.label += f".{variant_name}"

    if isinstance(env, MettaGridConfig):
        env.game.max_steps = max_steps
    return env


def _default_max_steps(mission_cls: type | None) -> int:
    if mission_cls is None:
        return 10000
    field = mission_cls.model_fields.get("max_steps")
    max_steps = field.default if field is not None else 10000
    if callable(max_steps):
        max_steps = max_steps()
    return int(max_steps)


def _resolve_variants(info: dict[str, Any], variant_names: list[str]) -> list[Any]:
    cogame = info.get("cogame")
    if isinstance(cogame, CoGame):
        variant_types = {variant.name: type(variant) for variant in cogame.variant_registry.all()}
        unknown = [name for name in variant_names if name not in variant_types]
        if unknown:
            available = ", ".join(sorted(variant_types))
            raise ValueError(f"Unknown variant {unknown[0]!r}. Available: {available}")
        return [variant_types[name]() for name in variant_names]

    parse_variants = info.get("parse_variants")
    if parse_variants is not None:
        return parse_variants(variant_names)

    if info.get("mission_class") is not None:
        return list(variant_names)

    raise ValueError(f"Game {info!r} does not support explicit variants")


def _default_variant_names(mission: Any) -> list[str]:
    if _configured_variant_names(mission):
        return []

    names: list[str] = []
    default_variants = getattr(mission, "default_variants", None)
    if isinstance(default_variants, Sequence) and not isinstance(default_variants, (str, bytes)):
        names.extend(str(value) for value in default_variants if str(value))

    default_variant = getattr(mission, "default_variant", None)
    if isinstance(default_variant, str) and default_variant and default_variant not in names:
        names.append(default_variant)
    return names


def _legacy_variants(mission: Any, info: dict[str, Any] | None = None) -> list[Any] | None:
    if info is not None and isinstance(info.get("cogame"), CoGame):
        return None
    if _make_env_resolves_default_variants(mission):
        return None
    variants = getattr(mission, "variants", None)
    if not isinstance(variants, list):
        return None

    registry = getattr(mission, "_variant_registry", None)
    variant_map = getattr(registry, "_variants", None)
    if isinstance(variant_map, dict) and variant_map:
        return None
    return variants


def _make_env_resolves_default_variants(mission: Any) -> bool:
    return bool(getattr(mission, "resolve_default_variants_in_make_env", False))


def _mission_owns_default_variants(mission: Any, info: dict[str, Any]) -> bool:
    if isinstance(info.get("cogame"), CoGame):
        return True
    return _make_env_resolves_default_variants(mission)


def _configured_variant_names(mission: Any) -> list[str]:
    registry = getattr(mission, "_variant_registry", None)
    configured_names = getattr(registry, "configured_names", None)
    if callable(configured_names):
        names = [str(name) for name in configured_names() if str(name)]
        if names:
            return _prioritize_default_variant(mission, names)

    ordered_names = getattr(registry, "ordered_names", None)
    if callable(ordered_names):
        names = [str(name) for name in ordered_names() if str(name)]
        if names:
            return _prioritize_default_variant(mission, names)

    ordered = getattr(registry, "ordered", None)
    if callable(ordered):
        names = [
            str(name)
            for name in (getattr(variant, "name", "") for variant in ordered())
            if isinstance(name, str) and name
        ]
        if names:
            return _prioritize_default_variant(mission, names)

    configured = getattr(registry, "configured", None)
    if callable(configured):
        names = [
            str(name)
            for name in (getattr(variant, "name", "") for variant in configured())
            if isinstance(name, str) and name
        ]
        if names:
            return _prioritize_default_variant(mission, names)

    variant_map = getattr(registry, "_variants", None)
    if isinstance(variant_map, dict) and variant_map:
        names = [str(name) for name in variant_map if str(name)]
        return _prioritize_default_variant(mission, names)

    legacy_variants = _legacy_variants(mission)
    if legacy_variants is not None:
        return [
            str(name)
            for name in (getattr(variant, "name", "") for variant in legacy_variants)
            if isinstance(name, str) and name
        ]

    return []


def _prioritize_default_variant(mission: Any, names: list[str]) -> list[str]:
    default_variant = getattr(mission, "default_variant", None)
    if isinstance(default_variant, str) and default_variant in names:
        return [default_variant, *[name for name in names if name != default_variant]]
    return names


from amongcogs.game import game as _game  # noqa: E402, F401
