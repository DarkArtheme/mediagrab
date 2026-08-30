# mediagrab

A standalone Python library (and CLI) that turns an Instagram or TikTok URL into
downloaded media files plus the post's text description. Built for pipelines —
including AI agents — that take a list of links, download them, and analyze the
videos.

Supported:

- **Instagram**: Reels → video; `/p/` posts → photo/mixed carousels.
- **TikTok**: videos and photo slideshows, including `vm.`/`vt.` share links.

Extraction is delegated to [yt-dlp](https://github.com/yt-dlp/yt-dlp) and
[gallery-dl](https://github.com/mikf/gallery-dl) (installed automatically as
dependencies). No raw scraping.

## Install

Requires Python ≥ 3.12. `ffmpeg` on PATH is recommended (yt-dlp uses it to
merge/remux streams).

```bash
# from a checkout of this monorepo
pip install ./packages/mediagrab

# or straight from git
pip install "mediagrab @ git+https://<your-git-host>/reels-downloader.git#subdirectory=packages/mediagrab"
```

## Credentials

- **Instagram requires session cookies** (anonymous scraping is dead). Export a
  Netscape `cookies.txt` from a logged-in burner account and pass it via the
  `IG_COOKIES_FILE` env var, the `instagram_cookies=` argument, or `--ig-cookies`.
- **TikTok works anonymously**; `TIKTOK_COOKIES_FILE` / `tiktok_cookies=` exist
  as an escape hatch.

## Python API

```python
import asyncio
from pathlib import Path

from mediagrab import MediaGrab


async def main() -> None:
    grabber = MediaGrab(
        download_dir=Path("downloads"),  # default: system temp
        instagram_cookies=Path("cookies.txt"),  # default: $IG_COOKIES_FILE
    )

    # One URL → MediaPost (raises a mediagrab.errors error on failure).
    post = await grabber.fetch("https://www.instagram.com/reel/DZu6cdBI2-A/")
    print(post.caption, post.author)
    for item in post.items:
        print(item.kind, item.path, item.duration)

    # A batch → per-URL results, never fail-fast: one dead link cannot
    # abort the rest of an agent's list.
    results = await grabber.fetch_many(
        [
            "https://www.instagram.com/reel/DZu6cdBI2-A/",
            "https://www.tiktok.com/@user/video/7301234567890123456",
        ],
        concurrency=2,
    )
    for result in results:
        if result.ok:
            print("ok", result.post.uid, [str(i.path) for i in result.post.items])
        else:
            print("failed", result.url, type(result.error).__name__)


asyncio.run(main())
```

`MediaPost.to_dict()` / `GrabResult.to_dict()` give JSON-safe dicts, handy for
persisting metadata next to the downloaded files.

Each post is downloaded into a **fresh temp directory** under `download_dir`;
the caller owns cleanup (delete the parent directory of the item paths when
done with the files).

### Data model

```
MediaPost = { items: list[MediaItem], caption: str, author: str, source_url: str, uid: str }
MediaItem = { kind: "video" | "photo", path: Path, width/height/duration: optional }
```

`uid` is stable per post (Instagram shortcode / `tiktok:<post id>`), so it works
as a dedup/cache key across differently-shaped links to the same post.

### Errors

All failures are subclasses of `mediagrab.errors.MediaGrabError`:
`UnsupportedUrl`, `PostUnavailable`, `AuthExpired` (refresh the Instagram
cookies), `RateLimited`, `ExtractionFailed`. Extractor exceptions never leak
through.

## CLI (for shelling out from an agent)

```bash
mediagrab URL [URL ...] [--input urls.txt] [--out DIR] \
    [--ig-cookies FILE] [--concurrency N] [--timeout SECONDS]
```

Prints one JSON object per URL (JSONL) to stdout — progress goes to stderr —
so the output is directly machine-readable:

```bash
$ mediagrab --input urls.txt --out downloads --ig-cookies cookies.txt
{"url": "https://www.instagram.com/reel/…", "ok": true, "post": {"uid": "…", "source_url": "…", "author": "…", "caption": "…", "items": [{"kind": "video", "path": "downloads/ig-…/….mp4", "width": 1080, "height": 1920, "duration": 12.3}]}}
{"url": "https://vt.tiktok.com/…", "ok": false, "error": {"type": "PostUnavailable", "message": "…"}}
```

`--input` takes one URL per line (`-` for stdin; blank lines and `#` comments
ignored). Exit code: `0` all succeeded, `1` some failed, `2` bad invocation.
`python -m mediagrab` is an alias.

## Using it from an AI agent

Typical loop: feed the agent a list of links → `fetch_many` (or the CLI) →
for each successful result, send `post.caption` plus the video/photo files to
your model for analysis → store the extracted info keyed by `post.uid`. Keep
`concurrency` low (the default is 2) to stay under the platforms' rate limits,
and treat `AuthExpired` as "refresh the Instagram cookies", not a retry.
