"""In-process round-trip test for every ``cogsguard`` leaf that ships the
shared ``coworld.player.v1`` JSON bridge.

The bridge transport itself (websockets) is bypassed. We drive
``CoworldJsonBridge.configure`` and ``action_for_observation`` directly with
the exact message schemas the cogs_vs_clips engine sends, then feed each
returned action back into a live ``Simulation`` so the bridge sees the
sequence of observations a real episode would produce. A passing test for a
leaf proves:

* its discovery package registers the expected short_name,
* ``policy_spec_from_uri`` resolves it,
* ``initialize_or_load_policy`` constructs the policy against a real env,
* observation triplet decoding consumes real wire-format observations,
* ``agent_policy.step()`` returns a well-formed action across a multi-step
  interaction (not just at step 0, which several scripted policies cannot
  serve until they have observed the hub).

It does **not** prove websocket framing, engine acceptance of the action
envelope, or anything about ``among_them`` (different bridge / protocol).
"""

from __future__ import annotations

from mettagrid.policy.loader import discover_and_register_policies
from mettagrid.simulator import Action

from players.player_sdk.coworld_json_bridge import CoworldJsonBridge

# How long to drive the bridge before we require at least one successful
# action envelope. Scripted policies need a brief warmup (steps until the
# hub becomes visible) before ``policy.step`` succeeds; 30 ticks comfortably
# covers every leaf currently in ``PLAYERS``.
WARMUP_TICKS = 30


def test_bridge_roundtrip(
    cogsguard_player,
    cogsguard_policy_env,
    cogsguard_player_config,
    cogsguard_sim,
    observation_message_for,
) -> None:
    discover_and_register_policies(cogsguard_player.discovery_package)
    bridge = CoworldJsonBridge(
        policy_uri=f"metta://policy/{cogsguard_player.default_short_name}",
        device="cpu",
    )
    bridge.configure(cogsguard_player_config)

    # Policies may emit any action in the full vocabulary, including
    # vibe-only variants (``change_vibe_heart`` etc.), which the engine
    # exposes via ``policy_env.all_action_names`` rather than the primary
    # ``action_names`` list on the ``player_config`` envelope.
    valid_action_names: set[str] = set(cogsguard_policy_env.all_action_names)
    num_agents = cogsguard_sim.num_agents
    last_bridge_action: dict[str, object] | None = None

    for tick in range(WARMUP_TICKS):
        # Bridge speaks for slot 0; the other agents act with noop so the
        # simulation can advance enough for slot 0 to observe the hub.
        slot_observation = cogsguard_sim.observations()[0]
        try:
            envelope = bridge.action_for_observation(
                observation_message_for(slot_observation, tick)
            )
        except RuntimeError:
            # Scripted policy not yet ready (e.g. heart recipe undiscovered);
            # fall back to noop and let the sim deliver fresh observations.
            envelope = None

        if envelope is not None:
            last_bridge_action = envelope
            assert envelope["type"] == "action"
            assert envelope["action_name"] in valid_action_names
            assert isinstance(envelope["policy_infos"], dict)
            assert envelope["request_id"] == f"step-{tick}"

        slot_action_name = (
            envelope["action_name"] if envelope is not None else "noop"
        )
        cogsguard_sim.agent(0).set_action(Action(name=slot_action_name))
        for other in range(1, num_agents):
            cogsguard_sim.agent(other).set_action(Action(name="noop"))
        cogsguard_sim.step()

    assert last_bridge_action is not None, (
        f"{cogsguard_player.leaf}: bridge produced no successful action "
        f"envelope within {WARMUP_TICKS} ticks"
    )
