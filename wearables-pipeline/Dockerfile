# Sentra backend: one image, two roles (worker / api). Data and secrets are volumes, never baked in.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    WP_ROOT=/app WP_DATA=/data WP_SECRETS=/secrets WP_REPORTS=/data/reports MPLBACKEND=Agg

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY wp ./wp
COPY run_sync.py ./

ARG WP_VERSION=dev
ENV WP_VERSION=${WP_VERSION}
LABEL org.opencontainers.image.title="sentra-backend" \
      org.opencontainers.image.description="Sentra wearables pipeline (worker + API)"

RUN useradd --uid 10001 --create-home sentra && mkdir -p /data /secrets && chown sentra /data /secrets
USER sentra
VOLUME ["/data", "/secrets"]
EXPOSE 8000

# default role: worker. The api service overrides the command.
CMD ["python", "-m", "wp", "worker"]
