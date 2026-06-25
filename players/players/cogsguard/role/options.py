from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from mettagrid.simulator import Action

from .types import CogsguardAgentState

OptionPredicate = Callable[[CogsguardAgentState], bool]
OptionAction = Callable[[CogsguardAgentState], Action]


@dataclass
class OptionDef:
    name: str
    can_start: OptionPredicate
    act: OptionAction
    should_terminate: OptionPredicate
    interruptible: bool = True


def options_always_can_start(_: CogsguardAgentState) -> bool:
    return True


def options_always_terminate(_: CogsguardAgentState) -> bool:
    return True


def run_options(s: CogsguardAgentState, options: list[OptionDef]) -> Action:
    if not options:
        return Action(name="noop")

    def reset_active() -> None:
        s.active_option_id = -1
        s.active_option_ticks = 0

    option_count = len(options)
    if 0 <= s.active_option_id < option_count:
        active_idx = s.active_option_id
        active = options[active_idx]
        if active.interruptible:
            for idx in range(active_idx):
                if options[idx].can_start(s):
                    s.active_option_id = idx
                    s.active_option_ticks = 0
                    active_idx = idx
                    active = options[idx]
                    break
        s.active_option_ticks += 1
        action = active.act(s)
        if active.should_terminate(s):
            reset_active()
        return action

    for idx, opt in enumerate(options):
        if not opt.can_start(s):
            continue
        s.active_option_id = idx
        s.active_option_ticks = 1
        action = opt.act(s)
        if opt.should_terminate(s):
            reset_active()
        return action

    return Action(name="noop")
