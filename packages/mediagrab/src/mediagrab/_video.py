"""Post-download video normalization: make every video Telegram-playable.

Telegram clients only decode H.264 MP4 inline; Instagram serves some carousel
videos exclusively as VP9 with no H.264 variant at all (so gallery-dl cannot
pick a better format — none exists), and the yt-dlp format-selector fallback
can land on VP9/AV1 too. Such a file uploads fine and renders as a video
message, but never plays. After download every video item is probed with
ffprobe and re-encoded with ffmpeg when it is not already H.264 MP4; the
probe also backfills missing width/height/duration.

Normalization is best-effort: when ffprobe/ffmpeg is missing or fails, the
original file is delivered unchanged instead of failing the whole post.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mediagrab import _proc
from mediagrab.errors import MediaGrabError
from mediagrab.models import MediaItem, MediaPost

log = logging.getLogger(__name__)

_PLAYABLE_VIDEO_CODECS = {"h264"}
_PLAYABLE_SUFFIXES = {".mp4", ".m4v"}


async def normalize_post(post: MediaPost, *, timeout: float) -> MediaPost:
    """Probe/transcode every video item of ``post`` in place; return it."""
    for item in post.items:
        if item.kind == "video":
            await _normalize_item(item, timeout=timeout)
    return post


async def _normalize_item(item: MediaItem, *, timeout: float) -> None:
    probe = await _probe(item.path, timeout=timeout)
    if probe is None:
        return

    item.width = item.width or probe.get("width")
    item.height = item.height or probe.get("height")
    item.duration = item.duration or probe.get("duration")

    vcodec = probe.get("vcodec")
    if vcodec in _PLAYABLE_VIDEO_CODECS and item.path.suffix.lower() in _PLAYABLE_SUFFIXES:
        return

    log.info("transcoding %s (codec %s) to H.264 for Telegram", item.path.name, vcodec)
    transcoded = await _transcode(item.path, timeout=timeout)
    if transcoded is not None:
        item.path.unlink(missing_ok=True)
        item.path = transcoded


async def _probe(path: Path, *, timeout: float) -> dict | None:
    cmd = [
        _proc.tool_path("ffprobe"),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        result = await _proc.run_tool(cmd, timeout=timeout)
    except MediaGrabError as err:
        log.warning("ffprobe unavailable, delivering %s as-is: %s", path.name, err)
        return None
    if result.returncode != 0:
        log.warning("ffprobe failed for %s: %s", path.name, result.stderr.strip())
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        log.warning("ffprobe produced unparseable JSON for %s", path.name)
        return None

    video = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    try:
        duration = float(data.get("format", {}).get("duration", ""))
    except ValueError:
        duration = None
    return {
        "vcodec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": duration,
    }


async def _transcode(path: Path, *, timeout: float) -> Path | None:
    out = path.with_name(path.stem + ".h264.mp4")
    cmd = [
        _proc.tool_path("ffmpeg"),
        "-y",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        # libx264 needs even dimensions; yuv420p is what mobile decoders expect.
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out),
    ]
    try:
        result = await _proc.run_tool(cmd, timeout=timeout)
    except MediaGrabError as err:
        log.warning("ffmpeg unavailable, delivering %s as-is: %s", path.name, err)
        return None
    if result.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        log.warning("ffmpeg failed for %s: %s", path.name, result.stderr.strip())
        out.unlink(missing_ok=True)
        return None
    return out
