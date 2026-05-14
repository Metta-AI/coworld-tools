"""Adapter for mettagrid's ``AgentPolicy`` interface (P0 stub).

P0 ships a placeholder so the public API surface matches PLAN §4. The
adapter is not exercised by the Coworld smoke path — that uses
``coworld/policy_player.py`` directly. P2+ will fill this in if/when the
mettagrid evaluation harness needs to run the coborg runtime in-process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_policies.policies.cyborg.bitworld.coborg_among_them import build_runtime

if TYPE_CHECKING:  # pragma: no cover — adapter is a P2+ concern
    from mettagrid.policy.policy import AgentPolicy
else:  # pragma: no cover — runtime fallback when mettagrid is absent
    AgentPolicy = object  # type: ignore[assignment,misc]


class AmongThemCoborgPolicy(AgentPolicy):
    """Minimal mettagrid wrapper. Returns the noop action index for now."""

    def __init__(self, policy_env: Any | None = None) -> None:
        self._policy_env = policy_env
        self._runtime = build_runtime()

    def close(self) -> None:
        self._runtime.close()
