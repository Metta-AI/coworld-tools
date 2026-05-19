# CogsGuard Nim-bindings player image.
#
# Builds the Nim FFI bindings (``cogsguard_agents``, ``thinky_agents``,
# ``random_agents``, ``nlanky``, ``racecar`` and friends) at image-build time
# via ``players.cogsguard.nim.build.build_nim``, then hosts the resulting
# NimMultiAgentPolicy inside ``players.player_sdk.coworld_json_bridge``.
#
# The default policy is ``metta://policy/thinky``; override via the manifest's
# ``env.COGAMES_POLICY_URI`` to deploy any of the other registered
# short_names (nim_random, race_car, role_nim, alignall, nlanky).

FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    COGAMES_POLICY_URI=metta://policy/thinky

# build-essential: nim c emits C and shells out to gcc.
# ca-certificates: nimby + manual nimby.lock sync use HTTPS to fetch packages.
RUN apt-get update \
 && apt-get install --no-install-recommends -y build-essential ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/players

COPY pyproject.toml README.md ./
COPY players ./players
RUN pip install --upgrade pip \
 && pip install -e ".[cogames]"

# Compile the Nim bindings now so the runtime container starts fast and so
# any toolchain failure surfaces during ``docker build`` rather than the
# first episode tick.
RUN python -m players.cogsguard.nim.build

CMD ["python", "-m", "players.player_sdk.coworld_json_bridge"]
