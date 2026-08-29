"""Map extractor stderr onto the mediagrab error taxonomy.

Auth patterns are checked before rate-limit ones on purpose: yt-dlp's usual
dead-cookies message ("rate-limit reached or login required") mentions both,
and with cookies configured the actionable cause is almost always the cookies
— the admin gets notified and can refresh them.
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
    "login page",
    "not logged in",
    "logged out",
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
)


def classify_failure(tool: str, stderr: str) -> MediaGrabError:
    """Build the taxonomy error matching a failed extractor run's stderr."""
    text = stderr.lower()
    tail = " | ".join(line.strip() for line in stderr.strip().splitlines()[-3:])[:500]

    if any(p in text for p in _AUTH_PATTERNS):
        return AuthExpired(f"{tool}: {tail}")
    if any(p in text for p in _RATE_PATTERNS):
        return RateLimited(f"{tool}: {tail}")
    if any(p in text for p in _GONE_PATTERNS):
        return PostUnavailable(f"{tool}: {tail}")
    return ExtractionFailed(f"{tool} failed: {tail or 'no error output'}")
