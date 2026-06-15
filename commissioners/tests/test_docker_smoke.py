from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from commissioners.common.protocol import DivisionInfo, LeagueInfo, MembershipInfo, RoundStart, VariantInfo


IMAGES = [
    (
        "commissioners-smoke-default",
        "config_driven",
        "default",
        2,
        2,
    ),
    (
        "commissioners-smoke-among-them",
        "config_driven",
        "among_them",
        8,
        8,
    ),
    (
        "commissioners-smoke-cogs-vs-clips",
        "config_driven",
        "cogs_vs_clips",
        8,
        8,
    ),
    (
        "commissioners-smoke-four-score",
        "config_driven",
        "four_score",
        4,
        32,
    ),
    (
        "commissioners-smoke-cue-n-woo",
        "config_driven",
        "cue_n_woo",
        4,
        2,
    ),
    (
        "commissioners-smoke-proxywar",
        "config_driven",
        "proxywar",
        4,
        4,
    ),
    (
        "commissioners-smoke-ruleset-strategy",
        "config_driven",
        "default",
        2,
        2,
    ),
]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _round_start_json(*, policy_count: int, num_agents: int) -> str:
    division_id = uuid4()
    league_id = uuid4()
    policy_version_ids = [uuid4() for _ in range(policy_count)]
    return json.dumps(
        RoundStart(
            round_id=uuid4(),
            round_number=1,
            league=LeagueInfo(id=league_id, commissioner_config={"num_episodes": 1}),
            divisions=[DivisionInfo(id=division_id, name="Dirt", level=0)],
            memberships=[
                MembershipInfo(
                    id=uuid4(),
                    league_id=league_id,
                    division_id=division_id,
                    policy_version_id=policy_version_id,
                    status="competing",
                    substatus="champion",
                    is_champion=True,
                )
                for policy_version_id in policy_version_ids
            ],
            recent_results=[],
            variants=[
                VariantInfo(
                    id="default",
                    name="Default",
                    game_config={"num_agents": num_agents},
                    num_agents=num_agents,
                )
            ],
        ).to_json()
    )


@pytest.mark.parametrize(
    ("image_name", "commissioner_key", "config_name", "policy_count", "num_agents"),
    IMAGES,
)
def test_commissioner_container_healthz_and_round_websocket(
    image_name: str,
    commissioner_key: str,
    config_name: str,
    policy_count: int,
    num_agents: int,
) -> None:
    if not _docker_available():
        pytest.skip("Docker daemon is not available")
    websockets_sync = pytest.importorskip("websockets.sync.client")

    repo_root = Path(__file__).resolve().parents[1]
    tag = f"{image_name}:test"
    subprocess.run(
        [
            "docker",
            "build",
            "-f",
            "commissioners/Dockerfile",
            "--build-arg",
            f"COMMISSIONER_KEY={commissioner_key}",
            "--build-arg",
            f"RULESET_STRATEGY_CONFIG_NAME={config_name}",
            "-t",
            tag,
            ".",
        ],
        cwd=repo_root,
        check=True,
    )
    container_id = subprocess.check_output(
        ["docker", "run", "-d", "-p", "127.0.0.1::8080", tag],
        cwd=repo_root,
        text=True,
    ).strip()

    try:
        port_output = subprocess.check_output(["docker", "port", container_id, "8080/tcp"], text=True).strip()
        host, port = port_output.rsplit(":", 1)
        health_url = f"http://{host}:{port}/healthz"
        for _ in range(60):
            try:
                with urllib.request.urlopen(health_url, timeout=1) as response:
                    assert response.status == 200
                    break
            except OSError:
                time.sleep(0.25)
        else:
            pytest.fail("container did not become healthy")

        with websockets_sync.connect(f"ws://{host}:{port}/round") as websocket:
            websocket.send(_round_start_json(policy_count=policy_count, num_agents=num_agents))
            schedule = json.loads(websocket.recv())
        assert schedule["type"] == "schedule_episodes"
        assert schedule["episodes"]
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
