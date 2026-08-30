# Implementation Plan — Instagram Reels/Posts → Telegram Bot

## Goal

A Telegram bot: user pastes an Instagram link, bot replies with the media and the description.

- Reel link (`https://www.instagram.com/reel/<code>/…`) → video + caption.
- Post link (`https://www.instagram.com/p/<code>/…`) → photo(s) as an album (mixed photo+video
  carousels supported) + caption.
- Built on a reusable library (`mediagrab`) designed so a TikTok provider drops in later.

## Locked decisions

| Area | Decision |
|---|---|
| Language / tooling | Python, uv workspace, ruff, pytest, typed |
| Repo | Monorepo: `packages/mediagrab` (library) + `bot/` (aiogram bot) |
| IG access | Burner account cookies + yt-dlp (video) / gallery-dl (photos), subprocess |
| Bot framework | aiogram 3.x, long polling |
| File limit | Self-hosted Local Bot API Server in Docker → 2 GB uploads |
| Captions | On media (≤1024 chars); overflow sent as follow-up text message |
| Cache | SQLite (WAL): uid → Telegram file_id(s) + caption, behind a repository class |
| Access | Whitelist of Telegram user IDs |
| UX | Immediate "⏳ downloading…" status, removed when media arrives |
| Deploy | VPS, docker-compose (bot + telegram-bot-api containers) |
| Scale path | Paid scraping API / proxies as an additional provider later; Postgres later |

## Architecture

```
reels-downloader/
├── CLAUDE.md / plan.md / README.md
├── pyproject.toml                  # uv workspace root
├── packages/mediagrab/
│   ├── pyproject.toml
│   ├── src/mediagrab/
│   │   ├── models.py               # MediaPost, MediaItem
│   │   ├── errors.py               # UnsupportedUrl, PostUnavailable, AuthExpired,
│   │   │                           # RateLimited, ExtractionFailed
│   │   ├── router.py               # URL pattern → provider; normalizes/strips tracking params
│   │   └── providers/
│   │       ├── base.py             # Provider protocol: resolve(url) -> MediaPost
│   │       ├── instagram/
│   │       │   ├── provider.py     # dispatch reel vs post
│   │       │   ├── ytdlp.py        # video extraction (subprocess, --dump-json)
│   │       │   └── gallerydl.py    # photo/carousel extraction (subprocess)
│   │       └── tiktok/             # future (yt-dlp based)
│   └── tests/                      # fixtures = captured extractor JSON, subprocess mocked
├── bot/
│   ├── pyproject.toml
│   ├── src/reelsbot/
│   │   ├── __main__.py / main.py   # startup, dispatcher, long polling
│   │   ├── config.py               # env: token, whitelist, cookies path, api server URL
│   │   ├── handlers.py             # link handler, /start, /help, whitelist filter
│   │   ├── delivery.py             # sendVideo / sendMediaGroup, caption split, status msg
│   │   └── cache.py                # SQLite repository (file_id cache)
│   └── tests/
├── docker/
│   ├── Dockerfile                  # bot image (python + yt-dlp + gallery-dl + ffmpeg)
│   └── docker-compose.yml          # bot + aiogram/telegram-bot-api, volumes: cookies, db, tmp
└── .github/workflows/ci.yml        # ruff + pytest on push/PR
```

Data flow: message → whitelist filter → router picks provider → cache lookup (hit ⇒ send
file_id instantly) → miss ⇒ provider downloads to a temp dir → delivery sends media + caption →
store returned file_id(s) in cache → cleanup temp files.

## Phases

### Phase 0 — Scaffolding (small)
uv workspace with both packages, ruff + pytest wired, CI running, empty-but-importable modules,
`.env.example`, README stub.
**Done when:** `uv sync && uv run pytest && uv run ruff check .` pass in CI.

### Phase 1 — Library core (small)
`models.py`, `errors.py`, `base.py` protocol, `router.py` with Instagram URL parsing
(`/reel/`, `/reels/`, `/p/`, `/tv/`; strips `igsh`/`igsi`/query junk; extracts shortcode as `uid`).
Unit tests for every URL shape, including the two example links from the brief.
**Done when:** router maps valid URLs to (provider, uid) and raises `UnsupportedUrl` otherwise.

### Phase 2 — Instagram provider (the hard one)
- Cookie handling: `IG_COOKIES_FILE` (Netscape format) documented; how-to in README
  (export via browser extension from the burner account).
- `ytdlp.py`: subprocess `yt-dlp --dump-json` + download for reels/video posts; map
  `description` → caption, `uploader` → author; detect login-wall/expired-cookie stderr
  patterns → `AuthExpired`; 429/throttle patterns → `RateLimited`.
- `gallerydl.py`: photo and mixed carousels for `/p/` links with the same cookie file; ordered
  items; caption from metadata.
- Provider tries yt-dlp for reels, gallery-dl for posts; a `/p/` video post falls back to yt-dlp.
- Tests: mocked subprocess with recorded JSON fixtures (success, multi-photo, mixed, private
  post, expired cookies). One optional live smoke test behind an env flag, skipped in CI.
**Done when:** `MediaPost` comes back correctly for reel, photo post, carousel, and error cases
map to the taxonomy. Manual check against the two example URLs.

### Phase 3 — Bot MVP
aiogram 3 app: whitelist filter, link handler, "⏳ downloading…" status message (deleted on
completion), `delivery.py` (sendVideo with `supports_streaming=True`; sendMediaGroup for albums,
caption on first item; >1024-char captions truncated on media + full text as follow-up message),
error taxonomy → friendly replies, admin notification on `AuthExpired`.
**Done when:** running locally against real Telegram (standard api.telegram.org for now), both
example links produce correct replies end-to-end.

