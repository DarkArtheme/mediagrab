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
image built and pushed to `ghcr.io/<owner>/reelsbot` as `X.Y.Z`, `X.Y`, and `latest`
(the version is also stamped into the image's `org.opencontainers.image.version` label).
Local compose builds tag the image `reelsbot:${BOT_VERSION:-dev}`.

### Running the bot locally

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and put the token in
   `.env` as `BOT_TOKEN`.
2. Find your numeric Telegram user id (e.g. message [@userinfobot](https://t.me/userinfobot))
   and put it in `WHITELIST_USER_IDS` and `ADMIN_USER_ID`.
3. Leave `TELEGRAM_API_URL` empty to use the standard `api.telegram.org` (50 MB upload
   limit; the 2 GB Local Bot API Server arrives with the Docker setup).
4. Point `IG_COOKIES_FILE` at the burner account's cookies file (see below).
5. `uv run python -m reelsbot`, then message the bot an Instagram link.

## Instagram cookies

Anonymous Instagram scraping no longer works: extraction needs the session cookies of a
logged-in account. Use a **dedicated burner account**, never a personal one.

1. Create/log into the burner account in a desktop browser (ideally a separate browser
   profile you keep logged in).
2. Install a cookies exporter extension (e.g. "Get cookies.txt LOCALLY") and export
   cookies for `instagram.com` in **Netscape format**.
3. Save the file and point `IG_COOKIES_FILE` in `.env` at it. In Docker it is mounted as
   a read-only volume.
4. When the bot reports `AuthExpired` (the admin gets a notification), repeat steps 1–3:
   log in again in the browser and re-export. Takes ~5 minutes.

Tips: don't log the burner account out in the browser (that invalidates the exported
session), and keep request volume low — the bot's cache and cooldowns exist to protect
the account.

### Live smoke test

CI never touches Instagram or TikTok. To verify extraction against the real sites:

```bash
MEDIAGRAB_LIVE_TEST=1 IG_COOKIES_FILE=~/ig-cookies.txt \
    uv run pytest packages/mediagrab/tests/test_live_smoke.py -v
```

## Status

Phases 0–4 and 7 done (scaffolding, library core, Instagram provider, bot MVP, cache +
politeness, TikTok provider). See `plan.md` for the implementation roadmap and
`worklog.md` for the project history.
