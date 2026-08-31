"""Instagram provider tests: subprocess calls are faked by monkeypatching
mediagrab._proc.run_tool; the fakes write files the way the real tools would."""

import json
from pathlib import Path

import pytest

from mediagrab import _proc
from mediagrab._proc import ToolResult
from mediagrab.errors import (
    AuthExpired,
    ExtractionFailed,
    PostUnavailable,
    RateLimited,
    UnsupportedUrl,
)
from mediagrab.providers.instagram.provider import InstagramProvider

FIXTURES = Path(__file__).parent / "fixtures"

REEL_URL = "https://www.instagram.com/reel/DZu6cdBI2-A/?igsi=ZTAxeWV0bjcxZmIy"
POST_URL = "https://www.instagram.com/p/DWTPjRXE5WS/"

YTDLP_INFO = json.loads((FIXTURES / "ytdlp_reel.json").read_text())
SIDECAR_META = json.loads((FIXTURES / "gallerydl_sidecar.json").read_text())

# The dead-cookies message yt-dlp actually prints (mentions rate-limit AND login).
YTDLP_LOGIN_WALL = (
    "ERROR: [Instagram] DZu6cdBI2-A: Requested content is not available, "
    "rate-limit reached or login required. Use --cookies for authentication"
)


def _flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def fake_ytdlp_ok(cmd: list[str]) -> ToolResult:
    dest = Path(_flag_value(cmd, "--output")).parent
    (dest / f"{YTDLP_INFO['id']}.mp4").write_bytes(b"video-bytes")
    return ToolResult(0, json.dumps(YTDLP_INFO), "")


def fake_gallerydl_items(cmd: list[str], names_and_nums: list[tuple[str, int]]) -> ToolResult:
    dest = Path(_flag_value(cmd, "--directory"))
    for name, num in names_and_nums:
        ext = name.rsplit(".", 1)[-1]
        meta = {**SIDECAR_META, "num": num, "extension": ext}
        if ext == "mp4":
            meta["video_duration"] = 7.2
        (dest / name).write_bytes(b"media-bytes")
        (dest / f"{name}.json").write_text(json.dumps(meta))
    return ToolResult(0, "", "")


def fake_ffprobe(cmd: list[str], *, vcodec: str = "h264") -> ToolResult:
    payload = {
        "streams": [{"codec_type": "video", "codec_name": vcodec, "width": 1080, "height": 1350}],
        "format": {"duration": "3.57"},
    }
    return ToolResult(0, json.dumps(payload), "")


def install_fakes(monkeypatch, *, ytdlp=None, gallerydl=None, ffprobe=fake_ffprobe, ffmpeg=None):
    """Fake extractor subprocesses; ``calls`` records only yt-dlp/gallery-dl.

    Video normalization (ffprobe/ffmpeg) is faked separately and kept out of
    ``calls`` so extractor-invocation assertions stay about extractors; by
    default every probed video reports H.264 (no transcode) and any ffmpeg
    call is an error.
    """
    calls: list[list[str]] = []

    async def fake_run_tool(cmd, *, timeout):
        tool = Path(cmd[0]).name
        if tool in ("ffprobe", "ffmpeg"):
            handler = ffprobe if tool == "ffprobe" else ffmpeg
        else:
            calls.append(list(cmd))
            handler = ytdlp if tool == "yt-dlp" else gallerydl
        assert handler is not None, f"unexpected {tool} call"
        return handler(list(cmd))

    monkeypatch.setattr(_proc, "run_tool", fake_run_tool)
    return calls


async def test_reel_resolves_to_video_post(monkeypatch, tmp_path):
    calls = install_fakes(monkeypatch, ytdlp=fake_ytdlp_ok)
    provider = InstagramProvider(cookies_file=Path("/data/ig.txt"), download_dir=tmp_path)

    post = await provider.resolve(REEL_URL)

    assert post.uid == "DZu6cdBI2-A"
    assert post.source_url == "https://www.instagram.com/reel/DZu6cdBI2-A/"
    assert post.caption.startswith("A caption with emoji 🎉")
    assert post.author == "some_creator"
    [item] = post.items
    assert item.kind == "video"
    assert (item.width, item.height, item.duration) == (1080, 1920, 15.34)
    assert item.path.exists() and item.path.suffix == ".mp4"
    # Only yt-dlp ran, with the cookies file threaded through.
    [cmd] = calls
    assert Path(cmd[0]).name == "yt-dlp"
    assert _flag_value(cmd, "--cookies") == "/data/ig.txt"


