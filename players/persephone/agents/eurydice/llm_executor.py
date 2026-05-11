"""Translate validated LLM decisions into Eurydice execution primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orpheus.mode import ModeDirective
from orpheus.task import Task
from orpheus.idle import IdleTask
from orpheus.tasks import (
    AcceptColorExchangeTask,
    AcceptRoleExchangeTask,
    ExitWhisperTask,
    GrantEntryTask,
    OfferColorExchangeTask,
    OfferRoleExchangeTask,
    SendMessageTask,
)

from agents.eurydice.advanced_modes import HostageSelectParams
from agents.eurydice.llm_action_mode import LLMActionParams
from agents.eurydice.modes import ProbeTargetParams
from agents.eurydice.pipeline import player_index_to_id
from agents.eurydice.types import PlayerID, ProbeIntent


@dataclass(frozen=True)
class LLMExecution:
    """Validated execution plan for one model decision."""

    directive: ModeDirective | None = None
    task: Task | None = None
    reason: str = ""


def directive_for_decision(decision: dict[str, Any]) -> ModeDirective | None:
    """Map a validated top-level decision to a registered mode directive."""

    action = decision.get("action")
    if action == "probe_player":
        target = _player_id(decision.get("target"))
        if target is None:
            return None
        return ModeDirective(
            "probe_target",
            ProbeTargetParams(target=target, intent=ProbeIntent.GENERAL),
        )

    if action in {
        "hold",
        "create_whisper",
        "join_whisper",
        "send_whisper",
        "send_global",
        "open_global",
        "open_info",
        "accept_color",
        "accept_role",
        "offer_color",
        "offer_role",
        "grant_entry",
        "deny_entry",
        "reject_offer",
        "exit_whisper",
        "seek_leadership",
        "select_hostage",
        "move_to",
    }:
        if action == "seek_leadership":
            return ModeDirective("seek_leadership")
        if action == "select_hostage":
            return ModeDirective(
                "hostage_select",
                HostageSelectParams(
                    move=tuple(
                        item
                        for item in (
                            _player_id(raw)
                            for raw in decision.get("hostage_targets") or []
                        )
                        if item is not None
                    )
                ),
            )
        return ModeDirective(
            "llm_action",
            LLMActionParams(
                action=str(action),
                target=_player_id(decision.get("target")),
                destination=_coordinate(decision.get("destination")),
                hostage_targets=tuple(
                    item
                    for item in (
                        _player_id(raw)
                        for raw in decision.get("hostage_targets") or []
                    )
                    if item is not None
                ),
                message=decision.get("message"),
            ),
        )
    return None


def task_for_whisper_decision(decision: dict[str, Any], belief_state) -> Task | None:
    """Map a validated in-whisper decision to one deterministic task."""

    action = decision.get("action")
    target = _player_id(decision.get("target"))
    if action == "hold":
        return IdleTask()
    if action == "send_whisper":
        return SendMessageTask(text=str(decision.get("message") or ""), channel="whisper")
    if action == "grant_entry":
        return GrantEntryTask()
    if action == "deny_entry":
        return IdleTask()
    if action == "offer_color":
        return OfferColorExchangeTask()
    if action == "offer_role":
        return OfferRoleExchangeTask()
    if action == "accept_color":
        index = _target_index(belief_state, target)
        return AcceptColorExchangeTask(index) if index is not None else IdleTask()
    if action == "accept_role":
        index = _target_index(belief_state, target)
        return AcceptRoleExchangeTask(index) if index is not None else IdleTask()
    if action in {"reject_offer", "exit_whisper"}:
        return ExitWhisperTask()
    return None


def _player_id(value: Any) -> PlayerID | None:
    if (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    ):
        return (int(value[0]), int(value[1]))
    return None


def _coordinate(value: Any) -> tuple[int, int] | None:
    return _player_id(value)


def _target_index(belief_state, target: PlayerID | None) -> int | None:
    if target is None:
        return None
    for index in getattr(belief_state, "whisper_occupants", []) or []:
        if player_index_to_id(index, belief_state) == target:
            return index
    for index in getattr(belief_state, "players", {}):
        if player_index_to_id(index, belief_state) == target:
            return index
    return None


__all__ = ["LLMExecution", "directive_for_decision", "task_for_whisper_decision"]
