"""TikTok provider: videos via yt-dlp, photo slideshows via gallery-dl.

Share links (``vt.tiktok.com/…``) are resolved to the real post URL first, so
``MediaPost.uid`` is always the numeric post id — the cache converges even
when different users paste different share tokens for the same post.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from mediagrab import _video
from mediagrab.errors import ExtractionFailed, MediaGrabError, UnsupportedUrl
from mediagrab.models import MediaItem, MediaPost
from mediagrab.providers.tiktok import _redirect, gallerydl, ytdlp
from mediagrab.router import Route, parse_url

log = logging.getLogger(__name__)


def _is_post_url(url: str) -> bool:
    try:
        route = parse_url(url)
    except UnsupportedUrl:
        return False
    return route.provider == "tiktok" and route.kind != "unknown"


class TikTokProvider:
    """Turn a TikTok URL into a :class:`MediaPost`.

    Media lands in a fresh temp directory per resolve (under ``download_dir``
    when given); the caller owns cleanup of the returned files' directory.
    Anonymous by default — ``cookies_file`` is an escape hatch for the day
    TikTok stops serving logged-out requests.
    """

    def __init__(
        self,
        *,
        cookies_file: Path | None = None,
        download_dir: Path | None = None,
        timeout: float = 600.0,
    ) -> None:
        self._cookies_file = cookies_file
        self._download_dir = download_dir
        self._timeout = timeout

    async def resolve(self, url: str) -> MediaPost:
        route = parse_url(url)
        if route.provider != "tiktok":
            raise UnsupportedUrl(url)

        if route.kind == "unknown":
            resolved_url = await _redirect.resolve_short_link(
                route.canonical_url, is_post_url=_is_post_url
            )
            route = parse_url(resolved_url)

        if self._download_dir is not None:
            self._download_dir.mkdir(parents=True, exist_ok=True)
        post_id = route.uid.rpartition(":")[2]
        dest_dir = Path(tempfile.mkdtemp(prefix=f"tt-{post_id}-", dir=self._download_dir))

        try:
            post = await self._resolve_in(route, dest_dir)
            return await _video.normalize_post(post, timeout=self._timeout)
        except BaseException:
            # On success the caller owns dest_dir; on failure nobody would.
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise

    async def _resolve_in(self, route: Route, dest_dir: Path) -> MediaPost:
        if route.kind == "video":
            try:
                return await self._resolve_video(route.canonical_url, route, dest_dir)
            except ExtractionFailed as err:
                # A slideshow shared under a /video/ path makes yt-dlp choke;
                # gallery-dl handles both path shapes.
                log.warning("yt-dlp failed for %s, trying gallery-dl: %s", route.uid, err)
                try:
                    post = self._build_gallery_post(
                        await gallerydl.extract_gallery(
                            route.canonical_url,
                            dest_dir=dest_dir,
                            cookies_file=self._cookies_file,
                            timeout=self._timeout,
                        ),
                        route,
                    )
                except MediaGrabError:
                    post = None
                if post is None:
                    raise err
                return post

        try:
            entries = await gallerydl.extract_gallery(
                route.canonical_url,
                dest_dir=dest_dir,
                cookies_file=self._cookies_file,
                timeout=self._timeout,
            )
        except ExtractionFailed as err:
            log.warning("gallery-dl failed for %s, falling back to yt-dlp: %s", route.uid, err)
            entries = []
        post = self._build_gallery_post(entries, route)
        if post is None:
            # yt-dlp's TikTok extractor only matches /video/ paths.
            video_url = route.canonical_url.replace("/photo/", "/video/")
            return await self._resolve_video(video_url, route, dest_dir)
        return post

    async def _resolve_video(self, url: str, route: Route, dest_dir: Path) -> MediaPost:
        path, info = await ytdlp.extract_video(
            url,
            dest_dir=dest_dir,
            cookies_file=self._cookies_file,
            timeout=self._timeout,
        )
        item = MediaItem(
            kind="video",
            path=path,
            width=info.get("width"),
            height=info.get("height"),
            duration=info.get("duration"),
        )
        return MediaPost(
            items=[item],
            caption=info.get("description") or "",
            author=info.get("uploader") or info.get("uploader_id") or "",
            source_url=route.canonical_url,
            uid=route.uid,
        )

    def _build_gallery_post(
        self, entries: list[tuple[Path, dict]], route: Route
    ) -> MediaPost | None:
        if not entries:
            return None

        items = [
            MediaItem(kind="photo", path=path, width=meta.get("width"), height=meta.get("height"))
            for path, meta in entries
        ]
        first_meta = entries[0][1]
        return MediaPost(
            items=items,
            caption=first_meta.get("desc") or "",
            author=first_meta.get("user") or "",
            source_url=route.canonical_url,
            uid=route.uid,
        )
