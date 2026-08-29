# Worklog

All project actions are recorded here, newest entry last.

## 2026-08-28 — Planning session

- Researched (3 parallel subagents) the 2026 state of: Instagram downloading tools
  (anonymous scraping dead; yt-dlp/gallery-dl need logged-in cookies; paid APIs as reliable
  alternative), Telegram bot stack (aiogram 3 + long polling; 50 MB limit → 2 GB via
  self-hosted Local Bot API Server; 1024-char media captions), and TikTok tools for the
  future provider (yt-dlp works anonymously for videos; photo slideshows flaky).
- Agreed decisions with the user: Python + uv monorepo (`packages/mediagrab` library +
  `bot/`), MVP for ~10 whitelisted users on a VPS with Docker, burner-account cookies for
  Instagram with a paid-API/proxy fallback designed for later, Local Bot API Server
  container, caption on media with >1024 overflow as a follow-up message, SQLite (WAL)
  file_id cache behind a repository class, photo/mixed carousels as albums, "⏳ downloading…"
  progress message, solid-but-lean engineering (ruff, pytest, typed, GitHub Actions CI).
- Created `CLAUDE.md` (working instructions, core provider contract, locked decisions,
  conventions) and `plan.md` (architecture, phases 0–6 with done-criteria, future work,
  risks).
- Per user instruction: persistent memory is not used in this project; this worklog is the
  record of actions instead. Removed the memory files created earlier in the session.

## 2026-08-28 — Phase 0: Scaffolding

- Created the uv workspace: root `pyproject.toml` with `[tool.uv.workspace]`
  (members: `packages/mediagrab`, `bot`), shared dev dependency group (pytest, ruff),
  ruff config (line-length 100, py312, rules E/W/F/I/UP/B/SIM), and pytest config.
  Pytest uses `--import-mode=importlib` because both packages have a `tests/test_imports.py`
  and the default import mode can't handle duplicate basenames.
- `packages/mediagrab`: pyproject (uv_build backend, src layout), package README, and
  empty-but-importable modules per the planned architecture: `models.py`, `errors.py`,
  `router.py`, `providers/base.py`, `providers/instagram/{provider,ytdlp,gallerydl}.py`.
- `bot/`: pyproject (`reelsbot`, depends on `mediagrab` via `{ workspace = true }`) and
  stub modules `main.py`, `__main__.py`, `config.py`, `handlers.py`, `delivery.py`,
  `cache.py`. `main()` raises NotImplementedError until Phase 3.
- Smoke tests: parametrized import tests for every module in both packages (16 tests).
- Repo files: `.github/workflows/ci.yml` (setup-uv, `uv sync --all-packages`, ruff check,
  ruff format --check, pytest), `.env.example` (BOT_TOKEN, TELEGRAM_API_ID/HASH,
  TELEGRAM_API_URL, WHITELIST_USER_IDS, ADMIN_USER_ID, IG_COOKIES_FILE, DB_PATH),
  root `README.md` stub, `.gitignore`, `.python-version` (3.12).
- Initialized the git repository (`git init -b main`); nothing committed yet, no remote.
- Verified locally: `uv sync --all-packages`, `uv run pytest` (16 passed),
  `uv run ruff check .`, `uv run ruff format --check .` all pass. CI itself will run once
  the repo is pushed to GitHub.

## 2026-08-28 — Phase 1: Library core

- `models.py`: `MediaItem` (kind: "video"|"photo", path, optional width/height/duration)
  and `MediaPost` (items, caption, author, source_url, uid) as slotted dataclasses.
- `errors.py`: `MediaGrabError` base + `UnsupportedUrl`, `PostUnavailable`, `AuthExpired`,
  `RateLimited`, `ExtractionFailed`.
- `providers/base.py`: runtime-checkable `Provider` protocol. **Decision:** `resolve` is
  `async` — the bot is aiogram/asyncio, Phase 4 plans an asyncio semaphore around
  extractions, and Phase 2 will use `asyncio.subprocess`.