async def test_photo_carousel_ordered_by_num(monkeypatch, tmp_path):
    # Files written in shuffled order; sidecar `num` must define the ordering.
    def gallery(cmd):
        return fake_gallerydl_items(
            cmd, [("creator_x_2.jpg", 2), ("creator_x_1.jpg", 1), ("creator_x_3.jpg", 3)]
        )

    install_fakes(monkeypatch, gallerydl=gallery)
    provider = InstagramProvider(download_dir=tmp_path)

    post = await provider.resolve(POST_URL)

    assert post.uid == "DWTPjRXE5WS"
    assert [i.kind for i in post.items] == ["photo", "photo", "photo"]
    assert [i.path.name for i in post.items] == [
        "creator_x_1.jpg",
        "creator_x_2.jpg",
        "creator_x_3.jpg",
    ]
    assert post.caption == SIDECAR_META["description"]
    assert post.author == "some_creator"


async def test_mixed_carousel_detects_video_items(monkeypatch, tmp_path):
    def gallery(cmd):
        return fake_gallerydl_items(cmd, [("c_1.jpg", 1), ("c_2.mp4", 2)])

    install_fakes(monkeypatch, gallerydl=gallery)
    provider = InstagramProvider(download_dir=tmp_path)

    post = await provider.resolve(POST_URL)

    assert [i.kind for i in post.items] == ["photo", "video"]
    assert post.items[1].duration == 7.2
    assert post.items[0].duration is None


async def test_vp9_carousel_video_transcoded_to_h264(monkeypatch, tmp_path):
    # Instagram serves some carousel videos only as VP9 (no H.264 variant);
    # Telegram can't play those, so the provider must re-encode after download.
    def gallery(cmd):
        return fake_gallerydl_items(cmd, [("c_1.jpg", 1), ("c_2.mp4", 2)])

    ffmpeg_calls: list[list[str]] = []

    def ffmpeg(cmd):
        ffmpeg_calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"h264-bytes")
        return ToolResult(0, "", "")

    install_fakes(
        monkeypatch,
        gallerydl=gallery,
        ffprobe=lambda cmd: fake_ffprobe(cmd, vcodec="vp9"),
        ffmpeg=ffmpeg,
    )
    provider = InstagramProvider(download_dir=tmp_path)

    post = await provider.resolve(POST_URL)

    video = post.items[1]
    assert video.kind == "video"
    assert video.path.name == "c_2.h264.mp4"
    assert video.path.read_bytes() == b"h264-bytes"
    assert len(ffmpeg_calls) == 1  # the photo was neither probed nor transcoded
    assert not (video.path.parent / "c_2.mp4").exists()  # original replaced


async def test_gallery_video_metadata_backfilled_from_ffprobe(monkeypatch, tmp_path):
    # Real gallery-dl sidecars carry no video_duration; the ffprobe pass fills it.
    def gallery(cmd):
        dest = Path(_flag_value(cmd, "--directory"))
        meta = {**SIDECAR_META, "num": 1, "extension": "mp4"}
        meta.pop("width", None)
        meta.pop("height", None)
        (dest / "c_1.mp4").write_bytes(b"media-bytes")
        (dest / "c_1.mp4.json").write_text(json.dumps(meta))
        return ToolResult(0, "", "")

    install_fakes(monkeypatch, gallerydl=gallery)
    provider = InstagramProvider(download_dir=tmp_path)

    post = await provider.resolve(POST_URL)

    [item] = post.items
    assert (item.width, item.height, item.duration) == (1080, 1350, 3.57)


