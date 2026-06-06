#!/usr/bin/env bash
# Richardborg container entrypoint: launch the Sprite-v1 websocket bridge.
# Reads COGAMES_ENGINE_WS_URL (filled in by the Coworld runner).
set -euo pipefail

exec python -m players.crewrift.richardborg.coworld.policy_player
