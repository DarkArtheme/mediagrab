# Bot image: python + the uv-managed workspace venv (yt-dlp, gallery-dl) + ffmpeg.
# Build from the repo root:
#   docker build -f docker/Dockerfile --build-arg VERSION=X.Y.Z -t reelsbot:X.Y.Z .
FROM python:3.12-slim

# Match the uv_build pin in the package pyprojects (>=0.12,<0.13).
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock .python-version ./
COPY packages ./packages
COPY bot ./bot
RUN uv sync --frozen --no-dev

# The venv on PATH also lets mediagrab resolve its pinned yt-dlp/gallery-dl.
ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home bot && mkdir -p /data && chown -R bot:bot /data
USER bot

ARG VERSION=dev
LABEL org.opencontainers.image.title="reelsbot" \
      org.opencontainers.image.description="Telegram bot that replies to Instagram/TikTok links with the media and caption" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/DarkArtheme/mediagrab"

CMD ["python", "-m", "reelsbot"]
