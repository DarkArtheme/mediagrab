#!/usr/bin/env bash
# Run the Telegram bot locally: sync the uv workspace, sanity-check config, start polling.
# Usage: scripts/run_bot.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f .env ]]; then
    echo "error: .env not found in $repo_root (BOT_TOKEN etc. are required)" >&2
    exit 1
fi

# Warn early if the cookies file from .env is missing — Instagram extraction
# would otherwise fail only on the first pasted link.
cookies="$(grep -E '^IG_COOKIES_FILE=' .env | tail -1 | cut -d= -f2- || true)"
if [[ -n "$cookies" && ! -f "$cookies" ]]; then
    echo "warning: IG_COOKIES_FILE=$cookies does not exist — Instagram downloads will fail" >&2
fi

uv sync --quiet
exec uv run python -m reelsbot
