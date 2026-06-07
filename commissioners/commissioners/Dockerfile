FROM python:3.13-slim

ARG COMMISSIONER_KEY=auto
ENV COMMISSIONER_KEY=${COMMISSIONER_KEY} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY commissioners /app/commissioners

RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["uvicorn", "commissioners.common.app:app", "--host", "0.0.0.0", "--port", "8080"]
