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
COPY among_them/among_them_summarizer/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY among_them/among_them_summarizer/among_them_summarizer.py /app/among_them_summarizer.py

ENTRYPOINT ["python", "/app/among_them_summarizer.py"]
