"""Content lock checks for Werewolf/Mafia ship readiness."""

from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "packages" / "mettagrid" / "nim" / "mettascope" / "data"

REQUIRED_ASSET_PATHS = [
    "agents/werewolf_mafia_villager.n.png",
    "agents/werewolf_mafia_villager.s.png",
    "agents/werewolf_mafia_villager.e.png",
    "agents/werewolf_mafia_villager.w.png",
    "agents/werewolf_mafia_werewolf.n.png",
    "agents/werewolf_mafia_werewolf.s.png",
    "agents/werewolf_mafia_werewolf.e.png",
    "agents/werewolf_mafia_werewolf.w.png",
    "agents/werewolf_mafia_dead.n.png",
    "agents/werewolf_mafia_dead.s.png",
    "agents/werewolf_mafia_dead.e.png",
    "agents/werewolf_mafia_dead.w.png",
    "objects/werewolf_mafia_tree.png",
    "objects/werewolf_mafia_cottage.png",
    "objects/werewolf_mafia_lantern.png",
    "objects/werewolf_mafia_villager_station.png",
    "objects/werewolf_mafia_werewolf_station.png",
    "objects/werewolf_mafia_meeting_bell.png",
    "minimap/werewolf_mafia_tree.png",
    "minimap/werewolf_mafia_cottage.png",
    "minimap/werewolf_mafia_lantern.png",
    "minimap/werewolf_mafia_villager_station.png",
    "minimap/werewolf_mafia_werewolf_station.png",
    "minimap/werewolf_mafia_meeting_bell.png",
    "icons/objects/werewolf_mafia_tree.png",
    "icons/objects/werewolf_mafia_cottage.png",
    "icons/objects/werewolf_mafia_lantern.png",
    "icons/objects/werewolf_mafia_villager_station.png",
    "icons/objects/werewolf_mafia_werewolf_station.png",
    "icons/objects/werewolf_mafia_meeting_bell.png",
    "profiles/werewolf_mafia_villager.png",
    "profiles/werewolf_mafia_werewolf.png",
    "profiles/werewolf_mafia_dead.png",
    "profiles/werewolf_mafia_villager_station.png",
    "profiles/werewolf_mafia_werewolf_station.png",
    "profiles/werewolf_mafia_meeting_bell.png",
    "resources/alive.png",
    "resources/vote_token.png",
    "resources/day_phase.png",
    "resources/night_phase.png",
    "resources/day_vote_open.png",
    "resources/night_hunt_open.png",
    "resources/accusation.png",
    "resources/suspicion.png",
    "backgrounds/werewolf_mafia_sky.png",
    "backgrounds/werewolf_mafia_mist.png",
    "terrain/repeating.werewolf_mafia_ground.png",
]

MAX_ASSET_BYTES_BY_PREFIX = {
    "agents/": 65_536,
    "objects/": 131_072,
    "minimap/": 4_096,
    "icons/": 16_384,
    "profiles/": 131_072,
    "resources/": 16_384,
    "backgrounds/": 196_608,
    "terrain/": 65_536,
}
TOTAL_ASSET_BYTES_BUDGET = 700_000


def _budget_for(path: str) -> int | None:
    for prefix, budget in MAX_ASSET_BYTES_BY_PREFIX.items():
        if path.startswith(prefix):
            return budget
    return None


def validate_content_lock() -> list[str]:
    missing = [path for path in REQUIRED_ASSET_PATHS if not (DATA_DIR / path).exists()]
    if missing:
        joined = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Missing required werewolf_mafia assets:\n{joined}")

    total_bytes = 0
    oversize: list[tuple[str, int, int]] = []
    for path in REQUIRED_ASSET_PATHS:
        size = (DATA_DIR / path).stat().st_size
        total_bytes += size
        budget = _budget_for(path)
        if budget is not None and size > budget:
            oversize.append((path, size, budget))

    if oversize:
        joined = "\n".join(f"- {path}: {size} bytes (budget {budget})" for path, size, budget in oversize)
        raise ValueError(f"Oversize werewolf_mafia assets:\n{joined}")

    if total_bytes > TOTAL_ASSET_BYTES_BUDGET:
        raise ValueError(
            f"werewolf_mafia content lock budget exceeded: {total_bytes} bytes > {TOTAL_ASSET_BYTES_BUDGET} bytes"
        )
    return REQUIRED_ASSET_PATHS
