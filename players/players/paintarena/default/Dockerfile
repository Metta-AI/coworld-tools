# Paint Arena default policy player image.
#
# Self-contained Paint Arena player: a direct websocket client (Paint Arena uses
# its own JSON protocol, not the mettagrid/cogames token protocol, so it does
# NOT use players.player_sdk.coworld_json_bridge). Build context is the repo root
# so the `players.paintarena.default` package imports cleanly.
#
# Build:   docker build -f players/paintarena/default/Dockerfile -t paintarena-default:dev .
# Upload:  coworld upload-policy paintarena-default:dev --name paintarena-default \
#            --run python --run -m --run players.paintarena.default.agent

FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv

WORKDIR /srv

RUN pip install --upgrade pip \
 && pip install "websockets>=16.0" "pydantic>=2.12.2"

COPY players/__init__.py players/__init__.py
COPY players/paintarena/__init__.py players/paintarena/__init__.py
COPY players/paintarena/README.md players/paintarena/README.md
COPY players/paintarena/default players/paintarena/default

CMD ["python", "-m", "players.paintarena.default.agent"]
