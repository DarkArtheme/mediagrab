"""Core data models shared by all providers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MediaKind = Literal["video", "photo"]


@dataclass(slots=True)
class MediaItem:
    """One downloaded media file (a video or a photo)."""

    kind: MediaKind
    path: Path
    width: int | None = None
    height: int | None = None
    duration: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation; ``path`` becomes a string."""
        return {
            "kind": self.kind,
            "path": str(self.path),
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
        }


@dataclass(slots=True)
class MediaPost:
    """A resolved post: downloaded media plus its text description."""

    items: list[MediaItem]
    caption: str
    author: str
    source_url: str
    uid: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for persisting alongside the media files."""
        return {
            "uid": self.uid,
            "source_url": self.source_url,
            "author": self.author,
            "caption": self.caption,
            "items": [item.to_dict() for item in self.items],
        }
