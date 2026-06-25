FROM docker.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["python", "-m", "diplomacog.coworld.server"]
