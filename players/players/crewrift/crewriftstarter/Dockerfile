# CrewriftStarter player image.
#
# CrewriftStarter imports the canonical Crewrift game modules. The players repo
# carries only the player source; the image build checks out the game repo at a
# pinned ref, overlays this player, and compiles the binary.

FROM debian:bookworm-slim AS build

ARG CREWRIFT_REF=f43fc318adfd0953d892fb8adcafd801418ed587

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      curl \
      git \
 && rm -rf /var/lib/apt/lists/*

RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
      curl -fsSL -o /usr/local/bin/nimby \
        https://github.com/treeform/nimby/releases/download/0.1.26/nimby-Linux-X64; \
    elif [ "$(dpkg --print-architecture)" = "arm64" ]; then \
      curl -fsSL -o /usr/local/bin/nimby \
        https://github.com/treeform/nimby/releases/download/0.1.26/nimby-Linux-ARM64; \
    else \
      echo "unsupported arch: $(dpkg --print-architecture)" && exit 1; \
    fi \
 && chmod +x /usr/local/bin/nimby \
 && nimby use 2.2.4

ENV PATH="/root/.nimby/nim/bin:$PATH"

WORKDIR /workspace/crewrift
RUN git clone https://github.com/Metta-AI/coworld-crewrift.git . \
 && git checkout "$CREWRIFT_REF"

RUN nimby --global sync nimby.lock

COPY players/crewrift/crewriftstarter ./players/crewriftstarter
RUN nim c \
      -d:release \
      -d:botHeadless \
      -d:useMalloc \
      --opt:speed \
      --stackTrace:on \
      --nimcache:/tmp/crewriftstarter-nimcache \
      --out:crewriftstarter \
      players/crewriftstarter/crewriftstarter.nim

FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      coreutils \
      libcurl4 \
      python3 \
      python3-pip \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages --no-cache-dir \
      "anthropic>=0.40.0" \
      "boto3>=1.34.0"

WORKDIR /workspace/crewrift
COPY --from=build /workspace/crewrift/crewriftstarter /bin/crewriftstarter
COPY players/crewrift/crewriftstarter/llm_meeting.py /srv/crewriftstarter/llm_meeting.py
COPY players/crewrift/crewriftstarter/memory /srv/crewriftstarter/memory

ENV CREWRIFTSTARTER_LLM_HELPER=/srv/crewriftstarter/llm_meeting.py \
    CREWRIFTSTARTER_LLM_SYSTEM_PROMPT_PATH=/srv/crewriftstarter/memory/system.md \
    CREWRIFTSTARTER_LLM_MEETINGS=1 \
    CREWRIFTSTARTER_LLM_PROCESS_TIMEOUT_SECONDS=6 \
    CREWRIFTSTARTER_LLM_TIMEOUT_SECONDS=5 \
    CREWRIFTSTARTER_LLM_MAX_TOKENS=160 \
    CREWRIFTSTARTER_LLM_TEMPERATURE=0 \
    CREWRIFTSTARTER_LLM_MIN_SUBMIT_CONFIDENCE=0.75 \
    AWS_REGION=us-west-2

CMD ["/bin/crewriftstarter"]
