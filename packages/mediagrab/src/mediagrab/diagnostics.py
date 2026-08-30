"""Self-check helpers for consumers (e.g. a bot's /health command)."""

from __future__ import annotations

from mediagrab import _proc
from mediagrab.errors import ExtractionFailed

EXTRACTOR_TOOLS = ("yt-dlp", "gallery-dl")


async def tool_version(tool: str, *, timeout: float = 10.0) -> str | None:
    """Return the first line of ``tool --version`` output, or None when the
    tool is missing, hangs, or exits non-zero."""
    try:
        result = await _proc.run_tool([_proc.tool_path(tool), "--version"], timeout=timeout)
    except ExtractionFailed:
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output.splitlines()[0] if output else None
