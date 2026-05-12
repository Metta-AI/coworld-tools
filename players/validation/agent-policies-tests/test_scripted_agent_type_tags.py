from __future__ import annotations

from agent_policies.policies.scripted.cogsguard.scripted_agent.utils import has_type_tag


def test_has_type_tag_ignores_non_type_tags() -> None:
    tags = ["team:cogs", "junction"]

    assert has_type_tag(tags, ("junction",)) is False