- `router.py`: `parse_url(url) -> Route` where `Route = (provider, uid, kind, canonical_url)`;
  `kind` is "reel" (also covers `/reels/` and `/tv/`) or "post" (`/p/`), which is what
  provider.py will dispatch on in Phase 2. Accepts instagram.com / www / m hosts, http(s),
  scheme-less pastes, username-prefixed share paths (`/<user>/p/<code>/`), and strips all
  query junk/fragments; canonical URL is `https://www.instagram.com/<seg>/<code>/` with
  `reels`→`reel` normalized. `/share/<...>/` redirect-token links are explicitly rejected
  (their last segment is not a shortcode). Everything else raises `UnsupportedUrl`.
  Also a `Router` class: `register(name, provider)` + `resolve(url) -> (Provider, Route)`;
  a parseable URL with no registered provider raises `UnsupportedUrl` too.
- `mediagrab/__init__.py` re-exports the public API (models, Provider, Route, Router,
  parse_url).
- Tests: 43 new (models construction, error hierarchy, 17 valid URL shapes, 17 unsupported
  shapes, Router registration paths). **Note:** the brief's two example links were never
  recorded in the repo, so tests use realistic stand-in links (`EXAMPLE_REEL`/`EXAMPLE_POST`
  in `test_router.py`, share-style URLs with `igsh` params); swap in the real ones when
  available.
- Done criteria verified: 59 tests pass, ruff check/format clean.

## 2026-08-28 — Phase 2: Instagram provider

- User supplied the brief's real example links; test_router.py now asserts on them:
  reel `DZu6cdBI2-A`, post `DWTPjRXE5WS` (expected uids/canonicals updated to match).
- `mediagrab/_proc.py` (new, shared by future providers): async `run_tool(cmd, timeout)`
  via `asyncio.create_subprocess_exec`; missing binary and timeout both surface as
  `ExtractionFailed`, never raw OS errors.
- `providers/instagram/_classify.py` (new): `classify_failure(tool, stderr)` maps stderr
  onto the taxonomy. **Decision:** auth patterns are checked before rate-limit ones —
  yt-dlp's dead-cookies message ("rate-limit reached or login required") mentions both,
  and with cookies configured the actionable cause is almost always expired cookies
  (admin gets notified to refresh). Pure 429/"too many requests" → `RateLimited`;
  404/private/does-not-exist → `PostUnavailable`; anything else → `ExtractionFailed`
  with the tool name + last 3 stderr lines in the message.
- `ytdlp.py`: one subprocess call (`--dump-json --no-simulate`) downloads and prints
  metadata; output template `<dest>/%(id)s.%(ext)s`, file located by id-glob;
  description→caption, uploader→author, width/height/duration mapped.
- `gallerydl.py`: `--write-metadata --directory <dest>`; items read back from sidecar
  `<file>.json` files and ordered by the `num` field; empty result list = cue for the
  yt-dlp fallback.
- `provider.py`: `InstagramProvider(cookies_file, download_dir, timeout=600)`; each
  resolve gets a fresh `mkdtemp` under `download_dir` (cleanup is the caller's job —
  the bot deletes after sending). reel → yt-dlp; post → gallery-dl; falls back to
  yt-dlp when gallery-dl finds nothing or raises `ExtractionFailed` (plain-video `/p/`
  posts). AuthExpired/RateLimited/PostUnavailable propagate without fallback.
  Video kind for gallery items inferred from file extension; `video_duration` from
  sidecar metadata.
- Deps: mediagrab now depends on `yt-dlp` + `gallery-dl` (pip packages ship the CLIs
  into the venv); dev adds `pytest-asyncio` (`asyncio_mode = "auto"`).
