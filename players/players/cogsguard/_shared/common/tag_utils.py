from __future__ import annotations

from typing import Optional

_SKIP_PREFIXES = ("team:",)


def select_primary_tag(tags: list[str], *, priority_objects: Optional[set[str]] = None) -> str:
    if not tags:
        return "unknown"

    for tag in tags:
        if tag.startswith("type:"):
            return tag.split(":", 1)[1]

    if priority_objects:
        for tag in tags:
            if tag and not any(tag.startswith(p) for p in _SKIP_PREFIXES) and tag in priority_objects:
                return tag

    for tag in tags:
        if tag and not any(tag.startswith(p) for p in _SKIP_PREFIXES):
            return tag

    for tag in tags:
        if tag:
            return tag

    return "unknown"


def derive_alignment_from_tags(
    obj_name: str,
    tags: list[str],
) -> Optional[str]:
    for tag in tags:
        if tag == "team:cogs":
            return "cogs"
        if tag == "team:clips":
            return "clips"

    if "c:" in obj_name:
        return "cogs"
    if "clips" in obj_name:
        return "clips"
    return None
