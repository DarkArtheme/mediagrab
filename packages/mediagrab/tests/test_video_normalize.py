"""Video normalization tests: ffprobe/ffmpeg are faked by monkeypatching
mediagrab._proc.run_tool, the same way provider tests fake the extractors."""

import json
from pathlib import Path

from mediagrab import _proc, _video
from mediagrab._proc import ToolResult
from mediagrab.errors import ExtractionFailed
from mediagrab.models import MediaItem, MediaPost


def _post(tmp_path: Path, *items: MediaItem) -> MediaPost:
    return MediaPost(items=list(items), caption="", author="", source_url="https://x", uid="uid")


def _probe_payload(vcodec: str) -> str:
    return json.dumps(
        {
            "streams": [
                {"codec_type": "video", "codec_name": vcodec, "width": 1080, "height": 1350}
            ],
            "format": {"duration": "4.4"},
        }
    )


def install_fakes(monkeypatch, *, ffprobe, ffmpeg=None):
    async def fake_run_tool(cmd, *, timeout):
        tool = Path(cmd[0]).name
        handler = ffprobe if tool == "ffprobe" else ffmpeg
        assert handler is not None, f"unexpected {tool} call"
        return handler(list(cmd))

    monkeypatch.setattr(_proc, "run_tool", fake_run_tool)


async def test_h264_video_untouched_and_backfilled(monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"h264")
    install_fakes(monkeypatch, ffprobe=lambda cmd: ToolResult(0, _probe_payload("h264"), ""))
    item = MediaItem(kind="video", path=src)

    await _video.normalize_post(_post(tmp_path, item), timeout=5)

    assert item.path == src
    assert (item.width, item.height, item.duration) == (1080, 1350, 4.4)


async def test_photos_never_probed(monkeypatch, tmp_path):
    install_fakes(monkeypatch, ffprobe=None)  # any probe would assert
    item = MediaItem(kind="photo", path=tmp_path / "p.jpg")

    await _video.normalize_post(_post(tmp_path, item), timeout=5)

    assert item.path.name == "p.jpg"


async def test_vp9_video_transcoded(monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"vp9")

    def ffmpeg(cmd):
        Path(cmd[-1]).write_bytes(b"h264")
        return ToolResult(0, "", "")

    install_fakes(
        monkeypatch, ffprobe=lambda cmd: ToolResult(0, _probe_payload("vp9"), ""), ffmpeg=ffmpeg
    )
    item = MediaItem(kind="video", path=src)

    await _video.normalize_post(_post(tmp_path, item), timeout=5)

    assert item.path == tmp_path / "v.h264.mp4"
    assert item.path.read_bytes() == b"h264"
    assert not src.exists()


async def test_failed_transcode_keeps_original(monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"vp9")
    install_fakes(
        monkeypatch,
        ffprobe=lambda cmd: ToolResult(0, _probe_payload("vp9"), ""),
        ffmpeg=lambda cmd: ToolResult(1, "", "encoder exploded"),
    )
    item = MediaItem(kind="video", path=src)

    await _video.normalize_post(_post(tmp_path, item), timeout=5)

    assert item.path == src
    assert src.exists()


async def test_missing_ffprobe_keeps_original(monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"vp9")

    async def fake_run_tool(cmd, *, timeout):
        raise ExtractionFailed("ffprobe is not installed or not on PATH")

    monkeypatch.setattr(_proc, "run_tool", fake_run_tool)
    item = MediaItem(kind="video", path=src)

    await _video.normalize_post(_post(tmp_path, item), timeout=5)

    assert item.path == src


async def test_sidecar_metadata_wins_over_probe(monkeypatch, tmp_path):
    src = tmp_path / "v.mp4"
    src.write_bytes(b"h264")
    install_fakes(monkeypatch, ffprobe=lambda cmd: ToolResult(0, _probe_payload("h264"), ""))
    item = MediaItem(kind="video", path=src, width=720, height=900, duration=7.2)

    await _video.normalize_post(_post(tmp_path, item), timeout=5)

    assert (item.width, item.height, item.duration) == (720, 900, 7.2)
