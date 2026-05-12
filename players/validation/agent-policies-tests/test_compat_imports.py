"""Compatibility coverage for historical import names."""

from __future__ import annotations


def test_cogames_agents_scripted_registry_shim() -> None:
    from cogames_agents.policy.scripted_registry import list_scripted_agent_names

    assert "starter" in list_scripted_agent_names()


def test_framework_shim_points_to_cyborg_evolution() -> None:
    import framework

    assert framework.__name__ == "agent_policies.frameworks.cyborg_evolution"
