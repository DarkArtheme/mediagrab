"""Optional live smoke test against real Instagram. Skipped unless
MEDIAGRAB_LIVE_TEST=1; never runs in CI. Uses the burner account's cookies
from IG_COOKIES_FILE when set.

    MEDIAGRAB_LIVE_TEST=1 IG_COOKIES_FILE=~/ig-cookies.txt uv run pytest \
        packages/mediagrab/tests/test_live_smoke.py -v
"""

import os
from pathlib import Path

import pytest

from mediagrab.providers.instagram.provider import InstagramProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("MEDIAGRAB_LIVE_TEST"),
    reason="live Instagram test; set MEDIAGRAB_LIVE_TEST=1 to run",
)

EXAMPLE_REEL = "https://www.instagram.com/reel/DZu6cdBI2-A/?igsi=ZTAxeWV0bjcxZmIy"
EXAMPLE_POST = "https://www.instagram.com/p/DWTPjRXE5WS/"


def _provider(tmp_path: Path) -> InstagramProvider:
    cookies = os.environ.get("IG_COOKIES_FILE")
    return InstagramProvider(
        cookies_file=Path(cookies).expanduser() if cookies else None,
        download_dir=tmp_path,
    )


async def test_live_reel(tmp_path: Path) -> None:
    post = await _provider(tmp_path).resolve(EXAMPLE_REEL)
    assert post.uid == "DZu6cdBI2-A"
    [item] = post.items
    assert item.kind == "video"
    assert item.path.exists() and item.path.stat().st_size > 0


async def test_live_post(tmp_path: Path) -> None:
    post = await _provider(tmp_path).resolve(EXAMPLE_POST)
    assert post.uid == "DWTPjRXE5WS"
    assert post.items
    for item in post.items:
        assert item.path.exists() and item.path.stat().st_size > 0
