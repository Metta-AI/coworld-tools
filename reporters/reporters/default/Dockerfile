# Build context: the `reporters/` directory (the directory containing
# this Dockerfile's parent's parent, the `reporter_sdk/` package, and the
# per-coworld reporter trees). See build.sh.
#
# This is the Softmax-published default reporter image. Coworld manifests
# whose `reporter[]` does not declare a game-specific reporter can point
# at this image to satisfy the schema's `min_length=1` requirement.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The shared reporter SDK.
COPY reporter_sdk/ /app/reporter_sdk/
RUN pip install /app/reporter_sdk

# The reporter's runtime entrypoint. The default reporter depends only on
# the SDK (no game-specific parsing libraries), so requirements.txt is
# empty today; the install line is here so a future change that adds a
# runtime dep doesn't require touching the Dockerfile.
COPY default/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY default/default_reporter.py /app/default_reporter.py

ENTRYPOINT ["python", "/app/default_reporter.py"]
