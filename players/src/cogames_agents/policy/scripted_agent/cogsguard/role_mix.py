from __future__ import annotations

_ROLE_ORDER = ["scrambler", "aligner", "miner", "scout"]


def default_role_counts(num_agents: int) -> dict[str, int]:
    if num_agents <= 1:
        return {"miner": 1}
    if num_agents == 2:
        return {"scrambler": 1, "miner": 1}
    if num_agents == 3:
        return {"scrambler": 1, "miner": 1, "scout": 1}
    if num_agents <= 7:
        scramblers = 1
        aligners = 1
        scouts = 1
    else:
        scramblers = max(2, num_agents // 6)
        aligners = max(2, num_agents // 6)
        scouts = 1
    miners = max(1, num_agents - scramblers - scouts - aligners)
    return {
        "scrambler": scramblers,
        "aligner": aligners,
        "miner": miners,
        "scout": scouts,
    }


def normalize_counts(num_agents: int, counts: dict[str, int]) -> dict[str, int]:
    normalized = {role: count for role, count in counts.items() if isinstance(count, int)}
    total = sum(normalized.values())
    if total < num_agents:
        normalized["miner"] = normalized.get("miner", 0) + (num_agents - total)
    elif total > num_agents:
        normalized["miner"] = max(0, normalized.get("miner", 0) - (total - num_agents))
    return normalized


def build_role_plan(num_agents: int, counts: dict[str, int]) -> list[str]:
    ordered = [role for role_name in _ROLE_ORDER for role in [role_name] * counts.get(role_name, 0)]
    if len(ordered) < num_agents:
        ordered.extend(["miner"] * (num_agents - len(ordered)))
    return ordered[:num_agents]
