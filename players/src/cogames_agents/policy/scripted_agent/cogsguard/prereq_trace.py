from __future__ import annotations


def prereq_missing(
    action_type: str,
    *,
    gear: int,
    heart: int,
    influence: int = 0,
) -> dict[str, bool]:
    if action_type not in {"align", "scramble"}:
        raise ValueError(f"Unsupported action_type: {action_type}")
    return {"gear": gear < 1, "heart": heart < 1}


def format_prereq_trace_line(
    *,
    step: int,
    agent_id: int,
    action_type: str,
    gear: int,
    heart: int,
    influence: int,
    missing: dict[str, bool],
) -> str:
    missing_str = ",".join(key for key, is_missing in missing.items() if is_missing) or "-"
    return (
        f"step={step} agent={agent_id} action={action_type} "
        f"gear={gear} heart={heart} influence={influence} missing[{missing_str}]"
    )
