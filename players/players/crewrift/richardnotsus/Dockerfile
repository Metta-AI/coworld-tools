# RichardNotsus player image.
#
# Notsus is a Nim player that imports the canonical Crewrift game modules. The
# players repo carries only the player source; the image build checks out the
# game repo at a pinned ref, overlays this player, and compiles the binary.

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

COPY players/crewrift/richardnotsus ./players/richardnotsus
RUN nim c \
      -d:release \
      -d:botHeadless \
      -d:useMalloc \
      --opt:speed \
      --stackTrace:on \
      --nimcache:/tmp/richardnotsus-nimcache \
      --out:richardnotsus \
      players/richardnotsus/richardnotsus.nim

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
COPY --from=build /workspace/crewrift/richardnotsus /bin/richardnotsus
COPY players/crewrift/richardnotsus/llm_meeting.py /srv/richardnotsus/llm_meeting.py
COPY players/crewrift/richardnotsus/memory /srv/richardnotsus/memory

ENV RICHARDNOTSUS_LLM_HELPER=/srv/richardnotsus/llm_meeting.py \
    RICHARDNOTSUS_LLM_SYSTEM_PROMPT_PATH=/srv/richardnotsus/memory/system.md \
    RICHARDNOTSUS_LLM_MEETINGS=1 \
    USE_BEDROCK=1 \
    AWS_REGION=us-west-2

CMD ["/bin/richardnotsus"]
