FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir "boto3>=1.34"
COPY paint_arena_grader.py /app/paint_arena_grader.py

ENTRYPOINT ["python", "/app/paint_arena_grader.py"]
