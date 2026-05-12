"""Shared trace structures for Python scripted agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TraceEntry:
    """One goal evaluation entry."""

    goal_name: str
    satisfied: bool
    detail: str = ""


@dataclass
class TraceLog:
    """Collects trace information during a single tick."""

    entries: list[TraceEntry] = field(default_factory=list)
    active_goal_chain: str = ""
    action_name: str = ""
    blackboard_summary: str = ""
    nav_target: Optional[tuple[int, int]] = None
    steps_since_useful: int = 0

    def skip(self, goal_name: str, reason: str = "ok") -> None:
        self.entries.append(TraceEntry(goal_name=goal_name, satisfied=True, detail=reason))

    def activate(self, goal_name: str, detail: str = "") -> None:
        self.entries.append(TraceEntry(goal_name=goal_name, satisfied=False, detail=detail))

    def format_line(
        self,
        step: int,
        agent_id: int,
        role: str,
        pos: tuple[int, int],
        hp: int,
        level: int,
    ) -> str:
        idle_str = f" IDLE={self.steps_since_useful}" if self.steps_since_useful >= 20 else ""
        prefix = f"[t={step} a={agent_id} {role} ({pos[0]},{pos[1]}) hp={hp}{idle_str}]"

        if level == 1:
            return f"{prefix} {self.active_goal_chain} → {self.action_name}"

        if level == 2:
            skips = " ".join(f"skip:{e.goal_name}({e.detail})" for e in self.entries if e.satisfied)
            target_str = ""
            if self.nav_target:
                dist = abs(self.nav_target[0] - pos[0]) + abs(self.nav_target[1] - pos[1])
                target_str = f" dist={dist}"
            bb = f" | bb={{{self.blackboard_summary}}}" if self.blackboard_summary else ""
            idle_detail = f" idle={self.steps_since_useful}" if self.steps_since_useful > 0 else ""
            return f"{prefix} {skips} → {self.active_goal_chain}{target_str} → {self.action_name}{bb}{idle_detail}"

        all_entries = " ".join(f"{'skip' if e.satisfied else 'ACTIVE'}:{e.goal_name}({e.detail})" for e in self.entries)
        target_str = f" nav_target={self.nav_target}" if self.nav_target else ""
        bb = f" bb={{{self.blackboard_summary}}}" if self.blackboard_summary else ""
        idle_detail = f" idle={self.steps_since_useful}"
        return f"{prefix} {all_entries}{target_str} → {self.action_name}{bb}{idle_detail}"
