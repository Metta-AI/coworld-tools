"""Hook registration and dispatch for Orpheus pipeline phase boundaries.

Hook signatures:
- pre_perception(frame, belief_state) -> frame | None
- post_perception(frame, perception, belief_state) -> None
- pre_belief_update(perception, belief_state) -> None
- post_belief_update(belief_state) -> None
- pre_decide(belief_state, action_memory) -> None
- post_decide(belief_state, action_memory) -> None
- pre_act(belief_state, action_memory) -> None
- post_act(belief_state, action_memory, act_command) -> None
"""

from __future__ import annotations

import copy
import dataclasses
import traceback
from collections.abc import Callable
from enum import Enum
from typing import Any

from orpheus.action_memory import ActionMemory
from orpheus.belief_state import BeliefState
from orpheus.logging import Logger
from orpheus.mode import ModeDirective, ModeRegistry


class HookPoint(Enum):
    """Pipeline phase boundaries where agent hooks may run."""

    # PRE_PERCEPTION: (frame, belief_state) -> frame | None
    PRE_PERCEPTION = "pre_perception"
    # POST_PERCEPTION: (frame, perception, belief_state) -> None
    POST_PERCEPTION = "post_perception"
    # PRE_BELIEF_UPDATE: (perception, belief_state) -> None
    PRE_BELIEF_UPDATE = "pre_belief_update"
    # POST_BELIEF_UPDATE: (belief_state) -> None
    POST_BELIEF_UPDATE = "post_belief_update"
    # PRE_DECIDE: (belief_state, action_memory) -> None
    PRE_DECIDE = "pre_decide"
    # POST_DECIDE: (belief_state, action_memory) -> None
    POST_DECIDE = "post_decide"
    # PRE_ACT: (belief_state, action_memory) -> None
    PRE_ACT = "pre_act"
    # POST_ACT: (belief_state, action_memory, act_command) -> None
    POST_ACT = "post_act"


