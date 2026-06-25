# Suspectra player image.
#
# Suspectra imports the canonical Crewrift game modules. The players repo
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

COPY players/crewrift/suspectra ./players/suspectra
RUN nim c \
      -d:release \
      -d:botHeadless \
      -d:useMalloc \
      --opt:speed \
      --stackTrace:on \
      --nimcache:/tmp/suspectra-nimcache \
      --out:suspectra \
      players/suspectra/suspectra.nim

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
COPY --from=build /workspace/crewrift/suspectra /bin/suspectra
COPY players/crewrift/suspectra/llm_meeting.py /srv/suspectra/llm_meeting.py
COPY players/crewrift/suspectra/memory /srv/suspectra/memory

ENV SUSPECTRA_LLM_HELPER=/srv/suspectra/llm_meeting.py \
    SUSPECTRA_LLM_SYSTEM_PROMPT_PATH=/srv/suspectra/memory/system.md \
    SUSPECTRA_LLM_MEETINGS=1 \
    SUSPECTRA_LLM_PROCESS_TIMEOUT_SECONDS=6 \
    SUSPECTRA_LLM_TIMEOUT_SECONDS=5 \
    SUSPECTRA_LLM_MAX_TOKENS=160 \
    SUSPECTRA_LLM_TEMPERATURE=0 \
    SUSPECTRA_LLM_MIN_SUBMIT_CONFIDENCE=0.75 \
    AWS_REGION=us-west-2

CMD ["/bin/suspectra"]
