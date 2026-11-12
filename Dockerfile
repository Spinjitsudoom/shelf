# Shelf in a container, for PCs and servers (amd64) and Raspberry Pi and other ARM boards (arm64).
#
#   docker compose up -d        (see compose.yaml and docs/docker.md)
#
# Your music is read from /music (mount it read-only); accounts, the library database, covers and
# converted copies live in /data (mount a volume or folder there to keep them).

FROM python:3.14-slim

# ffmpeg reads, measures and converts the music; tini passes stop signals on and reaps helpers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/shelf \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

# Essentia (tempo, key and "sounds like") only comes ready-made for amd64; on ARM, Shelf measures
# with its own engine instead, as it does on Windows.
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ] || [ -z "$TARGETARCH" ]; then \
      uv sync --frozen --no-dev --no-editable; \
    else \
      uv sync --frozen --no-dev --no-editable --no-install-package essentia; \
    fi \
 && rm -rf /root/.cache

COPY docker/config.toml /etc/shelf/config.toml
RUN mkdir -p /data /music && chown 1000:1000 /data

ENV PATH=/opt/shelf/bin:$PATH \
    SHELF_CONFIG=/etc/shelf/config.toml \
    SHELF_DATA_DIR=/data \
    SHELF_HOST=0.0.0.0 \
    SHELF_PORT=4533

# Not root. To match the owner of your files, run it as another user (compose: `user: "1000:1000"`).
USER 1000:1000
VOLUME /data
EXPOSE 4533
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4533/api/ping', timeout=4)"
ENTRYPOINT ["tini", "--"]
CMD ["shelf"]
