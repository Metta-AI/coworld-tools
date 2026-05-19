"""Variant tree for cogame-euchre.

Euchre ships with no variants in v1. Additional variants (e.g. fixed trump,
play-to-10, stick-the-dealer, go-alone) can be added here as new modules that
subclass :class:`cogame_euchre.framework.CoGameMissionVariant`.

Structure mirrors the cogame template convention:

* ``PUBLIC_VARIANT_TYPES`` — user-facing variants.
* ``HIDDEN_VARIANT_TYPES`` — interface / composition variants.
* ``resolve_variant_selection(names)`` — instantiate + run the full lifecycle
  (dependency resolution, topological configure order, configure phase) for
  a list of variant names.
"""

from __future__ import annotations

from collections.abc import Sequence

from cogame_euchre.framework import CoGameMissionVariant, VariantRegistry

PUBLIC_VARIANT_TYPES: tuple[type[CoGameMissionVariant], ...] = ()
HIDDEN_VARIANT_TYPES: tuple[type[CoGameMissionVariant], ...] = ()
ALL_VARIANT_TYPES: tuple[type[CoGameMissionVariant], ...] = (
    PUBLIC_VARIANT_TYPES + HIDDEN_VARIANT_TYPES
)

VARIANTS: tuple[CoGameMissionVariant, ...] = tuple(cls() for cls in PUBLIC_VARIANT_TYPES)
HIDDEN_VARIANTS: tuple[CoGameMissionVariant, ...] = tuple(cls() for cls in HIDDEN_VARIANT_TYPES)

_VARIANT_TYPES_BY_NAME: dict[str, type[CoGameMissionVariant]] = {
    v.name: type(v) for v in (*VARIANTS, *HIDDEN_VARIANTS)
}
HIDDEN_VARIANT_NAMES = frozenset(v.name for v in HIDDEN_VARIANTS)


def normalize_variant_names(names: Sequence[str]) -> list[str]:
    """Strip, dedupe, and validate a list of variant names."""
    requested: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = raw_name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        requested.append(name)
    unknown = [name for name in requested if name not in _VARIANT_TYPES_BY_NAME]
    if unknown:
        available = ", ".join(sorted(_VARIANT_TYPES_BY_NAME)) or "(none)"
        raise ValueError(f"Unknown variant {unknown[0]!r}. Available: {available}")
    return requested


def _instantiate_variant(name: str) -> CoGameMissionVariant:
    return _VARIANT_TYPES_BY_NAME[name]()  # pyright: ignore[reportCallIssue]


def resolve_variant_selection(names: Sequence[str]) -> VariantRegistry:
    """Instantiate variants and run the full configure lifecycle."""
    requested_names = normalize_variant_names(names)
    registry = VariantRegistry([_instantiate_variant(name) for name in requested_names])
    registry.run_configure(requested_names)

    if ALL_VARIANT_TYPES:
        unexpected = [v.name for v in registry.all() if not isinstance(v, ALL_VARIANT_TYPES)]
        assert not unexpected, f"cogame-euchre registry resolved non-local variants: {unexpected}"
    return registry


def parse_variants(names: Sequence[str]) -> list[CoGameMissionVariant]:
    """Return variants in configure (topological) order."""
    return list(resolve_variant_selection(names).configured())


__all__ = [
    "ALL_VARIANT_TYPES",
    "HIDDEN_VARIANTS",
    "HIDDEN_VARIANT_NAMES",
    "HIDDEN_VARIANT_TYPES",
    "PUBLIC_VARIANT_TYPES",
    "VARIANTS",
    "normalize_variant_names",
    "parse_variants",
    "resolve_variant_selection",
]
