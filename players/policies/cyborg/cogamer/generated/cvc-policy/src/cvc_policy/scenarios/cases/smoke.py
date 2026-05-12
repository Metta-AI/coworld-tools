"""S0 smoke_machina1_runs — tier 0 smoke test.

Runs a tiny machina_1 episode and asserts no crash plus at least one
action event per agent. This is the minimum signal that the harness
and policy are both wired correctly.
"""

from __future__ import annotations

from cvc_policy.scenarios import Scenario, scenario
from cvc_policy.scenarios.assertions import has_action_event_per_agent, no_crash


@scenario
def smoke_machina1_runs() -> Scenario:
    cogs = 2
    return Scenario(
        name="smoke_machina1_runs",
        tier=0,
        mission="machina_1",
        cogs=cogs,
        steps=30,
        seed=42,
        assertions=[no_crash(), has_action_event_per_agent(cogs)],
    )
