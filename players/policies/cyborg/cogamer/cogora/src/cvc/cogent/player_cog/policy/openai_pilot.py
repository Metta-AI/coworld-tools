from __future__ import annotations

from typing import Any

from cvc.cogent.player_cog.policy.pilot_base import PilotAgentPolicy, PilotCyborgPolicy
from cvc.cogent.player_cog.runtime.openai_pilot import OpenAIPilotSession

__all__ = [
    "OpenAICyborgPolicy",
    "OpenAIPilotAgentPolicy",
    "OpenAIPilotSession",
]


class OpenAIPilotAgentPolicy(PilotAgentPolicy):
    pass


class OpenAICyborgPolicy(PilotCyborgPolicy):
    short_names = ["openai-cyborg", "gpt-cyborg", "cyborg-openai"]
    _session_class = OpenAIPilotSession
    _agent_policy_class = OpenAIPilotAgentPolicy

    def _provider_session_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            "api_key": kwargs.get("api_key"),
            "api_key_file": kwargs.get("api_key_file"),
            "openai_api_key": kwargs.get("openai_api_key"),
            "openai_api_key_file": kwargs.get("openai_api_key_file"),
        }
