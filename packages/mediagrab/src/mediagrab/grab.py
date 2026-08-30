"""High-level facade for standalone use (scripts, AI-agent pipelines).

:class:`MediaGrab` hides the router/provider wiring behind two calls:
``fetch(url)`` for one post and ``fetch_many(urls)`` for a batch. Batch
results never fail fast — each URL yields a :class:`GrabResult` carrying
either the downloaded post or the error, so one dead link cannot abort an
agent's whole list.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mediagrab.errors import MediaGrabError
from mediagrab.models import MediaPost
from mediagrab.providers.instagram import InstagramProvider
from mediagrab.providers.tiktok import TikTokProvider
from mediagrab.router import Router


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


@dataclass(slots=True)
class GrabResult:
    """Outcome for one URL in a batch: the post on success, the error otherwise."""

    url: str
    post: MediaPost | None = None
    error: MediaGrabError | None = None

    @property
    def ok(self) -> bool:
        return self.post is not None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation (one line of the CLI's JSONL output)."""
        out: dict[str, Any] = {"url": self.url, "ok": self.ok}
        if self.post is not None:
            out["post"] = self.post.to_dict()
        if self.error is not None:
            out["error"] = {"type": type(self.error).__name__, "message": str(self.error)}
        return out


class MediaGrab:
    """Turn Instagram/TikTok URLs into downloaded media plus captions.

    Downloads land in fresh per-post temp directories under ``download_dir``
    (system tmp when omitted); the caller owns cleanup. Instagram needs
    session cookies (Netscape ``cookies.txt``) — passed explicitly or picked
    up from ``IG_COOKIES_FILE``; TikTok works anonymously, with
    ``TIKTOK_COOKIES_FILE`` as the escape hatch.
    """

    def __init__(
        self,
        *,
        download_dir: Path | None = None,
        instagram_cookies: Path | None = None,
        tiktok_cookies: Path | None = None,
        timeout: float = 600.0,
        router: Router | None = None,
    ) -> None:
        if router is None:
            if instagram_cookies is None:
                instagram_cookies = _env_path("IG_COOKIES_FILE")
            if tiktok_cookies is None:
                tiktok_cookies = _env_path("TIKTOK_COOKIES_FILE")
            router = Router()
            router.register(
                "instagram",
                InstagramProvider(
                    cookies_file=instagram_cookies,
                    download_dir=download_dir,
                    timeout=timeout,
                ),
            )
            router.register(
                "tiktok",
                TikTokProvider(
                    cookies_file=tiktok_cookies,
                    download_dir=download_dir,
                    timeout=timeout,
                ),
            )
        self.router = router

    async def fetch(self, url: str) -> MediaPost:
        """Download one post, raising a :mod:`mediagrab.errors` error on failure."""
        provider, _route = self.router.resolve(url)
        return await provider.resolve(url)

    async def fetch_many(self, urls: Sequence[str], *, concurrency: int = 2) -> list[GrabResult]:
        """Download a batch, at most ``concurrency`` posts at a time.

        Results come back in input order. :class:`MediaGrabError` failures are
        captured per URL; anything else is a provider-contract bug and
        propagates.
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def grab_one(url: str) -> GrabResult:
            async with semaphore:
                try:
                    return GrabResult(url=url, post=await self.fetch(url))
                except MediaGrabError as err:
                    return GrabResult(url=url, error=err)

        return list(await asyncio.gather(*(grab_one(url) for url in urls)))
