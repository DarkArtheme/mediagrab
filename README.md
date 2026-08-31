# reels-downloader

A Telegram bot: paste an Instagram or TikTok link, get back the media and the description.

- Instagram reel link → video + caption.
- Instagram post link (`/p/`) → photo(s) as an album (mixed photo+video carousels
  supported) + caption.
- TikTok link → video or photo slideshow + caption. Short share links
  (`vt.tiktok.com/…`, `vm.tiktok.com/…`) work too. No account or cookies needed —
  TikTok extraction is anonymous.

Monorepo with two Python packages:

- **`packages/mediagrab`** — a standalone library that turns a social-media URL into downloaded
  media plus its text description (Instagram and TikTok providers).
- **`bot/`** — the Telegram bot (`reelsbot`, aiogram 3.x) built on `mediagrab`.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                  # install everything (workspace)
uv run pytest                            # run all tests
uv run ruff check . && uv run ruff format --check .
uv run python -m reelsbot                # run the bot locally (needs .env)
docker compose up -d --build             # full stack: bot + local Bot API server
```

Copy `.env.example` to `.env` and fill in the values before running the bot.

## Releases & versioning

Both components follow [SemVer](https://semver.org/) (MAJOR.MINOR.PATCH), versioned
independently; each `pyproject.toml` is the single source of truth (`__version__` reads it via
package metadata).

What counts as what:

- **MAJOR** — breaking the public contract. For `mediagrab`: the
  `Provider.resolve(url) -> MediaPost` interface, the `MediaPost`/`MediaItem` fields, the error
  taxonomy, the CLI's JSONL shape/exit codes, or `uid` stability (uids are cache keys — changing
  their format invalidates every consumer's cache). For the bot: env vars/volumes it requires,
  or the cache DB schema.
- **MINOR** — backwards-compatible features: a new provider or URL shape, new optional
  fields/arguments/CLI flags, new bot commands.
- **PATCH** — fixes with no contract change: extractor breakage repairs, yt-dlp/gallery-dl
  bumps, format-selection tweaks, dependency updates.

While MAJOR is 0, minor bumps may still break things (normal SemVer caveat) — note breaks in
the release notes.

To cut a release:

```bash
scripts/release.sh mediagrab 0.3.0   # or: scripts/release.sh bot 0.2.0
git push origin master --follow-tags
```

The script bumps the version, runs lint + tests, commits, and creates the tag
(`mediagrab-vX.Y.Z` / `bot-vX.Y.Z`). On push, CI verifies the tag matches the package version,
then: library tags get a wheel/sdist attached to a GitHub Release; bot tags get the Docker
image built and pushed to `ghcr.io/darkartheme/reelsbot` as `X.Y.Z`, `X.Y`, and `latest`
(the version is also stamped into the image's `org.opencontainers.image.version` label).

The image is also built continuously: every push to `master` publishes
`ghcr.io/darkartheme/reelsbot:edge` plus an immutable semver dev tag
`X.Y.Z-dev.<short-sha>` (`X.Y.Z` = the current version in `bot/pyproject.toml`, so a
dev build reads as "on the way to X.Y.Z, at this commit"), and every PR builds the
image without pushing (Dockerfile validation). Use `edge` to track master,
`X.Y.Z`/`latest` for releases. Local compose builds tag the image
`reelsbot:${BOT_VERSION:-dev}`.

### Running the bot locally

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and put the token in
   `.env` as `BOT_TOKEN`.
2. Find your numeric Telegram user id (e.g. message [@userinfobot](https://t.me/userinfobot))
   and put it in `WHITELIST_USER_IDS` and `ADMIN_USER_ID`.
3. Leave `TELEGRAM_API_URL` empty to use the standard `api.telegram.org` (50 MB upload
   limit; the optional 2 GB Local Bot API Server is a Docker compose profile — see
   "Deploying to a VPS").
4. The `/data/...` paths `.env.example` ships for `IG_COOKIES_FILE`, `DB_PATH` and
   `DOWNLOAD_DIR` are in-container paths for the Docker deployment. For local runs,
   override them in `.env.local` (`cp .env.local.example .env.local`) — the bot loads
   it from the repo root on top of `.env`, and any variable set there wins. Point
   `IG_COOKIES_FILE` there at the burner account's cookies file (see below).
5. `uv run python -m reelsbot`, then message the bot an Instagram link.

## Instagram cookies

Anonymous Instagram scraping no longer works: extraction needs the session cookies of a
logged-in account. Use a **dedicated burner account**, never a personal one.

1. Create/log into the burner account in a desktop browser (ideally a separate browser
   profile you keep logged in).
2. Install a cookies exporter extension (e.g. "Get cookies.txt LOCALLY") and export
   cookies for `instagram.com` in **Netscape format**.
3. Save the file and point `IG_COOKIES_FILE` in `.env` at it. In Docker, name it
   `instagram.txt` in the repo root instead — compose mounts it read-only (see
   "Deploying to a VPS").
4. When the bot reports `AuthExpired` (the admin gets a notification), repeat steps 1–3:
   log in again in the browser and re-export. Takes ~5 minutes.

Tips: don't log the burner account out in the browser (that invalidates the exported
session), and keep request volume low — the bot's cache and cooldowns exist to protect
the account.

## Deploying to a VPS

Requires Docker with the compose plugin. The stack is defined in `docker-compose.yml`:
the bot image is built from source on the VPS (`reelsbot:${BOT_VERSION:-dev}`, see
`docker/Dockerfile`), and the optional Local Bot API Server uses the official
`aiogram/telegram-bot-api` image.

1. Clone the repo and prepare the config:

   ```bash
   git clone <repo-url> && cd reels-downloader
   cp .env.example .env
   # fill in: BOT_TOKEN, WHITELIST_USER_IDS, ADMIN_USER_ID
   # keep the pre-filled /data/... paths — the container reads them via env_file
   ```

2. Put the burner account's cookies file (Netscape format, see "Instagram cookies")
   in the repo root as `instagram.txt` — compose mounts `./instagram.txt` read-only
   into the container at `/data/cookies/instagram.txt`.

3. Start the stack — two modes:

   **Cloud mode (default, no api_id/hash needed).** Uploads are capped at 50 MB per
   file, which covers typical reels/TikToks (5–40 MB with the H.264 formats the bot
   selects); larger videos fail with a user-facing error message.

   ```bash
   docker compose up -d --build
   ```

   **2 GB mode (Local Bot API Server).** Needs `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`
   from [my.telegram.org](https://my.telegram.org) — create the app from a residential
   or mobile-data IP in the same country as the account's phone number (datacenter/VPN
   IPs get a blank "ERROR"). Then in `.env` set the two values and
   `TELEGRAM_API_URL=http://telegram-bot-api:8081`, and start with the profile:

   ```bash
   docker compose --profile local-api up -d --build
   ```

