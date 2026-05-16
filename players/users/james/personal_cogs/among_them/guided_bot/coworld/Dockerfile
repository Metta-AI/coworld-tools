FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY guided_bot /app/among_them/guided_bot
COPY common /app/among_them/common
COPY guided_bot/coworld/amongthem_policy.py /app/amongthem_policy.py
COPY guided_bot/coworld/policy_player.py /app/policy_player.py

RUN python /app/among_them/guided_bot/build_guided_bot.py \
    && rm -rf /app/among_them/guided_bot/nimcache

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV GUIDED_BOT_TRACE_DIR=stderr
ENV GUIDED_BOT_TRACE_LEVEL=full
# Keep the LLM available for meetings, but keep gameplay mode control on the
# symbolic path (defaultDirectiveFor + reflexes + mode handlers).
ENV GUIDED_BOT_LLM_DISABLE=0
ENV GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
    "mettagrid==0.26.17" \
    "websockets==16.0"

WORKDIR /app

COPY --from=builder /app /app

RUN python -c "from pathlib import Path; p = Path('/app/among_them/guided_bot/libguidedbot.so'); p.touch(); p.with_name(p.name + '.abi').touch()"
RUN printf '%s\n' '#!/bin/sh' 'exec python /app/policy_player.py "$@"' > /bin/guided_bot \
    && chmod +x /bin/guided_bot

CMD ["/bin/guided_bot"]
