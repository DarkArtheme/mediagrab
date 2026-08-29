"""Instagram provider: reels via yt-dlp, ``/p/`` posts via gallery-dl with a
yt-dlp fallback for plain video posts."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from mediagrab.errors import ExtractionFailed, UnsupportedUrl
from mediagrab.models import MediaItem, MediaPost
from mediagrab.providers.instagram import gallerydl, ytdlp
from mediagrab.router import Route, parse_url

log = logging.getLogger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".webm"}


class InstagramProvider:
    """Turn an Instagram URL into a :class:`MediaPost`.

    Media lands in a fresh temp directory per resolve (under ``download_dir``
    when given); the caller owns cleanup of the returned files' directory.
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
        if route.provider != "instagram":
            raise UnsupportedUrl(url)

        if self._download_dir is not None:
            self._download_dir.mkdir(parents=True, exist_ok=True)
        dest_dir = Path(tempfile.mkdtemp(prefix=f"ig-{route.uid}-", dir=self._download_dir))

        if route.kind == "reel":
            return await self._resolve_video(route, dest_dir)

        try:
            post = await self._resolve_gallery(route, dest_dir)
        except ExtractionFailed as err:
            # gallery-dl choked outright; a plain video /p/ post is the usual cause.
            # Log the swallowed reason so a broken gallery-dl setup stays diagnosable.
            log.warning("gallery-dl failed for %s, falling back to yt-dlp: %s", route.uid, err)
            post = None
        if post is None:
            return await self._resolve_video(route, dest_dir)
        return post

    async def _resolve_video(self, route: Route, dest_dir: Path) -> MediaPost:
        path, info = await ytdlp.extract_video(
            route.canonical_url,
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

    async def _resolve_gallery(self, route: Route, dest_dir: Path) -> MediaPost | None:
        entries = await gallerydl.extract_gallery(
            route.canonical_url,
            dest_dir=dest_dir,
            cookies_file=self._cookies_file,
            timeout=self._timeout,
        )
        if not entries:
            return None

        items = []
        for path, meta in entries:
            is_video = path.suffix.lower() in _VIDEO_SUFFIXES
            items.append(
                MediaItem(
                    kind="video" if is_video else "photo",
                    path=path,
                    width=meta.get("width"),
                    height=meta.get("height"),
                    duration=meta.get("video_duration") if is_video else None,
                )
            )

        first_meta = entries[0][1]
        return MediaPost(
            items=items,
            caption=first_meta.get("description") or "",
            author=first_meta.get("username") or "",
            source_url=route.canonical_url,
            uid=route.uid,
        )
