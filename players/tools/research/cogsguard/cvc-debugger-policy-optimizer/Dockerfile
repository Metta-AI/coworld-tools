FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    git-lfs \
    ca-certificates \
    unzip \
    jq \
    bc \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI v2
RUN set -eux; \
  arch="$(uname -m)"; \
  case "$arch" in \
    x86_64) aws_arch="x86_64" ;; \
    aarch64|arm64) aws_arch="aarch64" ;; \
    *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
  esac; \
  tmpdir="$(mktemp -d)"; \
  curl -sS "https://awscli.amazonaws.com/awscli-exe-linux-${aws_arch}.zip" -o "${tmpdir}/awscliv2.zip"; \
  unzip -q "${tmpdir}/awscliv2.zip" -d "${tmpdir}"; \
  "${tmpdir}/aws/install" --bin-dir /usr/local/bin --install-dir /usr/local/aws-cli --update; \
  rm -rf "${tmpdir}"

# Install OpenCode CLI
RUN curl -fsSL https://opencode.ai/install | bash

# Python deps for cogames simulation
RUN pip install --no-cache-dir \
    cogames \
    mettagrid \
    pufferlib-core \
    boto3 \
    python-dotenv \
    fastapi \
    uvicorn

WORKDIR /app

COPY eval_harness.py .
COPY optimize.sh .
COPY AGENT_INSTRUCTIONS.md .
COPY opencode.json .

RUN chmod +x optimize.sh

# Snapshots and results dirs
RUN mkdir -p /app/snapshots /app/results

# Git config for the commits
RUN git config --global user.email "aaronlan95@gmail.com" && \
    git config --global user.name "Aaron Landy Agent Optimizer"

ENTRYPOINT ["/bin/bash", "-c"]
CMD ["./optimize.sh"]