### Phase 4 — Cache + politeness
`cache.py`: SQLite in WAL mode, table `posts(uid PK, provider, kind, file_ids JSON, caption,
created_at)`; lookup before download, store after first successful send. Simple per-user
cooldown (e.g. one concurrent job per user, small delay between IG hits) to protect the burner
account. A global asyncio semaphore limits concurrent extractions.
**Done when:** re-sending a link replies instantly without touching Instagram.

### Phase 5 — Docker + deploy
Bot Dockerfile (includes yt-dlp, gallery-dl, ffmpeg); compose file with `aiogram/telegram-bot-api`
container (`TELEGRAM_API_ID/HASH`), bot pointed at it (which unlocks 2 GB uploads and local file
handoff); volumes for cookies, SQLite db, temp downloads; restart policies; deploy notes for the
VPS in README.
**Done when:** `docker compose up -d` on the VPS serves the whitelist, including a >50 MB video.

### Phase 6 — Hardening
Structured logging (request id, uid, timings), retry-once on transient extraction failures,
temp-dir cleanup guarantees, `/health` self-check command for admin, graceful shutdown,
yt-dlp/gallery-dl version pinning + a documented upgrade routine (these tools break when IG
changes; upgrading them is the first fix to try).
**Done when:** a week of normal use requires no manual intervention besides (rarely) refreshing
cookies.

### Phase 7 — TikTok provider

Decisions (locked 2026-08-30): videos **and** photo slideshows in the first version; slideshows
deliver photos + caption only (no music track); **anonymous** access — no cookies by default,
but an optional `TIKTOK_COOKIES_FILE` env is threaded through so a burner account can be added
later without code changes; no proxy work (VPS region reaches TikTok fine).

- **Router**: add TikTok hosts and URL shapes:
  - `tiktok.com/@user/video/<id>` → kind `video`, uid `<id>`
  - `tiktok.com/@user/photo/<id>` → kind `photo`, uid `<id>`
  - short links `vm.tiktok.com/<token>`, `vt.tiktok.com/<token>`, `tiktok.com/t/<token>` →
    kind `unknown` — the post id and video/photo kind are hidden behind a redirect. The router
    stays offline; the **provider** resolves the redirect (one anonymous GET, no auth) and then
    dispatches. `MediaPost.uid` is always the resolved numeric id, so the cache converges even
    when two users paste different short tokens for the same post. `PostKind` widens to a
    per-provider literal (`video`/`photo`/`unknown` for TikTok).
- **Provider layout** mirrors Instagram: `providers/tiktok/{provider.py, ytdlp.py, gallerydl.py}`.
  - `ytdlp.py`: `yt-dlp --dump-json` + download for `/video/` posts; prefer H.264 formats (same
    lesson as IG black-screen fix); `description` → caption, `uploader` → author; no cookies
    passed unless `TIKTOK_COOKIES_FILE` is set.
  - `gallerydl.py`: gallery-dl for `/photo/` slideshows (yt-dlp is flaky there); ordered photos,
    caption from metadata. If gallery-dl proves unreliable in live testing, fall back to a
    `__UNIVERSAL_DATA_FOR_REHYDRATION__` mini-parser as plan B.
  - A `/video/` URL that turns out to be a slideshow (or vice versa) falls through to the other
    extractor, same pattern as the IG `/p/`-video fallback.
- **Errors**: map geo-block / "video unavailable" / private-account / rate-limit stderr patterns
  onto the existing taxonomy (`PostUnavailable`, `RateLimited`, `ExtractionFailed`;
  `AuthExpired` only if cookies are configured).
- **Bot**: no handler/delivery changes (provider-agnostic by design); `config.py` gains the
  optional `TIKTOK_COOKIES_FILE` passthrough; cache uids namespaced per provider
  (`tiktok:<id>`) to rule out cross-provider collisions.
- **Tests**: router unit tests for every URL shape incl. junk query params; mocked-subprocess
  fixtures for video, slideshow, unavailable, geo-blocked; live smoke tests behind the existing
  env flag using real sample links (video, slideshow, short link).

**Done when:** pasting a TikTok video link, photo-slideshow link, and a `vm.tiktok.com` short
link each produce correct replies end-to-end; repeated links answered from cache.

## Future (designed-for, not built now)

- **Paid fallback provider**: ScrapeCreators (~$1–2/1000 posts) or Apify as an
  `InstagramApiProvider`; router gains an ordered fallback chain (cookies-based first, paid on
  failure). Proxy support (env `PROXY_URL`) threaded into subprocess calls for scaling.
- **Postgres** swap behind the repository class if the bot outgrows one process.
- **Open access** with per-user rate limits instead of the whitelist.

## Known risks

1. **Instagram breakage is a when, not an if.** Mitigation: thin wrappers over replaceable
   tools, pinned versions with an upgrade routine, error taxonomy that tells the admin exactly
   what broke (cookies vs rate limit vs extractor).
2. **Burner account flagging.** Mitigation: whitelist + cache + cooldowns keep request volume
   tiny; `AuthExpired` alerting makes re-login a 5-minute chore; paid-API fallback is the
   designed escape hatch.
3. **gallery-dl/yt-dlp caption edge cases** (empty captions, emoji, RTL text) — covered by
   fixtures in Phase 2 tests.
