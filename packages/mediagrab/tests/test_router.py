from pathlib import Path

import pytest

from mediagrab.errors import UnsupportedUrl
from mediagrab.models import MediaItem, MediaPost
from mediagrab.router import Route, Router, parse_url

# The two example links from the brief (a reel and a photo post).
EXAMPLE_REEL = "https://www.instagram.com/reel/DZu6cdBI2-A/?igsi=ZTAxeWV0bjcxZmIy"
EXAMPLE_POST = "https://www.instagram.com/p/DWTPjRXE5WS/"


@pytest.mark.parametrize(
    ("url", "uid", "kind", "canonical"),
    [
        # The two example links from the brief.
        (EXAMPLE_REEL, "DZu6cdBI2-A", "reel", "https://www.instagram.com/reel/DZu6cdBI2-A/"),
        (EXAMPLE_POST, "DWTPjRXE5WS", "post", "https://www.instagram.com/p/DWTPjRXE5WS/"),
        # Plain reel, with and without trailing slash.
        (
            "https://www.instagram.com/reel/ABC123xyz_-/",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        (
            "https://www.instagram.com/reel/ABC123xyz_-",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        # /reels/ (plural, app share shape) normalizes to /reel/.
        (
            "https://www.instagram.com/reels/ABC123xyz_-/",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        # IGTV links are videos too.
        (
            "https://www.instagram.com/tv/IGTVcode123/",
            "IGTVcode123",
            "reel",
            "https://www.instagram.com/tv/IGTVcode123/",
        ),
        # Photo post.
        (
            "https://www.instagram.com/p/PostCode456/",
            "PostCode456",
            "post",
            "https://www.instagram.com/p/PostCode456/",
        ),
        # Host variants: no www, mobile, http, uppercase.
        (
            "https://instagram.com/reel/ABC123xyz_-/",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        (
            "https://m.instagram.com/p/PostCode456/",
            "PostCode456",
            "post",
            "https://www.instagram.com/p/PostCode456/",
        ),
        (
            "http://www.instagram.com/reel/ABC123xyz_-/",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        (
            "https://WWW.INSTAGRAM.COM/reel/ABC123xyz_-/",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        # Scheme-less paste.
        (
            "instagram.com/reel/ABC123xyz_-/",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        # Query junk and fragments are stripped.
        (
            "https://www.instagram.com/reel/ABC123xyz_-/?utm_source=ig_web_copy_link&igsi=xyz",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        (
            "https://www.instagram.com/p/PostCode456/?img_index=2#comments",
            "PostCode456",
            "post",
            "https://www.instagram.com/p/PostCode456/",
        ),
        # Username-prefixed share pages.
        (
            "https://www.instagram.com/some.user_1/p/PostCode456/",
            "PostCode456",
            "post",
            "https://www.instagram.com/p/PostCode456/",
        ),
        (
            "https://www.instagram.com/some.user_1/reel/ABC123xyz_-/",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
        # Surrounding whitespace from a sloppy paste.
        (
            "  https://www.instagram.com/reel/ABC123xyz_-/  ",
            "ABC123xyz_-",
            "reel",
            "https://www.instagram.com/reel/ABC123xyz_-/",
        ),
    ],
)
def test_valid_urls(url: str, uid: str, kind: str, canonical: str) -> None:
    route = parse_url(url)
    assert route == Route(provider="instagram", uid=uid, kind=kind, canonical_url=canonical)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "not a url",
        "https://www.youtube.com/watch?v=abc",
        "https://www.tiktok.com/@user/video/123",  # future provider, unsupported today
        "https://www.instagram.com/",
        "https://www.instagram.com/some_user/",
        "https://www.instagram.com/stories/some_user/123456/",
        "https://www.instagram.com/explore/",
        "https://www.instagram.com/reel/",
        "https://www.instagram.com/reel/bad code/",
        "https://www.instagram.com/reel/ABC123/extra/",
        "https://www.instagram.com/share/reel/xyz123/",  # redirect-only share link
        "https://evil.com/reel/ABC123/",
        "https://notinstagram.com/reel/ABC123/",
        "ftp://www.instagram.com/reel/ABC123/",
        "mailto:someone@example.com",
    ],
)
def test_unsupported_urls_raise(url: str) -> None:
    with pytest.raises(UnsupportedUrl):
        parse_url(url)


class _FakeProvider:
    async def resolve(self, url: str) -> MediaPost:
        return MediaPost(
            items=[MediaItem(kind="video", path=Path("/tmp/x.mp4"))],
            caption="",
            author="",
            source_url=url,
            uid="x",
        )


def test_router_returns_registered_provider_and_route() -> None:
    router = Router()
    provider = _FakeProvider()
    router.register("instagram", provider)

    resolved_provider, route = router.resolve(EXAMPLE_REEL)

    assert resolved_provider is provider
    assert route.uid == "DZu6cdBI2-A"


def test_router_without_matching_provider_raises() -> None:
    router = Router()
    with pytest.raises(UnsupportedUrl):
        router.resolve(EXAMPLE_REEL)
