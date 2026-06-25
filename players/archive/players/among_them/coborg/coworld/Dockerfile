# Coborg Among Them player image.
#
# Build (from the players repo root):
#   docker build --platform linux/amd64 \
#     -t coborg-among-them:dev \
#     -f players/among_them/coborg/coworld/Dockerfile \
#     .
#
# The image installs the players package (without the mettagrid-heavy
# ``cogames`` extra) plus ``websockets``. Stderr is unbuffered so trace events
# show up immediately in the Coworld runner's captured logs.

FROM --platform=linux/amd64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/players

# Install runtime deps separately so they cache independently of source.
RUN pip install --upgrade pip \
 && pip install \
      "numpy>=2.0.0" \
      "pydantic>=2.12.2" \
      "websockets>=13.0"

# Copy only what's needed to install + run the package. Copying ``players/``
# (rather than the whole repo) keeps the image small and stable.
COPY pyproject.toml README.md ./
COPY players ./players
RUN pip install --no-deps -e .

COPY players/among_them/coborg/coworld/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