class HookRegistry:
    """Stores and dispatches agent-level and mode-level hooks."""

    def __init__(self) -> None:
        self._agent_hooks: dict[HookPoint, list[Callable]] = {
            hp: [] for hp in HookPoint
        }
        self._mode_hooks: dict[HookPoint, dict[str, list[Callable]]] = {
            hp: {} for hp in HookPoint
        }
        self._agent_mode_switch_callbacks: list[Callable] = []
        self._mode_switch_callbacks: dict[str, list[Callable]] = {}

    def register_hook(
        self,
        hook_point: HookPoint,
        callback: Callable,
        modes: list[str] | None = None,
    ) -> None:
        """Register `callback` at a hook point, optionally scoped to modes."""
        if modes is None:
            self._agent_hooks[hook_point].append(callback)
            return

        for mode in modes:
            self._mode_hooks[hook_point].setdefault(mode, []).append(callback)

    def register_mode_switch_callback(
        self,
        callback: Callable,
        modes: list[str] | None = None,
    ) -> None:
        """Register a mode-switch callback, optionally scoped to departing modes."""
        if modes is None:
            self._agent_mode_switch_callbacks.append(callback)
            return

        for mode in modes:
            self._mode_switch_callbacks.setdefault(mode, []).append(callback)

    def dispatch(
        self,
        hook_point: HookPoint,
        current_mode_name: str | None,
        belief_state: BeliefState,
        *args: Any,
        logger: Callable[[str], None] | None = None,
    ) -> Any:
        """Dispatch hooks for `hook_point`, rolling back belief on failures."""
        if hook_point is HookPoint.PRE_PERCEPTION:
            frame = args[0]
            for kind, hook in self._iter_hooks(hook_point, current_mode_name):
                snapshot = copy.deepcopy(belief_state)
                try:
                    result = hook(frame, belief_state)
                    if result is not None:
                        frame = result
                except Exception as exc:
                    self._rollback(belief_state, snapshot)
                    self._log_failure(
                        logger,
                        hook_point,
                        current_mode_name,
                        kind,
                        hook,
                        belief_state,
                        exc,
                    )
            return frame

        for kind, hook in self._iter_hooks(hook_point, current_mode_name):
            snapshot = copy.deepcopy(belief_state)
            try:
                self._call_hook(hook_point, hook, belief_state, *args)
            except Exception as exc:
                self._rollback(belief_state, snapshot)
                self._log_failure(
                    logger,
                    hook_point,
                    current_mode_name,
                    kind,
                    hook,
                    belief_state,
                    exc,
                )
        return None

    def dispatch_mode_switch(
        self,
        current_mode_name: str,
        belief_state: BeliefState,
        action_memory: ActionMemory,
        directive: ModeDirective,
        mode_registry: ModeRegistry,
        logger: Callable[[str], None] | None = None,
    ) -> ModeDirective:
        """Dispatch mode-switch callbacks and return the final directive.

        Agent-level callbacks fire first, followed by callbacks registered for
        the mode being departed. A callback may mutate belief state and may
        return a replacement ModeDirective; invalid replacements are logged and
        discarded.
        """
        current_directive = directive
        for kind, callback in self._iter_mode_switch_callbacks(current_mode_name):
            snapshot = copy.deepcopy(belief_state)
            try:
                override = callback(
                    belief_state,
                    action_memory,
                    current_directive,
                )
            except Exception as exc:
                self._rollback(belief_state, snapshot)
                self._log_failure(
                    logger,
                    "mode_switch",
                    current_mode_name,
                    kind,
                    callback,
                    belief_state,
                    exc,
                )
                continue

            if override is None:
                continue
            if self._is_directive_valid(override, mode_registry):
                current_directive = override
            elif logger is not None:
                callback_name = getattr(callback, "__name__", repr(callback))
                if isinstance(logger, Logger):
                    logger.event(
                        "invalid_mode_switch_override",
                        {
                            "hook_point": "mode_switch",
                            "mode": current_mode_name,
                            "kind": kind,
                            "hook_name": callback_name,
                            "directive": repr(override),
                        },
                    )
                else:
                    logger(
                        "invalid_mode_switch_override: "
                        "point=mode_switch "
                        f"mode={current_mode_name!r} "
                        f"kind={kind} "
                        f"hook={callback_name} "
                        f"directive={override!r}"
                    )
        return current_directive

    def _iter_hooks(
        self,
        hook_point: HookPoint,
        current_mode_name: str | None,
    ) -> list[tuple[str, Callable]]:
        """Return agent hooks followed by active-mode hooks for a point."""
        hooks: list[tuple[str, Callable]] = [
            ("agent", hook) for hook in self._agent_hooks[hook_point]
        ]
        if current_mode_name is not None:
            hooks.extend(
                ("mode", hook)
                for hook in self._mode_hooks[hook_point].get(
                    current_mode_name, []
                )
            )
        return hooks

    def _iter_mode_switch_callbacks(
        self,
        current_mode_name: str,
    ) -> list[tuple[str, Callable]]:
        """Return agent callbacks followed by departing-mode callbacks."""
        callbacks: list[tuple[str, Callable]] = [
            ("agent", callback)
            for callback in self._agent_mode_switch_callbacks
        ]
        callbacks.extend(
            ("mode", callback)
            for callback in self._mode_switch_callbacks.get(current_mode_name, [])
        )
        return callbacks

    def _call_hook(
        self,
        hook_point: HookPoint,
        hook: Callable,
        belief_state: BeliefState,
        *args: Any,
    ) -> None:
        """Call a non-pre-perception hook with its documented signature."""
        if hook_point in {
            HookPoint.POST_PERCEPTION,
            HookPoint.PRE_BELIEF_UPDATE,
        }:
            hook(*args, belief_state)
        elif hook_point is HookPoint.POST_BELIEF_UPDATE:
            hook(belief_state)
        elif hook_point in {
            HookPoint.PRE_DECIDE,
            HookPoint.POST_DECIDE,
            HookPoint.PRE_ACT,
        }:
            hook(belief_state, *args)
        elif hook_point is HookPoint.POST_ACT:
            hook(belief_state, *args)
        else:
            hook(*args, belief_state)

    def _rollback(
        self,
        belief_state: BeliefState,
        snapshot: BeliefState,
    ) -> None:
        """Restore a live belief state in place from a snapshot."""
        for field in dataclasses.fields(belief_state):
            setattr(belief_state, field.name, getattr(snapshot, field.name))

    def _log_failure(
        self,
        logger: Callable[[str], None] | None,
        hook_point: HookPoint | str,
        current_mode_name: str | None,
        kind: str,
        hook: Callable,
        belief_state: BeliefState,
        exc: Exception,
    ) -> None:
        """Report a hook failure if a logger callback was provided."""
        if logger is None:
            return

        hook_name = getattr(hook, "__name__", repr(hook))
        point = hook_point.value if isinstance(hook_point, HookPoint) else hook_point
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if isinstance(logger, Logger):
            logger.event(
                "hook_failure",
                {
                    "hook_point": point,
                    "mode": current_mode_name,
                    "kind": kind,
                    "hook_name": hook_name,
                    "exception": repr(exc),
                    "traceback": tb,
                    "tick": belief_state.tick,
                },
            )
            return

        logger(
            "hook_failed: "
            f"point={point} "
            f"mode={current_mode_name!r} "
            f"kind={kind} "
            f"hook={hook_name} "
            f"tick={belief_state.tick}: "
            f"{exc!r}\n{tb}"
        )

    def _is_directive_valid(
        self,
        directive: ModeDirective,
        mode_registry: ModeRegistry,
    ) -> bool:
        """Return True when a directive targets a registered mode with valid params."""
        mode_cls = mode_registry.get(directive.mode)
        return mode_cls is not None and isinstance(
            directive.params,
            mode_cls.params_type,
        )


__all__ = ["HookPoint", "HookRegistry"]
