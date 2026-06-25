FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY crewrift_diagnoser.py /app/crewrift_diagnoser.py

ENTRYPOINT ["python", "/app/crewrift_diagnoser.py"]
