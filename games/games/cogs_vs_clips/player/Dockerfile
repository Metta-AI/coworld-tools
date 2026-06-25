ARG PLAYER_RUNTIME_PLATFORM=linux/amd64
FROM --platform=${PLAYER_RUNTIME_PLATFORM} python:3.12-slim

RUN pip install --no-cache-dir \
    pydantic \
    websockets

WORKDIR /app
COPY games/cogs_vs_clips/player/policy_player.py /app/coworld_reference_player.py

CMD ["python", "/app/coworld_reference_player.py"]
