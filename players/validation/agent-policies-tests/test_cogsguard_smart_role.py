from __future__ import annotations

from policies.scripted.cogsguard.scripted_agent.cogsguard.policy import (
    SmartRoleAgentSnapshot,
    SmartRoleCoordinator,
)
from policies.scripted.cogsguard.scripted_agent.cogsguard.types import Role


def _snapshot(*, step: int, role: Role) -> SmartRoleAgentSnapshot:
    return SmartRoleAgentSnapshot(
        step=step,
        role=role,
        has_gear=True,
        structures_known=("hub", "junction"),
        structures_seen=20,
        heart_count=1,
        influence_count=1,
        junction_alignment_counts={"c": 1, "clips": 0, "neutral": 0, "unknown": 0},
    )


def test_smart_role_periodic_reassessment_uses_stochastic_choice(monkeypatch) -> None:
    coordinator = SmartRoleCoordinator(num_agents=4)
    coordinator.agent_snapshots = {
        0: _snapshot(step=25, role=Role.MINER),
        1: _snapshot(step=25, role=Role.SCOUT),
        2: _snapshot(step=25, role=Role.ALIGNER),
        3: _snapshot(step=25, role=Role.SCRAMBLER),
    }

    class _Rng:
        def random(self) -> float:
            return 0.0

        def choice(self, _values):
            return "aligner"

    monkeypatch.setattr(coordinator, "_rng_for_agent", lambda _agent_id: _Rng())

    assert coordinator.choose_role(0) == "aligner"


def test_smart_role_no_periodic_reassessment_outside_interval() -> None:
    coordinator = SmartRoleCoordinator(num_agents=4)
    coordinator.agent_snapshots = {
        0: _snapshot(step=24, role=Role.MINER),
        1: _snapshot(step=24, role=Role.SCOUT),
        2: _snapshot(step=24, role=Role.ALIGNER),
        3: _snapshot(step=24, role=Role.SCRAMBLER),
    }

    assert coordinator.choose_role(0) == "miner"
