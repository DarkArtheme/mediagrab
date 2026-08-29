"""Photo/carousel extraction via the gallery-dl subprocess.

``--write-metadata`` drops a ``<file>.json`` sidecar next to every downloaded
file; items are ordered by the sidecar's ``num`` field (position in the
carousel).
"""

from __future__ import annotations

import json
from pathlib import Path

from mediagrab import _proc
from mediagrab.providers.instagram._classify import classify_failure

_SKIP_SUFFIXES = {".part", ".json", ".ytdl"}


async def extract_gallery(
    url: str, *, dest_dir: Path, cookies_file: Path | None, timeout: float
) -> list[tuple[Path, dict]]:
    """Download all items of the post at ``url`` into ``dest_dir``.

    Returns ``(file path, sidecar metadata)`` pairs in carousel order; an empty
    list means gallery-dl found nothing it could handle (e.g. a video-only
    post), which the provider treats as a cue to fall back to yt-dlp.
    """
    cmd = [
        _proc.tool_path("gallery-dl"),
        "--write-metadata",
        "--directory",
        str(dest_dir),
    ]
    if cookies_file is not None:
        cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)

    result = await _proc.run_tool(cmd, timeout=timeout)
    if result.returncode != 0:
        raise classify_failure("gallery-dl", result.stderr)

    entries: list[tuple[Path, dict]] = []
    for media_path in sorted(dest_dir.iterdir()):
        if media_path.suffix in _SKIP_SUFFIXES or media_path.name.startswith("."):
            continue
        sidecar = media_path.with_name(media_path.name + ".json")
        meta: dict = {}
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text())
            except json.JSONDecodeError:
                meta = {}
        entries.append((media_path, meta))

    entries.sort(key=lambda entry: entry[1].get("num") or 0)
    return entries
