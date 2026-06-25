"""KEY=VALUE override parsing for `cgp play`.

Normalizes keys by turning dashes into underscores, then coerces the
value through int -> float -> bool -> JSON -> str in that order.
Bare `"true"` / `"false"` (case-insensitive) become booleans before
JSON is tried (JSON also parses them, but `true` isn't valid JSON
without surrounding quotes in some shells).
"""

from __future__ import annotations

import json
from typing import Any


def _coerce(value: str) -> Any:
    # int
    try:
        return int(value)
    except ValueError:
        pass
    # float
    try:
        return float(value)
    except ValueError:
        pass
    # bool
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    # json (objects/arrays/strings with embedded quotes)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    # fallback: raw string
    return value


def parse_override(spec: str) -> tuple[str, Any]:
    """Parse `KEY=VALUE`. Dashes in KEY become underscores."""
    if "=" not in spec:
        raise ValueError(f"override must contain '=': {spec!r}")
    key, _, value = spec.partition("=")
    key = key.strip().replace("-", "_")
    if not key:
        raise ValueError(f"empty key in override: {spec!r}")
    return key, _coerce(value)


def parse_variant_override(spec: str) -> tuple[str, str, Any]:
    """Parse `VARIANT.KEY=VALUE`. Dashes → underscores in both VARIANT and KEY."""
    key_part, _, value = spec.partition("=")
    if not value and "=" not in spec:
        raise ValueError(f"variant override must contain '=': {spec!r}")
    if "." not in key_part:
        raise ValueError(f"variant override must contain '.': {spec!r}")
    variant, _, key = key_part.partition(".")
    variant = variant.strip().replace("-", "_")
    key = key.strip().replace("-", "_")
    if not variant or not key:
        raise ValueError(f"empty variant or key in override: {spec!r}")
    return variant, key, _coerce(value)


__all__ = ["parse_override", "parse_variant_override"]
