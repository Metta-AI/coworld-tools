FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BE_DUMB=1 \
    CREWBORG_LLM_MEETINGS=0 \
    CREWBORG_LLM_SYSTEM_PROMPT_PATH=/srv/players/players/crewrift/richardborg/memory/system.md

WORKDIR /srv/players

COPY pyproject.toml README.md ./
COPY players ./players
RUN pip install --upgrade pip \
 && pip install -e .

ENTRYPOINT ["/srv/players/players/crewrift/richardborg/coworld/entrypoint.sh"]
