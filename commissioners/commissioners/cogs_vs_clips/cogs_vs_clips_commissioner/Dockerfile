FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY commissioners /app/commissioners

RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["uvicorn", "commissioners.cogs_vs_clips.cogs_vs_clips_commissioner.cogs_vs_clips_commissioner:app", "--host", "0.0.0.0", "--port", "8080"]
