from pathlib import Path

import pytest

from mediagrab.errors import PostUnavailable
from mediagrab.grab import GrabResult, MediaGrab
from mediagrab.models import MediaItem, MediaPost
from mediagrab.router import Router

REEL_URL = "https://www.instagram.com/reel/AAAAAAA/"
TIKTOK_URL = "https://www.tiktok.com/@user/video/123"
DEAD_URL = "https://www.instagram.com/reel/DEADDEAD/"


def make_post(uid: str) -> MediaPost:
    return MediaPost(
        items=[MediaItem(kind="video", path=Path(f"/tmp/{uid}.mp4"), duration=9.5)],
        caption=f"caption {uid}",
        author="someone",
        source_url=f"https://example.com/{uid}",
        uid=uid,
    )


class FakeProvider:
    """Resolves by uid embedded in the URL; DEADDEAD raises PostUnavailable."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def resolve(self, url: str) -> MediaPost:
        self.calls.append(url)
        if "DEADDEAD" in url:
            raise PostUnavailable(url)
        return make_post(url.rstrip("/").rpartition("/")[2])


@pytest.fixture
def grabber() -> MediaGrab:
    router = Router()
    provider = FakeProvider()
    router.register("instagram", provider)
    router.register("tiktok", provider)
    return MediaGrab(router=router)


async def test_fetch_returns_post(grabber: MediaGrab) -> None:
    post = await grabber.fetch(REEL_URL)
    assert post.uid == "AAAAAAA"


async def test_fetch_raises_mediagrab_error(grabber: MediaGrab) -> None:
    with pytest.raises(PostUnavailable):
        await grabber.fetch(DEAD_URL)


async def test_fetch_many_preserves_order_and_captures_errors(grabber: MediaGrab) -> None:
    results = await grabber.fetch_many([REEL_URL, DEAD_URL, TIKTOK_URL])
    assert [r.url for r in results] == [REEL_URL, DEAD_URL, TIKTOK_URL]
    assert results[0].ok and results[0].post is not None
    assert not results[1].ok
    assert isinstance(results[1].error, PostUnavailable)
    assert results[2].ok and results[2].post is not None
    assert results[2].post.uid == "123"


async def test_fetch_many_empty_list(grabber: MediaGrab) -> None:
    assert await grabber.fetch_many([]) == []


async def test_fetch_many_captures_unsupported_url(grabber: MediaGrab) -> None:
    (result,) = await grabber.fetch_many(["https://example.com/nope"])
    assert not result.ok
    assert result.error is not None
    assert type(result.error).__name__ == "UnsupportedUrl"


def test_grab_result_to_dict_success() -> None:
    result = GrabResult(url=REEL_URL, post=make_post("AAAAAAA"))
    data = result.to_dict()
    assert data["ok"] is True
    assert data["post"]["uid"] == "AAAAAAA"
    assert data["post"]["items"][0]["path"] == "/tmp/AAAAAAA.mp4"
    assert "error" not in data


def test_grab_result_to_dict_failure() -> None:
    result = GrabResult(url=DEAD_URL, error=PostUnavailable("gone"))
    data = result.to_dict()
    assert data["ok"] is False
    assert data["error"] == {"type": "PostUnavailable", "message": "gone"}
    assert "post" not in data


def test_env_cookie_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IG_COOKIES_FILE", "/secrets/ig.txt")
    monkeypatch.setenv("TIKTOK_COOKIES_FILE", "")
    grabber = MediaGrab()
    instagram = grabber.router._providers["instagram"]
    tiktok = grabber.router._providers["tiktok"]
    assert instagram._cookies_file == Path("/secrets/ig.txt")  # type: ignore[attr-defined]
    assert tiktok._cookies_file is None  # type: ignore[attr-defined]
