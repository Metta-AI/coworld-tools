"""Websocket transport for the Paint Arena default policy.

Connects to the game runnable, feeds each observation to
``strategy.choose_move``, and returns the chosen move. At episode end it writes
an optional player artifact (per-tick decisions + summary) to
``COWORLD_PLAYER_ARTIFACT_UPLOAD_URL`` — the durable telemetry the optimizer
loop reconstructs from. The artifact upload is best-effort by contract (a
missing artifact never fails an episode; see coworld PLAYER.md), so it is the
one place we tolerate a network failure.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

import websockets

from players.paintarena.default.strategy import Observation, choose_move

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("paintarena.default")

POLICY_VERSION = "paintarena-default/1"


async def main() -> None:
    url = os.environ["COWORLD_PLAYER_WS_URL"]
    logger.info("connecting to %s (policy=%s)", url, POLICY_VERSION)
    decisions: list[dict[str, Any]] = []
    last_scores: list[int] = []
    slot = -1

    async with websockets.connect(url) as websocket:
        async for raw_message in websocket:
            message = cast(dict[str, Any], json.loads(raw_message))
            kind = message["type"]
            if kind == "final":
                last_scores = message["scores"]
                logger.info("episode finished: scores=%s slot=%s", last_scores, slot)
                break
            if kind != "observation":
                continue
            slot = message["slot"]
            obs = Observation.model_validate(message)
            move = choose_move(obs, slot)
            decisions.append(
                {
                    "tick": obs.tick,
                    "slot": slot,
                    "position": obs.positions[slot],
                    "move": move,
                    "scores": message["scores"],
                }
            )
            await websocket.send(json.dumps({"move": move}))

    _upload_artifact(slot, decisions, last_scores)


def _upload_artifact(slot: int, decisions: list[dict[str, Any]], scores: list[int]) -> None:
    upload_url = os.environ.get("COWORLD_PLAYER_ARTIFACT_UPLOAD_URL")
    if not upload_url:
        return
    metadata = {
        "policy_version": POLICY_VERSION,
        "slot": slot,
        "final_scores": scores,
        "ticks": len(decisions),
        "my_score": scores[slot] if scores and 0 <= slot < len(scores) else None,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(metadata, indent=2))
        archive.writestr("decisions.jsonl", "\n".join(json.dumps(d) for d in decisions))
    payload = buffer.getvalue()

    # The runner hands us either a local file:// URL (local parity) or a hosted
    # presigned http(s):// PUT URL — handle both, per coworld PLAYER_ARTIFACT.md.
    try:
        if upload_url.startswith("file://"):
            destination = Path(upload_url.removeprefix("file://"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        else:
            request = Request(upload_url, data=payload, method="PUT")
            request.add_header("Content-Type", "application/zip")
            with urlopen(request, timeout=30):
                pass
        logger.info("uploaded artifact (%d bytes) -> %s", len(payload), upload_url)
    except Exception as exc:  # best-effort: a lost artifact must not fail the episode
        logger.warning("artifact upload failed: %s", exc)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
