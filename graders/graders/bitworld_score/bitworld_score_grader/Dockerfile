FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir "boto3>=1.34"
COPY graders/common/grader_runtime.py /app/graders/common/grader_runtime.py
COPY graders/bitworld_score/bitworld_score_grader/bitworld_score_grader.py /app/graders/bitworld_score/bitworld_score_grader/bitworld_score_grader.py

ENTRYPOINT ["python", "-m", "graders.bitworld_score.bitworld_score_grader.bitworld_score_grader"]
