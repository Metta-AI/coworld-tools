# Build context: the `reporters/` directory (i.e. the directory containing
# this Dockerfile's parent's parent, the `reporter_sdk/` package, and the
# per-coworld reporter trees). See build.sh.
#
# This is the template image. It is not registered in any Coworld manifest
# and not published to a registry; it exists so the template's smoke test
# can exercise the full reporter wiring (build -> bundle in, zip out) the
# same way a concrete reporter would.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The shared reporter SDK.
COPY reporter_sdk/ /app/reporter_sdk/
RUN pip install /app/reporter_sdk

# The template's runtime entrypoint. The template depends only on the
# SDK, so requirements.txt is empty today; the install line is here so a
# derived concrete reporter only has to drop deps into requirements.txt.
COPY templates/summarizer_template/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY templates/summarizer_template/summarizer.py /app/summarizer.py

ENTRYPOINT ["python", "/app/summarizer.py"]
