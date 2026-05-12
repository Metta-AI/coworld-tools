FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stacker.py /usr/local/bin/stacker
RUN chmod +x /usr/local/bin/stacker

ENTRYPOINT ["stacker"]
CMD ["--address", "host.docker.internal", "--port", "2000"]
