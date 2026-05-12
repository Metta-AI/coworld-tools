FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pystack.py /usr/local/bin/pystack
RUN chmod +x /usr/local/bin/pystack

ENTRYPOINT ["pystack"]
CMD ["--address", "host.docker.internal", "--port", "2000"]