- Tests (+27): provider tests fake `_proc.run_tool` and write files like the real tools
  (reel success incl. cookie flag threading, carousel ordering by `num` with shuffled
  filenames, mixed photo+video carousel, video-post fallback call order, expired
  cookies → `AuthExpired`, 429 → `RateLimited`, private → `PostUnavailable`, garbage
  JSON / unknown stderr → `ExtractionFailed`, non-IG URL rejected before any
  subprocess); classifier unit tests; real `run_tool` missing-binary + timeout tests.
  Fixtures: `ytdlp_reel.json`, `gallerydl_sidecar.json` (emoji/non-ASCII captions covered).
  `test_live_smoke.py` hits real Instagram only with `MEDIAGRAB_LIVE_TEST=1`.
- README: burner-account cookie export how-to (Netscape format, `IG_COOKIES_FILE`),
  refresh-on-AuthExpired routine, live smoke test instructions.
- Verified: 84 passed, 2 skipped (live smoke), ruff clean. End-to-end wiring
  sanity-checked with a real yt-dlp run (no cookies): subprocess + error classification
  worked; the connection to instagram.com timed out from this machine/sandbox, so the
  **manual check against the example URLs is still pending** — needs the burner
  cookies file and a network where Instagram is reachable (e.g. the VPS).
- Live retry (network reachable this time): **example reel resolved end-to-end without
  cookies** — 27 MB 1080x1920 mp4, real caption + author mapped correctly (yt-dlp gave
  no `duration` for this reel → field is None; fine for sendVideo). **Example photo
  post failed anonymously as expected**: gallery-dl was redirected to the login
  endpoint which returned 429; classified as `RateLimited` with stderr tail preserved.
  Remaining manual check: run the live smoke test with the burner `IG_COOKIES_FILE`
  to confirm the photo/carousel path.
- User provided the burner account's cookies (JSON extension export); converted to
  Netscape format at repo root `cookies.txt` (gitignored, chmod 600 — verified with
  `git check-ignore`). Live smoke test with `IG_COOKIES_FILE=cookies.txt`: **both
  example URLs pass** (reel video + photo post download with metadata). Note: the
  extractors rewrite the cookie jar after a run (rotated csrftoken/rur) — expected.
  **Phase 2 done-criteria fully met.**

## 2026-08-28 — Phase 3: Bot MVP

- Deps: `reelsbot` now depends on `aiogram>=3.13` and `python-dotenv>=1.0` (`.env` loaded
  in `main()`; env still wins in Docker where no `.env` exists).
- `config.py`: frozen `Config` dataclass + `Config.from_env()` (raises `ConfigError` on
  missing/malformed values). Required: `BOT_TOKEN`, non-empty `WHITELIST_USER_IDS`,
  `ADMIN_USER_ID`. Optional: `TELEGRAM_API_URL` (empty → standard api.telegram.org),
  `IG_COOKIES_FILE`, `DB_PATH` (default `cache.sqlite3`, used in Phase 4), and new
  `DOWNLOAD_DIR` (added to `.env.example`; empty → system temp dir).
- `delivery.py`: `split_caption()` (≤1024 unchanged; longer → 1023 chars + "…" on media,
  full text as follow-up messages chunked at 4096) and `send_post()` — single video via
  `send_video(supports_streaming=True, width/height/duration)`, single photo via
  `send_photo`, multi-item posts as `send_media_group` albums chunked at 10 with the
  caption only on the very first item; returns all sent `Message`s so Phase 4 can harvest
  file_ids. Float durations rounded to int for the Bot API.
- `handlers.py`: aiogram `Router` with a `Whitelisted` filter (reads `Config` via
  dispatcher DI); `/start`+`/help`; link handler (regex-extracts first URL incl.
  scheme-less pastes → `media_router.resolve` → "⏳ Downloading…" status → provider →
  `send_post` → status deleted); errors edit the status message in place via
  `friendly_error()` mapping the taxonomy to human replies (`ExtractionFailed` and
  unexpected exceptions share a generic fallback; unexpected ones re-raise after
  replying). `AuthExpired` additionally DMs `ADMIN_USER_ID` (best-effort, never breaks
  the user reply). Temp download dir is rmtree'd in a `finally`. Catch-all handlers:
  whitelisted non-text → usage hint; non-whitelisted anything → polite refusal.
  **Decision:** `UnsupportedUrl` from parsing is answered directly without creating a
  status message (nothing was ever going to be downloaded).
