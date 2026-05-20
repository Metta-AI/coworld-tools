"""Docker image-level lifecycle contract for ``among_them`` player images.

Both ``among_them`` players (``coborg`` Python bridge, ``starter`` Nim binary)
speak the BitWorld binary ``bitscreen_v1`` wire protocol. There is no JSON
``player_config`` handshake to assert against — the engine just opens a
websocket and starts streaming 8192-byte packed frames. Drive-by frame
fuzzing isn't valuable: each policy decodes frames in game-specific ways and
a synthetic blob would either be rejected as malformed (proving nothing) or
trigger arbitrary internal state.

What we *can* verify at the image-contract layer:

1. The container starts under the env it gets from the Coworld runner
   (``COGAMES_ENGINE_WS_URL`` + ``--add-host`` for host loopback).
2. The container actually connects to the engine's websocket — proves the
   Dockerfile, entrypoint, websocket client wiring, and any startup
   prerequisites are correct end-to-end.
3. When the engine closes the websocket, the container exits cleanly.

These three checks are the same lifecycle the cogsguard images get tested
against (minus the JSON ``player_config`` step that doesn't apply here).
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import socket
import subprocess
import uuid

import pytest
import pytest_asyncio
import websockets

DOCKER = shutil.which("docker")
CONNECT_TIMEOUT_SECONDS = 60.0
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
    """Spin up a fake BitWorld engine on a free port; yield ``(port, state)``."""
    state: dict[str, object] = {"connected": asyncio.Event()}

    async def handler(websocket):
        state["websocket"] = websocket
        state["connected"].set()
        try:
            await websocket.wait_closed()
        except Exception:  # pragma: no cover - engine just keeps the socket open
            pass

    port = _free_port()
    server = await websockets.serve(handler, "0.0.0.0", port)
    try:
        yield port, state
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.docker
async def test_image_connects_and_exits_cleanly(among_them_player, fake_engine):
    """Each among_them image must connect to the engine and exit cleanly on close."""
    if not _image_present(among_them_player.image_tag):
        pytest.skip(f"image {among_them_player.image_tag} not built (run build.sh)")

    port, state = fake_engine
    container_name = f"among-them-contract-{among_them_player.leaf}-{uuid.uuid4().hex[:8]}"
    docker_run = [
        DOCKER, "run", "--rm",
        "--name", container_name,
        "--add-host=host.docker.internal:host-gateway",
        "-e", f"COGAMES_ENGINE_WS_URL=ws://host.docker.internal:{port}/",
        among_them_player.image_tag,
    ]
    proc = subprocess.Popen(docker_run, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        try:
            await _wait_for_connection_or_proc_exit(state["connected"], proc)
        except Exception:
            _dump_container_logs(container_name)
            raise
        await state["websocket"].close()
        try:
            exit_code = await asyncio.get_event_loop().run_in_executor(
                None, lambda: proc.wait(timeout=CONTAINER_EXIT_TIMEOUT_SECONDS)
            )
        except subprocess.TimeoutExpired:
            _dump_container_logs(container_name)
            pytest.fail(
                f"container did not exit within {CONTAINER_EXIT_TIMEOUT_SECONDS}s "
                "of websocket close"
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
