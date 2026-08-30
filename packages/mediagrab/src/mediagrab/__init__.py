"""mediagrab: turn a social-media URL into downloaded media plus its text description."""

from importlib.metadata import PackageNotFoundError, version

from mediagrab.grab import GrabResult, MediaGrab
from mediagrab.models import MediaItem, MediaKind, MediaPost
from mediagrab.providers.base import Provider
from mediagrab.providers.instagram import InstagramProvider
from mediagrab.providers.tiktok import TikTokProvider
from mediagrab.router import PostKind, Route, Router, parse_url

# Single source of truth is pyproject.toml; bump versions via scripts/release.sh.
try:
    __version__ = version("mediagrab")
except PackageNotFoundError:  # imported from a checkout without an install
    __version__ = "0.0.0+unknown"

__all__ = [
    "GrabResult",
    "InstagramProvider",
    "MediaGrab",
    "MediaItem",
    "MediaKind",
    "MediaPost",
    "PostKind",
    "Provider",
    "Route",
    "Router",
    "TikTokProvider",
    "parse_url",
]