- `main.py`: `run()` builds `Bot` (custom `TelegramAPIServer.from_base` session when
  `TELEGRAM_API_URL` is set), `Dispatcher` with `config`/`media_router` injected as
  workflow data, `delete_webhook()` then long polling. `build_media_router()` registers
  `InstagramProvider(cookies_file, download_dir)` under "instagram".
- README: "Running the bot locally" section (BotFather token, user id via @userinfobot,
  leave `TELEGRAM_API_URL` empty until Docker phase); status updated to phases 0–3.
- Tests (+36, total 120 passed / 2 skipped): config parsing (required/optional/empty-var
  cases), caption splitting (limit boundaries, chunking), `send_post` against an
  `AsyncMock` bot (single video kwargs, album caption placement, >10-item chunking,
  follow-up text, returned messages), handlers (URL extraction, error mapping, whitelist
  filter, and the full link-handler flow with a fake provider: happy path incl. temp-dir
  cleanup, no-URL hint, unsupported URL, RateLimited edits status without admin ping,
  AuthExpired pings admin, delivery crash cleans up + re-raises). Ruff check/format clean.
- **Done-criterion still pending:** the live end-to-end run against real Telegram needs a
  `BOT_TOKEN` (none exists yet — no `.env` in the repo). Next step for the user: create a
  bot via @BotFather, fill `.env` per the new README section, run
  `uv run python -m reelsbot`, and send both example links.

## 2026-08-29 — .env, first commit, branch rename

- Answered setup questions (in chat): `.env` paths are host paths when running locally
  and container paths (`/data/...`) only once the Phase 5 Docker stack mounts them;
  how to create the Telegram application on my.telegram.org; how the Local Bot API
  Server deployment works (aiogram/telegram-bot-api container, `--local` mode, `logOut`
  token migration, shared volume).
- User couldn't create the my.telegram.org application (VPN-related "ERROR"; Telegram
  blocked without VPN). **Decision:** proceed without it — `api_id`/`api_hash` are only
  needed by the Local Bot API Server in Phase 5; Phase 3 uses cloud api.telegram.org
  with just the bot token. Fallbacks for Phase 5: retry the form later / from the VPS
  IP, or ship in 50 MB cloud mode and add the local server afterwards (env-only change).
- User created the bot (@darkartheme_reels_scraper_bot) and filled `.env` (cloud API,
  one whitelisted user who is also admin, `IG_COOKIES_FILE=cookies.txt`,
  `DOWNLOAD_DIR=/tmp/reels-downloads`). Verified: `Config.from_env()` parses it, the
  cookies file exists, `getMe` succeeds with the token, and `.env`/`cookies.txt`/
  `cache.sqlite3` are all git-ignored.
- Renamed the branch `main` → `master` (no commits existed yet) and made the initial
  commit: everything from Phases 0–3 (workspace, mediagrab library, Instagram provider,
  bot MVP, tests, CI, docs).
- Per user instruction, added a rule to CLAUDE.md: commit to `master` after any file
  changes (secrets stay git-ignored, never committed).

## 2026-08-29 — Phase 4: Cache + politeness

- `cache.py`: `CacheRepository(db_path)` over sqlite3 (WAL pragma on connect; parent dir
  auto-created), table `posts(uid PK, provider, kind, file_ids JSON, caption,
  created_at)`. `get(uid) -> CachedPost | None`, `put` (upsert via ON CONFLICT),
  `delete`, `close`. `CachedItem(kind, file_id)` / `CachedPost` dataclasses.
  **Decision:** sync sqlite3 calls straight from the async handler — ops are
  sub-millisecond at this scale; revisit only if Postgres lands.
