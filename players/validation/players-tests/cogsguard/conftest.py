"""Per-game test fixtures for the ``cogsguard`` (Cogs vs Clips) player suite.

Every player under ``players/cogsguard/`` ships into the same Coworld game
and therefore against the same engine-side message schemas. Tests in this
package consume the shared fixtures below and parametrize over
``PLAYERS``; adding a new cogsguard leaf only requires extending that list.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cogsguard.missions.machina_1 import make_machina1_mission
from mettagrid.policy.policy_env_interface import PolicyEnvInterface


@dataclass(frozen=True)
class CogsguardPlayer:
    """Registry entry for one leaf in ``players/cogsguard/``.

    ``image_tag`` matches the ``IMAGE_LOCAL_TAG`` produced by each leaf's
    ``build.sh``; the image-level contract tests rely on it.
    """

    leaf: str
    discovery_package: str
    default_short_name: str
    image_tag: str


PLAYERS: list[CogsguardPlayer] = [
    CogsguardPlayer("baseline", "players.cogsguard.baseline", "baseline", "players-cogsguard-baseline:dev"),
    CogsguardPlayer("tiny_baseline", "players.cogsguard.tiny_baseline", "tiny_baseline", "players-cogsguard-tiny-baseline:dev"),
    CogsguardPlayer("buggy", "players.cogsguard.buggy", "buggy", "players-cogsguard-buggy:dev"),
    CogsguardPlayer("cranky", "players.cogsguard.cranky", "cranky", "players-cogsguard-cranky:dev"),
    CogsguardPlayer("role", "players.cogsguard.role", "role", "players-cogsguard-role:dev"),
    CogsguardPlayer("nim", "players.cogsguard.nim", "thinky", "players-cogsguard-nim:dev"),
]


@pytest.fixture(params=PLAYERS, ids=lambda player: player.leaf)
def cogsguard_player(request) -> CogsguardPlayer:
    """Auto-parametrize tests over every leaf in ``players/cogsguard/``."""
    return request.param


@pytest.fixture(scope="module")
def cogsguard_env_cfg():
    """Build a real ``MettaGridConfig`` for the smallest cogsguard mission.

    machina_1 is sufficient to exercise the protocol: any policy registered
    for cogs_vs_clips must accept the standard ``PolicyEnvInterface`` derived
    from it.
    """
    mission = make_machina1_mission(num_agents=4, max_steps=50)
    return mission.make_env()


@pytest.fixture(scope="module")
def cogsguard_policy_env(cogsguard_env_cfg) -> PolicyEnvInterface:
    """Same factory the cogs_vs_clips engine uses for its ``player_config``."""
    return PolicyEnvInterface.from_mg_cfg(cogsguard_env_cfg)


@pytest.fixture(scope="module")
def cogsguard_player_config(cogsguard_policy_env) -> dict[str, object]:
    """Faithful ``player_config`` message — same schema the engine sends."""
    return {
        "type": "player_config",
        "protocol": "coworld.player.v1",
        "slot": 0,
        "connection_id": "validation-image-contract",
        "action_names": list(cogsguard_policy_env.action_names),
        "policy_env": cogsguard_policy_env.model_dump(),
    }
