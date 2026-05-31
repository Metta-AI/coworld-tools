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
        "commissioners/default/default_commissioner/Dockerfile",
    ),
    (
        "commissioners-smoke-among-them",
        "commissioners/among_them/among_them_commissioner/Dockerfile",
    ),
]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _round_start_json() -> str:
    division_id = uuid4()
    policy_version_ids = [uuid4(), uuid4()]
    return json.dumps(
        RoundStart(
            round_id=uuid4(),
            round_number=1,
            league=LeagueInfo(id=uuid4(), commissioner_config={"num_episodes": 1}),
            divisions=[DivisionInfo(id=division_id, name="Dirt", level=0)],
            memberships=[
                MembershipInfo(id=uuid4(), division_id=division_id, policy_version_id=policy_version_id)
                for policy_version_id in policy_version_ids
            ],
            recent_results=[],
            variants=[VariantInfo(id="default", name="Default", game_config={"num_agents": 2}, num_agents=2)],
        ).to_json()
    )


@pytest.mark.parametrize(("image_name", "dockerfile"), IMAGES)
def test_commissioner_container_healthz_and_round_websocket(image_name: str, dockerfile: str) -> None:
    if not _docker_available():
        pytest.skip("Docker daemon is not available")
    websockets_sync = pytest.importorskip("websockets.sync.client")

    repo_root = Path(__file__).resolve().parents[1]
    tag = f"{image_name}:test"
    subprocess.run(["docker", "build", "-f", dockerfile, "-t", tag, "."], cwd=repo_root, check=True)
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
            websocket.send(_round_start_json())
            schedule = json.loads(websocket.recv())
        assert schedule["type"] == "schedule_episodes"
        assert len(schedule["episodes"]) == 1
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
