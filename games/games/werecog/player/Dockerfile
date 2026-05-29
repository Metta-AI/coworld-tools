FROM docker.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir "websockets>=15.0.0"
COPY src/werecog/coworld/player.py /app/player.py

CMD ["python", "/app/player.py"]
