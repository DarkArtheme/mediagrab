"""Provider protocol implemented by every platform backend."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mediagrab.models import MediaPost


@runtime_checkable
class Provider(Protocol):
    """A backend that turns a supported URL into a :class:`MediaPost`.

    Implementations download media to local files and must raise only errors
    from :mod:`mediagrab.errors` — no extractor exceptions may leak through.
    """

    async def resolve(self, url: str) -> MediaPost:
        """Download the post at ``url`` and return it with its media on disk."""
        ...
