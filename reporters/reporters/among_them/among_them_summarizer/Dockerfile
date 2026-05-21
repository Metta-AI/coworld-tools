FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY among_them_summarizer.py /app/among_them_summarizer.py

ENTRYPOINT ["python", "/app/among_them_summarizer.py"]
