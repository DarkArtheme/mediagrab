"""Map TikTok extractor stderr onto the mediagrab error taxonomy.

Unlike Instagram, the default TikTok setup is anonymous: a login-wall error
then means the post itself needs an account (age-gated, private) — that's
`PostUnavailable`, not `AuthExpired`. Only when a cookies file is actually
configured does a login wall mean the session died and the admin should
refresh it.
"""

from __future__ import annotations

from mediagrab.errors import (
    AuthExpired,
    ExtractionFailed,
    MediaGrabError,
    PostUnavailable,
    RateLimited,
)

_AUTH_PATTERNS = (
    "login required",
    "log in",
    "not logged in",
    "requires authentication",
    "unauthorized",
    "401",
)
_RATE_PATTERNS = (
    "429",
    "too many requests",
    "rate limit",
    "rate-limit",
    "throttl",
)
_GONE_PATTERNS = (
    "404",
    "not found",
    "private",
    "does not exist",
    "no longer available",
    "removed",
    "unavailable",
    "not available",
    "geo restricted",
    "geo-restricted",
)


def classify_failure(tool: str, stderr: str, *, cookies_configured: bool = False) -> MediaGrabError:
    """Build the taxonomy error matching a failed extractor run's stderr."""
    text = stderr.lower()
    tail = " | ".join(line.strip() for line in stderr.strip().splitlines()[-3:])[:500]

    if any(p in text for p in _AUTH_PATTERNS):
        if cookies_configured:
            return AuthExpired(f"{tool}: {tail}")
        return PostUnavailable(f"{tool}: {tail}")
    if any(p in text for p in _RATE_PATTERNS):
        return RateLimited(f"{tool}: {tail}")
    if any(p in text for p in _GONE_PATTERNS):
        return PostUnavailable(f"{tool}: {tail}")
    return ExtractionFailed(f"{tool} failed: {tail or 'no error output'}")
