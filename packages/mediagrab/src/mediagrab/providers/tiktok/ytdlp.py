"""TikTok video extraction via the yt-dlp subprocess.

One call does both jobs: ``--dump-json --no-simulate`` downloads the video and
prints its metadata JSON to stdout. Anonymous by default; a cookies file is
threaded through only when configured.
"""

from __future__ import annotations

import json
from pathlib import Path

from mediagrab import _proc
from mediagrab.errors import ExtractionFailed
from mediagrab.providers.tiktok._classify import classify_failure

_SKIP_SUFFIXES = {".part", ".json", ".ytdl"}

# Telegram clients only decode H.264 inline, but yt-dlp's default pick for
# TikTok is the bytevc1 (H.265) 1080p format. Prefer TikTok's clean H.264
# progressive formats (the watermarked "download" format is also H.264 but
# carries preference=-2, so it only wins when nothing better exists), then
# anything at all so an exotic post still downloads instead of erroring out.
_FORMAT_SELECTOR = "b[vcodec^=h264]/bv*[vcodec^=h264]+ba/b"


async def extract_video(
    url: str, *, dest_dir: Path, cookies_file: Path | None, timeout: float
) -> tuple[Path, dict]:
    """Download the video at ``url`` into ``dest_dir``; return (file path, metadata)."""
    cmd = [
        _proc.tool_path("yt-dlp"),
        "--no-warnings",
        "--no-progress",
        "--dump-json",
        "--no-simulate",
        "--format",
        _FORMAT_SELECTOR,
        "--merge-output-format",
        "mp4",
        "--output",
        str(dest_dir / "%(id)s.%(ext)s"),
    ]
    if cookies_file is not None:
        cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)

    result = await _proc.run_tool(cmd, timeout=timeout)
    if result.returncode != 0:
        raise classify_failure("yt-dlp", result.stderr, cookies_configured=cookies_file is not None)

    lines = result.stdout.strip().splitlines()
    try:
        info: dict = json.loads(lines[0])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ExtractionFailed("yt-dlp produced no parseable metadata JSON") from exc

    video_id = str(info.get("id", ""))
    files = [p for p in dest_dir.glob(f"{video_id}.*") if p.suffix not in _SKIP_SUFFIXES]
    if not files:
        raise ExtractionFailed(f"yt-dlp reported success but produced no file for id {video_id!r}")
    return files[0], info
