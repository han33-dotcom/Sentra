# Sentra read API + processing job: one image, two commands. No health data, secrets or
# collector credentials are baked in; processed outputs live in the sentra-processed volume.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SENTRA_PROCESSED_DIR=/data/processed

WORKDIR /app
COPY requirements-cloud.txt requirements-api.txt ./
RUN pip install -r requirements-cloud.txt -r requirements-api.txt

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps . && pip check

RUN useradd --uid 10001 --create-home sentra && mkdir -p /data/processed && chown -R sentra /data
USER sentra
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "sentra.api:app", "--host", "0.0.0.0", "--port", "8000"]
