# CLAUDE.md

Always communicate with the user in English in this project.

Do not use persistent memory for this project. Instead, record every project action (decisions,
files created/changed, phases completed) as an entry in `worklog.md` at the repo root.

## What this project is

A monorepo with two Python packages:

1. **`mediagrab`** (`packages/mediagrab/`) — a standalone, pip-installable library that turns a
   social-media URL into downloaded media plus its text description. First provider: Instagram
   (Reels → video, posts `/p/` → photo/mixed carousels). The architecture must keep a clean seam
   for a future TikTok provider.
2. **`reelsbot`** (`bot/`) — a Telegram bot (aiogram 3.x, long polling) that uses `mediagrab` to
   reply to a pasted link with the video/photos and the caption text.

Target scale: MVP for ~10 whitelisted users on a VPS with Docker, with an explicit path to scale
later via paid proxies / paid scraping APIs as additional providers.

## Core contract (do not break)

Everything flows through one interface:

```
Provider.resolve(url) -> MediaPost
MediaPost = { items: list[MediaItem], caption: str, author: str, source_url: str, uid: str }
MediaItem = { kind: "video" | "photo", path: Path, width/height/duration: optional }
```

The bot knows nothing about Instagram; providers know nothing about Telegram. New platforms
(TikTok) and new backends (paid APIs) are added as providers behind this interface only.

## Key technical decisions (already made — don't relitigate)

- **Python**, managed with **uv** (workspace mode); lint/format with **ruff**; tests with
  **pytest**; typed code (mypy-clean or pyright-clean).
- **Instagram access**: anonymous scraping is dead (2026). We use a dedicated burner IG account's
  session cookies (Netscape `cookies.txt`, mounted as a Docker volume, path from env
  `IG_COOKIES_FILE`). Extraction is delegated to ready-made tools invoked as subprocesses:
  **yt-dlp** for reels/videos, **gallery-dl** for photo/mixed carousels. Never implement raw
  GraphQL scraping.
- **Telegram**: aiogram 3.x, **long polling**, plus the official **Local Bot API Server**
  container (`aiogram/telegram-bot-api`) so uploads are capped at 2 GB instead of 50 MB.
  Requires `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` from my.telegram.org.
- **Caption delivery**: description goes as the media caption; if > 1024 chars, caption is
  truncated with an ellipsis and the full text is sent as a follow-up text message (max 4096/msg).
  In media groups (albums) only the first item carries the caption.
- **Cache**: SQLite (WAL mode) stores `uid → telegram file_id(s) + caption`. Repeated links are
  answered from cache with zero re-scraping. All DB access goes through a repository class so a
  later Postgres migration touches one module.
- **Access control**: static whitelist of Telegram user IDs from env/config; everyone else gets a
  polite refusal.
- **UX**: send an immediate "⏳ downloading…" status message, delete/edit it when media arrives.

## Commands

```bash
uv sync                                  # install everything (workspace)
uv run pytest                            # run all tests
uv run pytest packages/mediagrab         # library tests only
uv run ruff check . && uv run ruff format --check .
uv run python -m reelsbot                # run the bot locally (needs .env)
docker compose up -d --build             # full stack: bot + local Bot API server
```

## Conventions

- Providers live in `packages/mediagrab/src/mediagrab/providers/<platform>/`; register them in
  the router, which maps URL patterns → provider.
- External tools (yt-dlp, gallery-dl) are called via subprocess with `--dump-json`-style output;
  wrap every call, never let their exceptions/exit codes leak past the provider.
- All user-facing failures map to a small error taxonomy in `mediagrab.errors`
  (`UnsupportedUrl`, `PostUnavailable`, `AuthExpired`, `RateLimited`, `ExtractionFailed`) —
  the bot translates these to human messages and notifies the admin on `AuthExpired`
  (means the IG cookies need refreshing).
- Tests never hit real Instagram/Telegram: subprocess calls and Bot API are mocked; JSON
  fixtures for extractor output live next to the tests.
- Secrets (bot token, api_id/hash, cookies) come from env / mounted files only — never committed.

## Roadmap context

See `plan.md` for phased implementation. Deferred by design: TikTok provider (yt-dlp based),
paid-API fallback provider (ScrapeCreators/Apify) with proxy support, Postgres, open access with
per-user rate limits.
