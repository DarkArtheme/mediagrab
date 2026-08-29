"""Core data models shared by all providers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MediaKind = Literal["video", "photo"]


@dataclass(slots=True)
class MediaItem:
    """One downloaded media file (a video or a photo)."""

    kind: MediaKind
    path: Path
    width: int | None = None
    height: int | None = None
    duration: float | None = None


@dataclass(slots=True)
class MediaPost:
    """A resolved post: downloaded media plus its text description."""

    items: list[MediaItem]
    caption: str
    author: str
    source_url: str
    uid: str
