FROM docker.io/library/python:3.12-slim

ARG NIMBY_VERSION=0.1.26
ARG NIM_VERSION=2.2.6

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential ca-certificates curl git && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/local/bin /root/.nimby/nim/bin && \
    arch="$(uname -m)" && \
    if [ "$arch" = "aarch64" ]; then nimby_arch="Arm64"; else nimby_arch="X64"; fi && \
    curl -fsSL "https://github.com/treeform/nimby/releases/download/${NIMBY_VERSION}/nimby-Linux-${nimby_arch}" \
      -o /usr/local/bin/nimby && \
    chmod +x /usr/local/bin/nimby && \
    nimby use "${NIM_VERSION}" && \
    chmod +x /root/.nimby/nim/bin/*

ENV PATH="/root/.nimby/nim/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app
RUN nimby sync -g nimby.lock && \
    pip install --no-cache-dir ".[test]"

CMD ["python", "-m", "tribal_village_env.coworld.server"]
