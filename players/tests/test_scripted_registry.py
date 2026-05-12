from __future__ import annotations

import pytest
from cogames_agents.policy.scripted_registry import list_scripted_agent_names, resolve_scripted_agent_uri

from mettagrid.policy.loader import resolve_policy_class_path


def test_resolve_scripted_agent_uri_known() -> None:
    names = set(list_scripted_agent_names())
    expected = {
        "alignall",
        "baseline",
        "cogsguard_control",
        "cogsguard_targeted",
        "cogsguard_v2",
        "nim_random",
        "race_car",
        "role",
        "role_nim",
        "teacher",
        "thinky",
        "tiny_baseline",
        "wombo",
    }
    assert expected.issubset(names)
    for name in expected:
        assert resolve_scripted_agent_uri(name) == f"metta://policy/{name}"


def test_resolve_scripted_agent_uri_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown scripted agent"):
        resolve_scripted_agent_uri("not-a-real-agent")


def test_role_aliases_resolve_to_expected_policy_classes() -> None:
    assert resolve_policy_class_path("role").endswith("CogsguardPolicy")
    assert resolve_policy_class_path("role_nim").endswith("CogsguardAgentsMultiPolicy")
