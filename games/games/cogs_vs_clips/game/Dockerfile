ARG GAME_RUNTIME_PLATFORM=linux/amd64
FROM --platform=${GAME_RUNTIME_PLATFORM} python:3.12-slim

RUN pip install --no-cache-dir \
    coworld \
    fastapi==0.115.5 \
    uvicorn[standard]==0.34.2

COPY games/cogsguard /tmp/cogsguard
RUN pip install --no-cache-dir /tmp/cogsguard && rm -rf /tmp/cogsguard

WORKDIR /app
COPY games/cogs_vs_clips/game/client /app/client
COPY games/cogs_vs_clips/game/server.py /app/server.py

CMD ["python", "/app/server.py"]
