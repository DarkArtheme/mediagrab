"""Resolve TikTok share links (vm./vt.tiktok.com, /t/) to the real post URL.

Share links hide the post id and the video/photo kind behind an HTTP
redirect. One anonymous GET per hop (no cookies needed) reads the
``Location`` header without downloading the page body.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request
from urllib.parse import urljoin

from mediagrab.errors import ExtractionFailed, PostUnavailable

_MAX_HOPS = 5
# TikTok answers bare urllib requests with 403s at times; a browser UA keeps
# the redirect endpoint happy.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None  # make every 3xx surface as HTTPError instead of being followed


def _next_hop(url: str, timeout: float) -> str | None:
    """Return the redirect target of ``url``, or None if it doesn't redirect."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with opener.open(request, timeout=timeout):
            return None
    except urllib.error.HTTPError as err:
        if 300 <= err.code < 400:
            location = err.headers.get("Location")
            return urljoin(url, location) if location else None
        if err.code == 404:
            raise PostUnavailable(f"short link returned HTTP 404: {url}") from err
        raise ExtractionFailed(f"short link returned HTTP {err.code}: {url}") from err
    except (urllib.error.URLError, TimeoutError) as err:
        raise ExtractionFailed(f"could not resolve short link {url}: {err}") from err


async def resolve_short_link(url: str, *, is_post_url, timeout: float = 15.0) -> str:
    """Follow redirects from ``url`` until ``is_post_url(hop)`` accepts one.

    Raises :class:`PostUnavailable` when the chain ends somewhere else (an
    expired share link redirects to the TikTok homepage or an error page).
    """
    current = url
    for _ in range(_MAX_HOPS):
        target = await asyncio.to_thread(_next_hop, current, timeout)
        if target is None:
            raise PostUnavailable(f"short link did not lead to a post: {url} -> {current}")
        if is_post_url(target):
            return target
        current = target
    raise PostUnavailable(f"short link redirect chain too long: {url}")
