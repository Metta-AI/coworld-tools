FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir "boto3>=1.34"
COPY graders/common/grader_runtime.py /app/graders/common/grader_runtime.py
COPY graders/tribal_cog/tribal_cog_grader/tribal_cog_grader.py /app/graders/tribal_cog/tribal_cog_grader/tribal_cog_grader.py

ENTRYPOINT ["python", "-m", "graders.tribal_cog.tribal_cog_grader.tribal_cog_grader"]
