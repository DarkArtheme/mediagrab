"""TikTok provider tests: subprocess calls are faked by monkeypatching
mediagrab._proc.run_tool; short-link redirects are faked at the resolver."""

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
from mediagrab.providers.tiktok import _redirect
from mediagrab.providers.tiktok.provider import TikTokProvider

FIXTURES = Path(__file__).parent / "fixtures"

VIDEO_URL = "https://www.tiktok.com/@kyotheorangecatt/video/7677354019064515870?_r=1&_t=ZS-9"
PHOTO_URL = "https://www.tiktok.com/@rastograf_vlog/photo/7677528044197776670"
SHORT_URL = "https://vt.tiktok.com/ZSVvX7VkE/"

YTDLP_INFO = json.loads((FIXTURES / "ytdlp_tiktok_video.json").read_text())
SIDECAR_META = json.loads((FIXTURES / "gallerydl_tiktok_sidecar.json").read_text())


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
        (dest / name).write_bytes(b"media-bytes")
        (dest / f"{name}.json").write_text(json.dumps(meta))
    return ToolResult(0, "", "")


def fake_ffprobe(cmd: list[str], *, vcodec: str = "h264") -> ToolResult:
    payload = {
        "streams": [{"codec_type": "video", "codec_name": vcodec, "width": 720, "height": 1280}],
        "format": {"duration": "14.0"},
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


async def test_video_resolves_to_video_post(monkeypatch, tmp_path):
    calls = install_fakes(monkeypatch, ytdlp=fake_ytdlp_ok)
    provider = TikTokProvider(download_dir=tmp_path)

    post = await provider.resolve(VIDEO_URL)

    assert post.uid == "tiktok:7677354019064515870"
    assert post.source_url == "https://www.tiktok.com/@kyotheorangecatt/video/7677354019064515870"
    assert post.caption.startswith("he’s reconsidering everything")
    assert post.author == "kyotheorangecatt"
    [item] = post.items
    assert item.kind == "video"
    assert (item.width, item.height, item.duration) == (720, 1280, 14)
    assert item.path.exists() and item.path.suffix == ".mp4"
    # Only yt-dlp ran, anonymously — no --cookies flag without a cookies file.
    [cmd] = calls
    assert Path(cmd[0]).name == "yt-dlp"
    assert "--cookies" not in cmd


async def test_cookies_threaded_through_when_configured(monkeypatch, tmp_path):
    calls = install_fakes(monkeypatch, ytdlp=fake_ytdlp_ok)
    provider = TikTokProvider(cookies_file=Path("/data/tt.txt"), download_dir=tmp_path)

    await provider.resolve(VIDEO_URL)

    [cmd] = calls
    assert _flag_value(cmd, "--cookies") == "/data/tt.txt"


async def test_photo_slideshow_ordered_and_audio_dropped(monkeypatch, tmp_path):
    # Files written in shuffled order plus the music track gallery-dl always
    # saves; sidecar `num` must define the ordering and the mp3 must be dropped.
    def gallery(cmd):
        result = fake_gallerydl_items(cmd, [("post_2.jpg", 2), ("post_1.jpg", 1)])
        dest = Path(_flag_value(cmd, "--directory"))
        (dest / "post song.mp3").write_bytes(b"audio-bytes")
        (dest / "post song.mp3.json").write_text(json.dumps(SIDECAR_META))
        return result

    install_fakes(monkeypatch, gallerydl=gallery)
    provider = TikTokProvider(download_dir=tmp_path)

    post = await provider.resolve(PHOTO_URL)

    assert post.uid == "tiktok:7677528044197776670"
    assert [i.kind for i in post.items] == ["photo", "photo"]
    assert [i.path.name for i in post.items] == ["post_1.jpg", "post_2.jpg"]
    assert (post.items[0].width, post.items[0].height) == (960, 1280)
    assert post.caption == SIDECAR_META["desc"]
    assert post.author == "rastograf_vlog"


async def test_short_link_resolves_redirect_then_downloads(monkeypatch, tmp_path):
    hops = {
        "https://vt.tiktok.com/ZSVvX7VkE/": (
            "https://www.tiktok.com/@kyotheorangecatt/video/7677354019064515870?_r=1"
        ),
    }

    def fake_next_hop(url, timeout):
        return hops.get(url)

    monkeypatch.setattr(_redirect, "_next_hop", fake_next_hop)
    install_fakes(monkeypatch, ytdlp=fake_ytdlp_ok)
    provider = TikTokProvider(download_dir=tmp_path)

    post = await provider.resolve(SHORT_URL)

    # uid is the resolved post id, not the share token.
    assert post.uid == "tiktok:7677354019064515870"
    assert post.items[0].kind == "video"


async def test_short_link_to_photo_post_uses_gallerydl(monkeypatch, tmp_path):
    def fake_next_hop(url, timeout):
        return f"{PHOTO_URL}?_r=1"

    monkeypatch.setattr(_redirect, "_next_hop", fake_next_hop)
    install_fakes(monkeypatch, gallerydl=lambda cmd: fake_gallerydl_items(cmd, [("post_1.jpg", 1)]))
    provider = TikTokProvider(download_dir=tmp_path)

    post = await provider.resolve("https://vt.tiktok.com/ZSVvXyT7M/")

    assert post.uid == "tiktok:7677528044197776670"
    assert [i.kind for i in post.items] == ["photo"]


async def test_dead_short_link_raises_post_unavailable(monkeypatch, tmp_path):
    # Expired share links redirect to the homepage, which never parses as a post.
    def fake_next_hop(url, timeout):
        return "https://www.tiktok.com/" if "vt.tiktok" in url else None

    monkeypatch.setattr(_redirect, "_next_hop", fake_next_hop)
    calls = install_fakes(monkeypatch)
    provider = TikTokProvider(download_dir=tmp_path)

    with pytest.raises(PostUnavailable):
        await provider.resolve(SHORT_URL)
    assert calls == []


async def test_slideshow_under_video_path_falls_back_to_gallerydl(monkeypatch, tmp_path):
    # yt-dlp can't extract a slideshow; the provider retries with gallery-dl.
    calls = install_fakes(
        monkeypatch,
        ytdlp=lambda cmd: ToolResult(1, "", "ERROR: something exploded"),
        gallerydl=lambda cmd: fake_gallerydl_items(cmd, [("post_1.jpg", 1)]),
    )
    provider = TikTokProvider(download_dir=tmp_path)

    post = await provider.resolve(VIDEO_URL)

    assert [Path(c[0]).name for c in calls] == ["yt-dlp", "gallery-dl"]
    assert [i.kind for i in post.items] == ["photo"]


async def test_empty_gallery_falls_back_to_ytdlp_video_url(monkeypatch, tmp_path):
    # gallery-dl finds nothing → provider retries yt-dlp, rewriting /photo/ to
    # /video/ (yt-dlp's TikTok extractor only matches /video/ paths).
    calls = install_fakes(
        monkeypatch,
        ytdlp=fake_ytdlp_ok,
        gallerydl=lambda cmd: ToolResult(0, "", ""),
    )
    provider = TikTokProvider(download_dir=tmp_path)

    post = await provider.resolve(PHOTO_URL)

    assert [Path(c[0]).name for c in calls] == ["gallery-dl", "yt-dlp"]
    assert "/video/" in calls[1][-1]
    assert post.items[0].kind == "video"
    assert post.uid == "tiktok:7677528044197776670"


async def test_login_wall_without_cookies_raises_post_unavailable(monkeypatch, tmp_path):
    stderr = "ERROR: [TikTok] 7677354019064515870: Log in for access"
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", stderr), gallerydl=None)

    with pytest.raises(PostUnavailable):
        await TikTokProvider(download_dir=tmp_path).resolve(VIDEO_URL)


async def test_login_wall_with_cookies_raises_auth_expired(monkeypatch, tmp_path):
    stderr = "ERROR: [TikTok] 7677354019064515870: Log in for access"
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", stderr))
    provider = TikTokProvider(cookies_file=Path("/data/tt.txt"), download_dir=tmp_path)

    with pytest.raises(AuthExpired):
        await provider.resolve(VIDEO_URL)


async def test_http_429_raises_rate_limited(monkeypatch, tmp_path):
    stderr = "ERROR: unable to download webpage: HTTP Error 429: Too Many Requests"
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", stderr))

    with pytest.raises(RateLimited):
        await TikTokProvider(download_dir=tmp_path).resolve(VIDEO_URL)


async def test_removed_post_raises_post_unavailable(monkeypatch, tmp_path):
    stderr = "ERROR: [TikTok] 7677354019064515870: Video not available"
    install_fakes(monkeypatch, ytdlp=lambda cmd: ToolResult(1, "", stderr))

    with pytest.raises(PostUnavailable):
        await TikTokProvider(download_dir=tmp_path).resolve(VIDEO_URL)


async def test_garbage_metadata_raises_extraction_failed(monkeypatch, tmp_path):
    install_fakes(
        monkeypatch,
        ytdlp=lambda cmd: ToolResult(0, "not json", ""),
        gallerydl=lambda cmd: ToolResult(0, "", ""),
    )

    with pytest.raises(ExtractionFailed):
        await TikTokProvider(download_dir=tmp_path).resolve(VIDEO_URL)


async def test_non_tiktok_url_rejected_before_any_subprocess(monkeypatch, tmp_path):
    calls = install_fakes(monkeypatch)
    provider = TikTokProvider(download_dir=tmp_path)

    with pytest.raises(UnsupportedUrl):
        await provider.resolve("https://www.instagram.com/reel/ABC123xyz_-/")
    assert calls == []


async def test_redirect_chain_follows_multiple_hops(monkeypatch):
    hops = {
        "https://vt.tiktok.com/token1/": "https://vm.tiktok.com/token2/",
        "https://vm.tiktok.com/token2/": f"{PHOTO_URL}?_r=1",
    }
    monkeypatch.setattr(_redirect, "_next_hop", lambda url, timeout: hops.get(url))

    resolved = await _redirect.resolve_short_link(
        "https://vt.tiktok.com/token1/", is_post_url=lambda u: "/photo/" in u
    )
    assert resolved == f"{PHOTO_URL}?_r=1"


async def test_redirect_loop_gives_up(monkeypatch):
    monkeypatch.setattr(_redirect, "_next_hop", lambda url, timeout: "https://vm.tiktok.com/x/")

    with pytest.raises(PostUnavailable, match="too long"):
        await _redirect.resolve_short_link(
            "https://vt.tiktok.com/token1/", is_post_url=lambda u: False
        )


async def test_failed_extraction_removes_temp_dir(monkeypatch, tmp_path):
    # yt-dlp chokes, the gallery-dl fallback also fails: nothing may leak.
    install_fakes(
        monkeypatch,
        ytdlp=lambda cmd: ToolResult(1, "", "ERROR: something exploded"),
        gallerydl=lambda cmd: ToolResult(1, "", "error: nope"),
    )

    with pytest.raises(ExtractionFailed):
        await TikTokProvider(download_dir=tmp_path).resolve(VIDEO_URL)
    assert list(tmp_path.iterdir()) == []  # no leaked tt-* dir
