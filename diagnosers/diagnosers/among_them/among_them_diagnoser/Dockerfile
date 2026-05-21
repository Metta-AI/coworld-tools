FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY among_them_diagnoser.py /app/among_them_diagnoser.py

ENTRYPOINT ["python", "/app/among_them_diagnoser.py"]
