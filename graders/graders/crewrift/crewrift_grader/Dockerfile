FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir "boto3>=1.34"
COPY graders/common/grader_runtime.py /app/graders/common/grader_runtime.py
COPY graders/crewrift/crewrift_grader/crewrift_grader.py /app/graders/crewrift/crewrift_grader/crewrift_grader.py

ENTRYPOINT ["python", "-m", "graders.crewrift.crewrift_grader.crewrift_grader"]
