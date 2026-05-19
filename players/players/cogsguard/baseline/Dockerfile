# CogsGuard Baseline player image.
#
# Built via this leaf's ``build.sh``. The build context is the repo root so the
# image can install the local ``players`` package (which brings in mettagrid and
# the Coworld JSON bridge that hosts the policy).

FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    COGAMES_POLICY_URI=metta://policy/baseline

WORKDIR /srv/players

COPY pyproject.toml README.md ./
COPY players ./players
RUN pip install --upgrade pip \
 && pip install -e ".[cogames]"

CMD ["python", "-m", "players.player_sdk.coworld_json_bridge"]
