FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir "boto3>=1.34"
COPY cogs_v_clips_grader.py /app/cogs_v_clips_grader.py

ENTRYPOINT ["python", "/app/cogs_v_clips_grader.py"]