async def test_broken_ffprobe_leaves_video_as_is(monkeypatch, tmp_path):
    # Normalization is best-effort: a missing/failing ffprobe must not sink the post.
    def gallery(cmd):
        return fake_gallerydl_items(cmd, [("c_1.mp4", 1)])

    install_fakes(
        monkeypatch,
        gallerydl=gallery,
        ffprobe=lambda cmd: ToolResult(1, "", "ffprobe exploded"),
    )
    provider = InstagramProvider(download_dir=tmp_path)

    post = await provider.resolve(POST_URL)

    [item] = post.items
    assert item.path.name == "c_1.mp4"
    assert item.path.exists()


async def test_video_only_post_falls_back_to_ytdlp(monkeypatch, tmp_path):
    # gallery-dl exits 0 but downloads nothing → provider retries with yt-dlp.
    calls = install_fakes(
        monkeypatch,
        ytdlp=fake_ytdlp_ok,
        gallerydl=lambda cmd: ToolResult(0, "", ""),
    )
    provider = InstagramProvider(download_dir=tmp_path)

    post = await provider.resolve(POST_URL)

    assert [Path(c[0]).name for c in calls] == ["gallery-dl", "yt-dlp"]
    assert post.items[0].kind == "video"
    assert post.uid == "DWTPjRXE5WS"


async def test_expired_cookies_raise_auth_expired(monkeypatch, tmp_path):
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", YTDLP_LOGIN_WALL))
    provider = InstagramProvider(download_dir=tmp_path)

    with pytest.raises(AuthExpired):
        await provider.resolve(REEL_URL)


async def test_http_429_raises_rate_limited(monkeypatch, tmp_path):
    stderr = "ERROR: unable to download webpage: HTTP Error 429: Too Many Requests"
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", stderr))
    provider = InstagramProvider(download_dir=tmp_path)

    with pytest.raises(RateLimited):
        await provider.resolve(REEL_URL)


async def test_private_post_raises_post_unavailable(monkeypatch, tmp_path):
    stderr = "gallery-dl: instagram: This post is from a private account"
    install_fakes(monkeypatch, gallerydl=lambda cmd: ToolResult(4, "", stderr))
    provider = InstagramProvider(download_dir=tmp_path)

    with pytest.raises(PostUnavailable):
        await provider.resolve(POST_URL)


async def test_garbage_metadata_raises_extraction_failed(monkeypatch, tmp_path):
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(0, "not json", ""))
    provider = InstagramProvider(download_dir=tmp_path)

    with pytest.raises(ExtractionFailed):
        await provider.resolve(REEL_URL)


async def test_unknown_extractor_error_maps_to_extraction_failed(monkeypatch, tmp_path):
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", "ERROR: something exploded"))
    provider = InstagramProvider(download_dir=tmp_path)

    with pytest.raises(ExtractionFailed):
        await provider.resolve(REEL_URL)


async def test_non_instagram_url_rejected_before_any_subprocess(monkeypatch, tmp_path):
    calls = install_fakes(monkeypatch)
    provider = InstagramProvider(download_dir=tmp_path)

    with pytest.raises(UnsupportedUrl):
        await provider.resolve("https://www.youtube.com/watch?v=abc")
    assert calls == []


async def test_missing_binary_maps_to_extraction_failed():
    with pytest.raises(ExtractionFailed, match="not installed"):
        await _proc.run_tool(["definitely-not-a-real-binary-xyz"], timeout=5)


async def test_timeout_maps_to_extraction_failed():
    with pytest.raises(ExtractionFailed, match="timed out"):
        await _proc.run_tool(["sleep", "5"], timeout=0.1)


async def test_failed_extraction_removes_temp_dir(monkeypatch, tmp_path):
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", "ERROR: something exploded"))
    provider = InstagramProvider(download_dir=tmp_path)

    with pytest.raises(ExtractionFailed):
        await provider.resolve(REEL_URL)
    assert list(tmp_path.iterdir()) == []  # no leaked ig-* dir


async def test_successful_extraction_keeps_temp_dir(monkeypatch, tmp_path):
    install_fakes(monkeypatch, ytdlp=fake_ytdlp_ok)
    provider = InstagramProvider(download_dir=tmp_path)

    post = await provider.resolve(REEL_URL)
    assert post.items[0].path.is_file()  # the caller owns cleanup
