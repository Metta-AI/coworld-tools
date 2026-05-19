"""Shared helpers for Toolsy goal task normalization."""

from __future__ import annotations

from typing import Any


def clean_goal_text(text: Any) -> str:
    value = str(text or "").strip()
    for prefix in ("- [ ] ", "- [x] ", "- [X] ", "- ", "* ", "• "):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    if ". " in value:
        number, _, rest = value.partition(". ")
        if number.isdigit():
            value = rest.strip()
    return value


def goal_lines(prompt: str) -> list[str]:
    return [text for text in (clean_goal_text(line) for line in str(prompt or "").splitlines()) if text]


def active_goals_text(tasks: list[dict]) -> str:
    return "\n".join(task["text"] for task in tasks if not task.get("completed"))


def public_goal_tasks(tasks: list[dict]) -> list[dict]:
    return [
        {"id": str(task["id"]), "text": str(task["text"]), "completed": bool(task.get("completed"))}
        for task in tasks
        if str(task.get("text", "")).strip()
    ]


def normalize_goal_tasks(raw_tasks: Any) -> list[dict]:
    if not isinstance(raw_tasks, list):
        return []
    tasks: list[dict] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(raw_tasks, start=1):
        if isinstance(raw, str):
            goal_id = f"goal-{index}"
            text = clean_goal_text(raw)
            completed = False
        elif isinstance(raw, dict):
            goal_id = str(raw.get("id") or raw.get("goal_id") or f"goal-{index}")
            text = clean_goal_text(raw.get("text", raw.get("goal", "")))
            completed = bool(raw.get("completed"))
        else:
            continue
        if not text:
            continue
        base_id = goal_id
        suffix = 2
        while goal_id in used_ids:
            goal_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(goal_id)
        tasks.append({"id": goal_id, "text": text, "completed": completed})
    return tasks
