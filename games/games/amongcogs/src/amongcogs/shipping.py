"""Shared helpers for AmongCogs shipping audits and release gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Sequence


@dataclass(frozen=True)
class NumericProfile:
    """Compact numeric profile for audit metrics."""

    min: float
    p50: float
    p95: float
    max: float
    mean: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def percentile(values: Sequence[float], q: float) -> float:
    """Return percentile from an already sorted sequence."""
    if not values:
        raise ValueError("values must not be empty")
    if q <= 0:
        return values[0]
    if q >= 1:
        return values[-1]
    idx = q * (len(values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(values) - 1)
    frac = idx - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def profile(values: Sequence[float]) -> NumericProfile:
    """Build min/p50/p95/max/mean profile for a numeric sequence."""
    if not values:
        raise ValueError("values must not be empty")
    sorted_values = sorted(float(value) for value in values)
    return NumericProfile(
        min=sorted_values[0],
        p50=percentile(sorted_values, 0.50),
        p95=percentile(sorted_values, 0.95),
        max=sorted_values[-1],
        mean=mean(sorted_values),
    )


def build_gate_check(
    name: str,
    value: float,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> dict[str, object]:
    """Create a standardized gate-check row."""
    passed = True
    if min_value is not None and value < min_value:
        passed = False
    if max_value is not None and value > max_value:
        passed = False

    check: dict[str, object] = {
        "name": name,
        "value": value,
        "passed": passed,
    }
    if min_value is not None:
        check["min"] = min_value
    if max_value is not None:
        check["max"] = max_value
    return check
