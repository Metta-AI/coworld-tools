"""One-shot semantic action mode for validated LLM decisions."""

from __future__ import annotations

from dataclasses import dataclass

from orpheus.idle import IdleTask
from orpheus.mode import Mode, ModeDirective, ModeParams
from orpheus.perception.types import View
from orpheus.task import Task
from orpheus.tasks import (
    AcceptColorExchangeTask,
    AcceptRoleExchangeTask,
    CreateWhisperTask,
    ExitWhisperTask,
    GrantEntryTask,
    MoveToTask,
    OfferColorExchangeTask,
    OfferRoleExchangeTask,
    CloseViewTask,
    OpenGlobalChatTask,
    OpenInfoScreenTask,
    RequestEntryTask,
    SendMessageTask,
)

from agents.eurydice.ext_keys import MODE_COMPLETE
from agents.eurydice.pipeline import player_index_to_id
from agents.eurydice.types import PlayerID


@dataclass(frozen=True)
class LLMActionParams(ModeParams):
    """Typed params for one validated LLM semantic action."""

    action: str = "hold"
    target: PlayerID | None = None
    destination: tuple[int, int] | None = None
    hostage_targets: tuple[PlayerID, ...] = ()
    message: str | None = None


class LLMActionMode(Mode):
    """Execute one semantic action, then mark the mode complete."""

    params_type = LLMActionParams
    params: LLMActionParams = LLMActionParams()

    def select_task(self, belief_state, action_memory) -> Task | None:
        del action_memory
        action = self.params.action

        if action == "hold":
            _complete_mode(belief_state)
            return IdleTask()
        if action == "move_to" and self.params.destination is not None:
            if not _view_is(belief_state, {View.PLAYING, View.WAITING_ENTRY}):
                return _complete_idle(belief_state)
            return MoveToTask(*self.params.destination)
        if action == "open_global":
            view = getattr(belief_state, "view", None)
            if view is View.GLOBAL_CHAT:
                _complete_mode(belief_state)
                return IdleTask()
            if view is View.INFO_SCREEN:
                return CloseViewTask()
            if view not in {View.PLAYING, View.HOSTAGE_SELECT, View.LEADER_SUMMIT}:
                return _complete_idle(belief_state)
            return OpenGlobalChatTask()
        if action == "open_info":
            view = getattr(belief_state, "view", None)
            if view is View.INFO_SCREEN:
                _complete_mode(belief_state)
                return IdleTask()
            if view is View.GLOBAL_CHAT:
                return CloseViewTask()
            if view not in {View.PLAYING, View.HOSTAGE_SELECT, View.LEADER_SUMMIT}:
                return _complete_idle(belief_state)
            return OpenInfoScreenTask()
        if action == "send_global":
            view = getattr(belief_state, "view", None)
            if view is View.GLOBAL_CHAT:
                _complete_mode(belief_state)
                return SendMessageTask(text=self.params.message or "", channel="global")
            if view in {View.PLAYING, View.HOSTAGE_SELECT, View.LEADER_SUMMIT}:
                return OpenGlobalChatTask()
            if view is View.INFO_SCREEN:
                return CloseViewTask()
            return _complete_idle(belief_state)
        if action == "send_whisper":
            if not _view_is(belief_state, {View.WHISPER, View.LEADER_SUMMIT}):
                return _complete_idle(belief_state)
            _complete_mode(belief_state)
            return SendMessageTask(text=self.params.message or "", channel="whisper")
        if action == "create_whisper":
            if not _view_is(belief_state, {View.PLAYING}):
                return _complete_idle(belief_state)
            return CreateWhisperTask()
        if action == "join_whisper":
            if not _view_is(belief_state, {View.PLAYING}):
                return _complete_idle(belief_state)
            index = _target_index(belief_state, self.params.target)
            if index is None:
                _complete_mode(belief_state)
                return IdleTask()
            return RequestEntryTask(player_index=index)
        if action == "grant_entry":
            if not _view_is(belief_state, {View.WHISPER}):
                return _complete_idle(belief_state)
            _complete_mode(belief_state)
            return GrantEntryTask()
        if action == "deny_entry":
            _complete_mode(belief_state)
            return IdleTask()
        if action == "offer_color":
            if not _view_is(belief_state, {View.WHISPER}):
                return _complete_idle(belief_state)
            _complete_mode(belief_state)
            return OfferColorExchangeTask()
        if action == "offer_role":
            if not _view_is(belief_state, {View.WHISPER}):
                return _complete_idle(belief_state)
            _complete_mode(belief_state)
            return OfferRoleExchangeTask()
        if action == "accept_color":
            if not _view_is(belief_state, {View.WHISPER}):
                return _complete_idle(belief_state)
            index = _target_index(belief_state, self.params.target)
            if index is None:
                _complete_mode(belief_state)
                return IdleTask()
            _complete_mode(belief_state)
            return AcceptColorExchangeTask(player_index=index)
        if action == "accept_role":
            if not _view_is(belief_state, {View.WHISPER}):
                return _complete_idle(belief_state)
            index = _target_index(belief_state, self.params.target)
            if index is None:
                _complete_mode(belief_state)
                return IdleTask()
            _complete_mode(belief_state)
            return AcceptRoleExchangeTask(player_index=index)
        if action == "exit_whisper":
            if not _view_is(belief_state, {View.WHISPER}):
                return _complete_idle(belief_state)
            return ExitWhisperTask()
        if action == "reject_offer":
            if not _view_is(belief_state, {View.WHISPER}):
                return _complete_idle(belief_state)
            return ExitWhisperTask()

        _complete_mode(belief_state)
        return IdleTask()

    def mode_enter(self, belief_state, action_memory) -> None:
        del action_memory
        belief_state.extra.pop(MODE_COMPLETE, None)

    def mode_switch_cleanup(
        self,
        belief_state,
        action_memory,
        new_mode_directive: ModeDirective,
    ) -> None:
        del belief_state, action_memory, new_mode_directive


def _target_index(belief_state, target: PlayerID | None) -> int | None:
    if target is None:
        return None
    for index in getattr(belief_state, "players", {}):
        if player_index_to_id(index, belief_state) == target:
            return index
    for index in getattr(belief_state, "whisper_occupants", []) or []:
        if player_index_to_id(index, belief_state) == target:
            return index
    return None


def _complete_mode(belief_state) -> None:
    belief_state.extra[MODE_COMPLETE] = True


def _complete_idle(belief_state) -> IdleTask:
    _complete_mode(belief_state)
    return IdleTask()


def _view_is(belief_state, views: set[View]) -> bool:
    return getattr(belief_state, "view", None) in views


__all__ = ["LLMActionMode", "LLMActionParams"]
