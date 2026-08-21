# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip build \
    && python -m build --wheel --outdir /wheels

FROM python:3.12-slim-bookworm AS runtime

ARG APP_UID=10001
ARG APP_GID=10001
ARG VERSION=dev
ARG REVISION=unknown
ARG CREATED=unknown

LABEL org.opencontainers.image.title="Synobot" \
      org.opencontainers.image.description="Telegram control and monitoring for Synology Download Station" \
      org.opencontainers.image.source="https://github.com/q8hk/synobot" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/synobot.db \
    TMPDIR=/tmp/uploads

RUN groupadd --gid "${APP_GID}" synobot \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --home-dir /home/synobot synobot \
    && install -d -o synobot -g synobot -m 0750 /data /tmp/uploads

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl \
    && rm -rf /wheels

USER synobot:synobot
WORKDIR /data
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-m", "synobot.healthcheck"]

STOPSIGNAL SIGTERM
CMD ["python", "-m", "synobot"]

