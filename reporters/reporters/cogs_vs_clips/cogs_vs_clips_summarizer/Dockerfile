# Build context: the `reporters/` directory. See build.sh.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY reporter_sdk/ /app/reporter_sdk/
RUN pip install /app/reporter_sdk

COPY cogs_vs_clips/cogs_vs_clips_summarizer/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY cogs_vs_clips/cogs_vs_clips_summarizer/cogs_vs_clips_summarizer.py /app/cogs_vs_clips_summarizer.py

ENTRYPOINT ["python", "/app/cogs_vs_clips_summarizer.py"]
