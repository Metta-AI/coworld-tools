import sys

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="Nim agents bindings are not supported on Windows")
def test_nim_agents_import_and_init() -> None:
    from agent_policies.policies.scripted.cogsguard.nim_agents import agents  # noqa: PLC0415

    agents.na.nim_agents_init_chook()
