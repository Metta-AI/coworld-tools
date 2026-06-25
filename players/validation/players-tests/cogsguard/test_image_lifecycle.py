"""Docker image-level lifecycle contract for ``cogsguard`` player images.

For every leaf in ``PLAYERS`` we run the built image against a fake Coworld
engine (a ``websockets.serve`` server) and assert the container:

1. Connects to the engine websocket URL (proves Dockerfile, env wiring, and
   the entrypoint actually invoke the bridge).
2. Accepts a real ``player_config`` envelope. The bridge's ``configure()`` runs
   pydantic validation, walks ``COGAMES_POLICY_DISCOVERY_PACKAGES``, resolves
   ``COGAMES_POLICY_URI`` via mettagrid's resolver, and constructs the policy.
   Any image whose URI or discovery wiring is wrong fails here.
3. Exits cleanly when it receives ``final``.

We deliberately do **not** drive the observation\u2192action loop here. The
baseline-family cogsguard policies currently crash in-process under
mettagrid 0.2.0.58 at recipe-discovery time (see
``docs/findings/baseline-policy-recipe-discovery.md``); driving them through
real observations is a policy-correctness question that the image-contract
test should not gate on. The lifecycle this test exercises is a strict
superset of what the previous in-process bridge test covered for the
configure path, plus the Dockerfile/entrypoint/env stack the in-process test
never touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import socket
import subprocess
import uuid

import pytest
import pytest_asyncio
import websockets

DOCKER = shutil.which("docker")
CONNECT_TIMEOUT_SECONDS = 90.0
CONFIGURE_TIMEOUT_SECONDS = 60.0
CONTAINER_EXIT_TIMEOUT_SECONDS = 30.0


pytestmark = [
    pytest.mark.skipif(DOCKER is None, reason="docker binary not on PATH"),
    pytest.mark.asyncio,
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return sock.getsockname()[1]


async def _wait_for_connection_or_proc_exit(
    connected: asyncio.Event, proc: subprocess.Popen
) -> None:
    """Wait for the container to connect; fail fast if it exits first."""
    loop = asyncio.get_event_loop()
    connect_task = asyncio.ensure_future(connected.wait())
    proc_task = loop.run_in_executor(None, proc.wait)
    done, _ = await asyncio.wait(
        {connect_task, proc_task},
        timeout=CONNECT_TIMEOUT_SECONDS,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if not done:
        connect_task.cancel()
        proc_task.cancel()
        raise TimeoutError(
            f"container did not connect within {CONNECT_TIMEOUT_SECONDS}s"
        )
    if proc_task in done and not connected.is_set():
        logs = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
        raise AssertionError(
            f"container exited before connecting (rc={proc.returncode}):\n{logs}"
        )
    proc_task.cancel()


def _dump_container_logs(container_name: str) -> None:
    """Print whatever the container has emitted so the failure mode is visible."""
    logs = subprocess.run(
        [DOCKER, "logs", container_name],
        capture_output=True,
        check=False,
    )
    print("\n--- container stdout/stderr (docker logs) ---")
    print(logs.stdout.decode("utf-8", errors="replace"))
    if logs.stderr:
        print(logs.stderr.decode("utf-8", errors="replace"))
    print("--- end container logs ---\n")


def _image_present(tag: str) -> bool:
    return (
        subprocess.run(
            [DOCKER, "image", "inspect", tag],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


@pytest_asyncio.fixture
async def fake_engine():
    """Spin up a fake Coworld engine on a free port; yield ``(port, state)``."""
    state: dict[str, object] = {"connected": asyncio.Event(), "error": None}

    async def handler(websocket):
        state["websocket"] = websocket
        state["connected"].set()
        try:
            await websocket.wait_closed()
        except Exception as exc:  # pragma: no cover - surfaced via state
            state["error"] = exc

    port = _free_port()
    server = await websockets.serve(handler, "0.0.0.0", port)
    try:
        yield port, state
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.docker
async def test_image_completes_configure_lifecycle(
    cogsguard_player,
    cogsguard_player_config,
    fake_engine,
):
    """Each cogsguard image must connect, accept player_config, and exit on final."""
    if not _image_present(cogsguard_player.image_tag):
        pytest.skip(f"image {cogsguard_player.image_tag} not built (run build.sh)")

    port, state = fake_engine
    container_name = f"cogsguard-contract-{cogsguard_player.leaf}-{uuid.uuid4().hex[:8]}"
    docker_run = [
        DOCKER, "run", "--rm",
        "--name", container_name,
        "--add-host=host.docker.internal:host-gateway",
        "-e", f"COGAMES_ENGINE_WS_URL=ws://host.docker.internal:{port}/",
        cogsguard_player.image_tag,
    ]
    proc = subprocess.Popen(docker_run, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        await _wait_for_connection_or_proc_exit(state["connected"], proc)
        websocket = state["websocket"]
        try:
            await asyncio.wait_for(
                websocket.send(json.dumps(cogsguard_player_config)),
                timeout=CONFIGURE_TIMEOUT_SECONDS,
            )
            await asyncio.wait_for(
                websocket.send(json.dumps({"type": "final"})),
                timeout=CONFIGURE_TIMEOUT_SECONDS,
            )
        except Exception:
            _dump_container_logs(container_name)
            raise
        await websocket.close()
        try:
            exit_code = await asyncio.get_event_loop().run_in_executor(
                None, lambda: proc.wait(timeout=CONTAINER_EXIT_TIMEOUT_SECONDS)
            )
        except subprocess.TimeoutExpired:
            _dump_container_logs(container_name)
            pytest.fail(
                f"container did not exit within {CONTAINER_EXIT_TIMEOUT_SECONDS}s "
                "of receiving final"
            )
        if exit_code != 0:
            _dump_container_logs(container_name)
            pytest.fail(f"container exited with code {exit_code}")
    finally:
        if proc.poll() is None:
            with contextlib.suppress(Exception):
                subprocess.run([DOCKER, "kill", container_name], capture_output=True, check=False)
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
