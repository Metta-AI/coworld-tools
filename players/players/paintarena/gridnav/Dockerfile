# Paint Arena gridnav demo player image.
#
# Demonstrates the shared player_sdk libraries (nav_grid + worldmodel) on the
# simplest real coworld protocol. Build context is the repo root so the
# `players.paintarena.gridnav` and `players.player_sdk` packages import
# cleanly (same pattern as players/paintarena/default).
#
# Build:   docker build -f players/paintarena/gridnav/Dockerfile -t paintarena-gridnav:dev .
# Upload:  coworld upload-policy paintarena-gridnav:dev --name paintarena-gridnav \
#            --run python --run -m --run players.paintarena.gridnav.agent

FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv

WORKDIR /srv

RUN pip install --upgrade pip \
 && pip install "websockets>=16.0" "pydantic>=2.12.2"

# The whole SDK tree: importing players.player_sdk.nav_grid executes the
# package __init__, which re-exports the (grid-free) SDK core.
COPY players/__init__.py players/__init__.py
COPY players/player_sdk players/player_sdk
COPY players/paintarena/__init__.py players/paintarena/__init__.py
COPY players/paintarena/gridnav players/paintarena/gridnav

CMD ["python", "-m", "players.paintarena.gridnav.agent"]
