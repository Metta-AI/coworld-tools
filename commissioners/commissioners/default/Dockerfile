FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY cli.py server.py strategies.py graduation.py /app/

EXPOSE 8080

# Defaults to round-robin with no graduation; override args to configure.
ENTRYPOINT ["python", "cli.py"]
