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
    nimble buildLib && \
    cp libtribal_village.so tribal_village_env/libtribal_village.so && \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.9.0+cpu" && \
    pip install --no-cache-dir \
      "numpy>=1.20.0" \
      "gymnasium>=0.29.0" \
      "opencv-python-headless>=4.8.0" \
      "fastapi>=0.115.0" \
      "typer>=0.19.2" \
      "rich>=13.7.0" \
      "pydantic>=2.0.0" \
      "uvicorn[standard]>=0.34.0" \
      "websockets>=15.0.0" \
      psutil \
      nvidia-ml-py \
      rich-argparse && \
    pip install --no-cache-dir --no-deps "pufferlib-core>=3.0.0" && \
    pip install --no-cache-dir --no-deps .

CMD ["python", "-m", "tribal_village_env.coworld.server"]
