FROM docker.io/library/python:3.12-slim

RUN pip install --no-cache-dir websockets==16.0

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN mkdir -p /app/tribal_village_env/coworld && \
    touch /app/tribal_village_env/__init__.py /app/tribal_village_env/coworld/__init__.py
COPY tribal_village_env/coworld/player.py /app/tribal_village_env/coworld/player.py

CMD ["python", "-m", "tribal_village_env.coworld.player"]
