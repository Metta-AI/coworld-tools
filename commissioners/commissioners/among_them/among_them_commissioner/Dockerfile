FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY among_them_commissioner.py /app/among_them_commissioner.py

ENTRYPOINT ["python", "/app/among_them_commissioner.py"]
