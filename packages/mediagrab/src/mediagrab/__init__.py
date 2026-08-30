"""mediagrab: turn a social-media URL into downloaded media plus its text description."""

from mediagrab.models import MediaItem, MediaKind, MediaPost
from mediagrab.providers.base import Provider
from mediagrab.providers.instagram import InstagramProvider
from mediagrab.providers.tiktok import TikTokProvider
from mediagrab.router import PostKind, Route, Router, parse_url

__version__ = "0.1.0"

__all__ = [
    "InstagramProvider",
    "TikTokProvider",
    "MediaItem",
    "MediaKind",
    "MediaPost",
    "PostKind",
    "Provider",
    "Route",
    "Router",
    "parse_url",
]
