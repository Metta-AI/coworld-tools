# Build context: the `reporters/` directory. See build.sh.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY reporter_sdk/ /app/reporter_sdk/
RUN pip install /app/reporter_sdk

COPY episode_analysis/ /app/episode_analysis/
RUN pip install "/app/episode_analysis[charts]"

COPY mettagrid/mettagrid_replay_atlas/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY mettagrid/mettagrid_replay_atlas/mettagrid_replay_atlas.py /app/mettagrid_replay_atlas.py

ENTRYPOINT ["python", "/app/mettagrid_replay_atlas.py"]
