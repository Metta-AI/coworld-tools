"""Shared goal-tree primitives for Python scripted agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from mettagrid.simulator import Action


class Goal:
    """Base class for all goals in the goal tree.

    Subclasses implement:
    - is_satisfied(ctx) -> bool: whether this goal is already met
    - preconditions() -> list[Goal]: sub-goals that must be satisfied first
    - execute(ctx) -> Action | None: produce an action, or None to skip/defer
    """

    name: str = "Goal"

    def is_satisfied(self, ctx: Any) -> bool:
        """Check if this goal is already satisfied."""
        return False

    def preconditions(self) -> list[Goal]:
        """Return sub-goals that must be satisfied before this goal can execute."""
        return []

    def execute(self, ctx: Any) -> Optional[Action]:
        """Produce an action to work toward this goal, or None to skip."""
        return Action(name="noop")


def evaluate_goals(
    goals: list[Goal],
    ctx: Any,
    *,
    fallback_action: Callable[[], Action] | None = None,
) -> Action:
    """Evaluate a priority-ordered goal list and return an action."""
    for goal in goals:
        if goal.is_satisfied(ctx):
            if ctx.trace:
                ctx.trace.skip(goal.name, "ok")
            continue

        leaf = _deepest_unsatisfied(goal, ctx)
        action = leaf.execute(ctx)
        if action is None:
            if ctx.trace:
                ctx.trace.skip(leaf.name, "deferred")
            continue

        if ctx.trace:
            ctx.trace.active_goal_chain = _build_chain(goal, leaf)
            ctx.trace.action_name = action.name
        return action

    if fallback_action is None:
        return Action(name="noop")
    fallback = fallback_action()
    if ctx.trace:
        ctx.trace.active_goal_chain = "AllGoalsSatisfied"
        ctx.trace.action_name = fallback.name
    return fallback


def _deepest_unsatisfied(goal: Goal, ctx: Any) -> Goal:
    """Find the deepest unsatisfied precondition in the goal tree."""
    for pre in goal.preconditions():
        if not pre.is_satisfied(ctx):
            if ctx.trace:
                ctx.trace.activate(pre.name)
            return _deepest_unsatisfied(pre, ctx)
    return goal


def _build_chain(root: Goal, leaf: Goal) -> str:
    """Build a display chain like 'MineCarbon>BeNearExtractor'."""
    if root is leaf:
        return root.name
    chain = [root.name]
    _find_path(root, leaf, chain)
    return ">".join(chain)


def _find_path(current: Goal, target: Goal, chain: list[str]) -> bool:
    """Depth-first search to find the path from current to target goal."""
    for pre in current.preconditions():
        if pre is target:
            chain.append(pre.name)
            return True
        chain.append(pre.name)
        if _find_path(pre, target, chain):
            return True
        chain.pop()
    return False
