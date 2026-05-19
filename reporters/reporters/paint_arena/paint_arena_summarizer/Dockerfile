# Build context: the `reporters/` directory (i.e. the directory containing
# this Dockerfile's parent, the `reporter_sdk/` package, and the per-coworld
# reporter trees). See build.sh.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The shared reporter SDK. Empty for now (skeleton package) but copied and
# installed so the future SDK extraction is a no-op for this reporter.
COPY reporter_sdk/ /app/reporter_sdk/
RUN pip install /app/reporter_sdk

# The reporter source.
COPY paint_arena/paint_arena_summarizer/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY paint_arena/paint_arena_summarizer/paint_arena_summarizer.py /app/paint_arena_summarizer.py

ENTRYPOINT ["python", "/app/paint_arena_summarizer.py"]
