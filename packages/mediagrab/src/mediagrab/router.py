"""Map a pasted URL to a provider and a stable post uid.

Parsing strips tracking junk (``igsh``/``igsi``/UTM query params, fragments)
and produces a canonical URL, so the same post always yields the same uid —
which the bot uses as the cache key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from mediagrab.errors import UnsupportedUrl
from mediagrab.providers.base import Provider

PostKind = Literal["reel", "post"]

_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}

# Optional username segment (share pages use /<user>/p/<code>/), then the link
# type, then the shortcode.
_INSTAGRAM_PATH = re.compile(
    r"^/(?:(?P<user>[A-Za-z0-9._]+)/)?(?P<segment>reel|reels|p|tv)/(?P<code>[A-Za-z0-9_-]+)/?$"
)

# /share/reel/<token>/ links carry a redirect token, not a shortcode; resolving
# them needs a network round-trip, so they are not supported.
_RESERVED_PREFIXES = {"share"}

_SEGMENT_KIND: dict[str, PostKind] = {"reel": "reel", "reels": "reel", "tv": "reel", "p": "post"}
_CANONICAL_SEGMENT = {"reel": "reel", "reels": "reel", "tv": "tv", "p": "p"}


@dataclass(frozen=True, slots=True)
class Route:
    """Where a URL should go: which provider, which post, what kind of post."""

    provider: str
    uid: str
    kind: PostKind
    canonical_url: str


def parse_url(url: str) -> Route:
    """Parse a pasted URL into a :class:`Route`, or raise :class:`UnsupportedUrl`."""
    text = url.strip()
    if not text:
        raise UnsupportedUrl(url)
    if "://" not in text:
        text = f"https://{text}"

    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise UnsupportedUrl(url)

    host = (parts.hostname or "").lower()
    if host in _INSTAGRAM_HOSTS:
        match = _INSTAGRAM_PATH.match(parts.path)
        if match and match["user"] not in _RESERVED_PREFIXES:
            segment = match["segment"]
            code = match["code"]
            canonical = f"https://www.instagram.com/{_CANONICAL_SEGMENT[segment]}/{code}/"
            return Route(
                provider="instagram",
                uid=code,
                kind=_SEGMENT_KIND[segment],
                canonical_url=canonical,
            )

    raise UnsupportedUrl(url)


class Router:
    """Registry mapping provider names to :class:`Provider` instances."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, name: str, provider: Provider) -> None:
        self._providers[name] = provider

    def resolve(self, url: str) -> tuple[Provider, Route]:
        """Return the provider responsible for ``url`` plus its parsed route."""
        route = parse_url(url)
        provider = self._providers.get(route.provider)
        if provider is None:
            raise UnsupportedUrl(url)
        return provider, route