- `throttle.py` (new module): `ExtractionGate` — global `asyncio.Semaphore`
  (default 2 concurrent extractions), a minimum interval between extraction *starts*
  (default 3 s, enforced under a lock with monotonic time), and a per-user busy set
  (`acquire_user`/`release_user`) so each user has at most one in-flight job.
  Defaults are module constants, not env — move to config if tuning is ever needed.
- `delivery.py` refactor: internal `_Payload` (kind + FSInputFile-or-file_id string +
  video dims) and one `_deliver()` used by both `send_post` (fresh files) and new
  `send_cached` (Telegram file_ids, no download). New `extract_file_ids(messages)`
  harvests `video.file_id` / largest `photo` size from sent messages, skipping text
  follow-ups. Same caption rules on both paths.
- `handlers.py`: link handler now takes `cache` + `gate` via dispatcher DI. Flow:
  route → cache lookup (hit ⇒ `send_cached`, instant, no status message) → per-user
  gate (busy ⇒ "still working on your previous link") → status message → extraction
  under `gate.slot()` → send → `cache.put` with extracted file_ids → release user in
  `finally`. **Decision:** a `TelegramBadRequest` on a cached send (stale file_id,
  e.g. after a future Bot API server switch) deletes the entry and falls through to a
  fresh extraction instead of failing the user.
- `main.py`: constructs `CacheRepository(config.db_path)` and `ExtractionGate()` and
  injects them as polling workflow data.
- Tests (+21, total 141 passed / 2 skipped): cache (roundtrip incl. emoji caption,
  order-preserving multi-item JSON, upsert, delete, persistence across connections,
  WAL mode), throttle (busy/release/independent users, min-interval spacing,
  concurrency peak of 1 under a 1-slot gate, zero-interval fast path), delivery
  (send_cached by file_id for video/photo/album, extract_file_ids), handlers (happy
  path now also asserts cache stored + user slot released; cache hit answers without
  touching the provider or posting a status; stale-cache fallback re-extracts and
  replaces the entry; busy user refused; failures cache nothing and release the user).
  README status → phases 0–4. Ruff check/format clean.
- Done-criterion "re-sending a link replies instantly without touching Instagram" —
  unit-verified (cache-hit path never calls the provider); live confirmation shares
  the pending Phase 3 end-to-end run.

## 2026-08-29 — Live-test round 1: two bugs found and fixed

- Ran the bot locally (background process, logs to a scratchpad file); user sent the
  two example links. Both failed; log analysis found two independent bugs:
  1. **Reel: `TelegramNetworkError: Request timeout error` on `send_video`** — the
     ~27 MB upload through cloud api.telegram.org exceeded aiogram's default 60 s
     request timeout. Fix: `delivery.py` passes `request_timeout=UPLOAD_TIMEOUT`
     (300 s) on `send_video`/`send_photo`/`send_media_group`.
  2. **Photo post: `ExtractionFailed` ("yt-dlp … No video formats found") in 1.8 s** —
     gallery-dl was never really tried: it's installed only in the venv, and the bot
     was launched via `.venv/bin/python -m reelsbot` directly, so PATH lacked
     `.venv/bin`; gallery-dl → instant "not installed" → silent fallback to the
     *global* `~/.local/bin/yt-dlp`, which correctly refuses a photo post. (Manual
     `gallery-dl --cookies cookies.txt <post>` worked fine.) Fix:
     `mediagrab/_proc.tool_path(name)` resolves each tool next to `sys.executable`
     (the venv's pinned copy) first, falling back to PATH; both wrappers use it.
     Bonus: the provider now logs the swallowed gallery-dl error before the yt-dlp
     fallback so this failure mode stays diagnosable.
- Tests updated: provider assertions compare `Path(cmd[0]).name`; delivery asserts
  `request_timeout > 60` on video sends. 141 passed / 2 skipped, ruff clean.
- Bot restarted with the fixes; awaiting live re-test (reel, post, reel-again).