4. Verify: `docker compose logs -f bot` should show "starting long polling", and the
   `/health` command (from the admin account) should report all checks green.

Switching between the modes later is just the `.env` change plus a restart. Cached
Telegram `file_id`s go stale across a switch; the bot detects that, drops the entry,
and re-downloads — no manual cache surgery needed.

To update a running deployment: `git pull && docker compose up -d --build` (add
`--profile local-api` in 2 GB mode).

### Deploying from the registry (no build on the VPS)

CI publishes the image to GHCR on every master push and release (see "Releases &
versioning"), so the VPS can pull instead of building. In `.env` set:

```bash
BOT_IMAGE=ghcr.io/darkartheme/reelsbot
BOT_VERSION=latest        # or X.Y.Z, or edge / X.Y.Z-dev.<sha> for master builds
```

then:

```bash
docker compose pull bot
docker compose up -d --no-build
```

If the GHCR package is private (the default on first push), the VPS needs
`docker login ghcr.io` with a GitHub personal access token that has `read:packages`;
alternatively make the package public in its GitHub settings and skip the login.

## Operations

- **`/health`** (admin only): the bot replies with its package versions, the yt-dlp /
  gallery-dl versions it resolves, cookies-file status, cache DB row count, and uptime.
  Run it first when something looks off.
- **Logs**: every link job logs under a `req=<id>` tag with the post `uid`, the requesting
  user, and `extract=`/`deliver=`/`total=` timings — grep the request id to follow one job
  end to end.
- **Retries**: a transient extraction failure (`ExtractionFailed`) is retried once
  automatically before the user sees an error. Stable failures (private post, dead cookies,
  rate limit) are not retried.
- **Shutdown**: on SIGINT/SIGTERM the bot stops polling, waits up to 30 s for in-flight
  downloads to finish delivering, then closes the cache DB. The compose file's
  `stop_grace_period` (45 s) is sized to let that complete.
- **Temp files**: each post downloads into its own temp dir, removed after delivery or on
  failure. On startup the bot also sweeps `DOWNLOAD_DIR` for `ig-*`/`tt-*` dirs a crashed
  run may have left behind (in Docker, `DOWNLOAD_DIR=/data/tmp` lives on the `video-cache`
  named volume, so leftovers survive a container restart and the sweep cleans them up).

## Upgrading yt-dlp / gallery-dl

Extraction breaking is a *when*, not an *if* — Instagram and TikTok change their sites, and
the fix nearly always ships in a new extractor release. Exact versions are pinned by
`uv.lock` (the pyprojects only set floors), so an upgrade is a lockfile change:

```bash
uv lock --upgrade-package yt-dlp --upgrade-package gallery-dl
uv sync
MEDIAGRAB_LIVE_TEST=1 IG_COOKIES_FILE=~/ig-cookies.txt \
    uv run pytest packages/mediagrab/tests/test_live_smoke.py -v   # verify against real sites
uv run pytest                                                      # unit suite still green
```

Commit the updated `uv.lock`, then redeploy (`docker compose up -d --build` — the image
installs from the lockfile with `--frozen`). Cutting a PATCH release of the bot for this is
the intended flow (see “Releases & versioning”).

When extraction breaks in production, try in this order: **1)** upgrade the tools as above;
**2)** if `/health` or the admin notification says `AuthExpired`, refresh the IG cookies
(section above); **3)** only then debug the wrappers themselves.

### Live smoke test

CI never touches Instagram or TikTok. To verify extraction against the real sites:

```bash
MEDIAGRAB_LIVE_TEST=1 IG_COOKIES_FILE=~/ig-cookies.txt \
    uv run pytest packages/mediagrab/tests/test_live_smoke.py -v
```

## Status

Phases 0–4, 6, and 7 done (scaffolding, library core, Instagram provider, bot MVP, cache +
politeness, hardening, TikTok provider). Phase 5 (Docker + VPS deploy) has its files ready
but is not yet live-verified on the VPS. See `plan.md` for the implementation roadmap and
`worklog.md` for the project history.
