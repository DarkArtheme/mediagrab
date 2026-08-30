"""handlers: url extraction, error mapping, whitelist filter, link-handler flow."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from mediagrab import MediaItem, MediaPost
from mediagrab import Router as MediaRouter
from mediagrab.errors import (
    AuthExpired,
    ExtractionFailed,
    PostUnavailable,
    RateLimited,
    UnsupportedUrl,
)
from reelsbot import handlers
from reelsbot.cache import CachedItem, CachedPost, CacheRepository
from reelsbot.config import Config
from reelsbot.throttle import ExtractionGate

CONFIG = Config(
    bot_token="123:abc",
    whitelist=frozenset({111}),
    admin_user_id=999,
    api_url=None,
    ig_cookies_file=None,
    tiktok_cookies_file=None,
    db_path=Path("cache.sqlite3"),
    download_dir=None,
)

REEL_URL = "https://www.instagram.com/reel/DZu6cdBI2-A/"
REEL_UID = "DZu6cdBI2-A"


@pytest.fixture
def cache(tmp_path: Path) -> CacheRepository:
    return CacheRepository(tmp_path / "cache.sqlite3")


@pytest.fixture
def gate() -> ExtractionGate:
    return ExtractionGate(min_interval=0.0)


class FakeProvider:
    """Provider double: returns a canned post or raises a canned error."""

    def __init__(self, post: MediaPost | None = None, error: Exception | None = None) -> None:
        self.post = post
        self.error = error
        self.calls: list[str] = []

    async def resolve(self, url: str) -> MediaPost:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        assert self.post is not None
        return self.post


def make_message(text: str | None = REEL_URL, user_id: int = 111) -> AsyncMock:
    message = AsyncMock()
    message.text = text
    message.chat = SimpleNamespace(id=555)
    message.from_user = SimpleNamespace(id=user_id)
    message.answer.return_value = AsyncMock()  # the status message
    return message


def make_router(provider: FakeProvider) -> MediaRouter:
    media_router = MediaRouter()
    media_router.register("instagram", provider)
    return media_router


def make_post(tmp_path: Path) -> MediaPost:
    dest = tmp_path / "ig-DZu6cdBI2-A-x"
    dest.mkdir()
    video = dest / "v.mp4"
    video.touch()
    return MediaPost(
        items=[MediaItem(kind="video", path=video)],
        caption="cap",
        author="a",
        source_url=REEL_URL,
        uid="DZu6cdBI2-A",
    )


class TestFirstUrl:
    def test_plain_url(self) -> None:
        assert handlers.first_url(f"look {REEL_URL} wow") == REEL_URL

    def test_schemeless(self) -> None:
        assert handlers.first_url("instagram.com/p/ABC/") == "instagram.com/p/ABC/"

    def test_no_url(self) -> None:
        assert handlers.first_url("hello there") is None


class TestFriendlyError:
    @pytest.mark.parametrize(
        "err",
        [UnsupportedUrl("x"), PostUnavailable("x"), AuthExpired("x"), RateLimited("x")],
    )
    def test_specific_replies(self, err: Exception) -> None:
        assert handlers.friendly_error(err) != handlers._FALLBACK_REPLY

    def test_extraction_failed_falls_back(self) -> None:
        assert handlers.friendly_error(ExtractionFailed("x")) == handlers._FALLBACK_REPLY


class TestWhitelisted:
    async def test_allows_listed_user(self) -> None:
        assert await handlers.Whitelisted()(make_message(), CONFIG) is True

    async def test_denies_unlisted_user(self) -> None:
        assert await handlers.Whitelisted()(make_message(user_id=222), CONFIG) is False

    async def test_denies_missing_user(self) -> None:
        message = make_message()
        message.from_user = None
        assert await handlers.Whitelisted()(message, CONFIG) is False


SENT_VIDEO = SimpleNamespace(video=SimpleNamespace(file_id="vid-1"), photo=None)


class TestHandleLink:
    async def test_happy_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: CacheRepository,
        gate: ExtractionGate,
    ) -> None:
        post = make_post(tmp_path)
        provider = FakeProvider(post=post)
        send_post = AsyncMock(return_value=[SENT_VIDEO])
        monkeypatch.setattr(handlers.delivery, "send_post", send_post)
        message, bot = make_message(), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)

        assert provider.calls == [REEL_URL]
        send_post.assert_awaited_once_with(bot, 555, post)
        status = message.answer.return_value
        status.delete.assert_awaited_once()
        status.edit_text.assert_not_awaited()
        assert not post.items[0].path.parent.exists()  # temp dir cleaned up
        # file_ids of the sent messages were stored for next time
        stored = cache.get(REEL_UID)
        assert stored is not None
        assert stored.items == [CachedItem(kind="video", file_id="vid-1")]
        assert stored.caption == "cap"
        # user slot released: the next job is accepted
        assert gate.acquire_user(111) is True

    async def test_short_link_caches_both_token_and_post_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: CacheRepository,
        gate: ExtractionGate,
    ) -> None:
        # A TikTok share link routes under its token; the provider resolves the
        # real post id. Both keys must land in the cache.
        short_url = "https://vt.tiktok.com/ZSVvX7VkE/"
        dest = tmp_path / "tt-123-x"
        dest.mkdir()
        video = dest / "v.mp4"
        video.touch()
        post = MediaPost(
            items=[MediaItem(kind="video", path=video)],
            caption="cap",
            author="a",
            source_url="https://www.tiktok.com/@user/video/123",
            uid="tiktok:123",
        )
        provider = FakeProvider(post=post)
        media_router = MediaRouter()
        media_router.register("tiktok", provider)
        monkeypatch.setattr(handlers.delivery, "send_post", AsyncMock(return_value=[SENT_VIDEO]))
        message, bot = make_message(text=short_url), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, media_router, cache, gate)

        for uid in ("tiktok:ZSVvX7VkE", "tiktok:123"):
            stored = cache.get(uid)
            assert stored is not None, uid
            assert stored.items == [CachedItem(kind="video", file_id="vid-1")]

    async def test_cache_hit_skips_provider(
        self, monkeypatch: pytest.MonkeyPatch, cache: CacheRepository, gate: ExtractionGate
    ) -> None:
        cached = CachedPost(
            uid=REEL_UID,
            provider="instagram",
            kind="reel",
            items=[CachedItem(kind="video", file_id="vid-1")],
            caption="cap",
        )
        cache.put(cached)
        send_cached = AsyncMock()
        monkeypatch.setattr(handlers.delivery, "send_cached", send_cached)
        provider = FakeProvider()
        message, bot = make_message(), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)

        send_cached.assert_awaited_once_with(bot, 555, cached)
        assert provider.calls == []  # Instagram untouched
        message.answer.assert_not_awaited()  # no status message either

    async def test_stale_cache_falls_back_to_extraction(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: CacheRepository,
        gate: ExtractionGate,
    ) -> None:
        cache.put(
            CachedPost(
                uid=REEL_UID,
                provider="instagram",
                kind="reel",
                items=[CachedItem(kind="video", file_id="dead-id")],
                caption="cap",
            )
        )
        error = TelegramBadRequest(method=None, message="wrong file identifier")  # type: ignore[arg-type]
        monkeypatch.setattr(handlers.delivery, "send_cached", AsyncMock(side_effect=error))
        send_post = AsyncMock(return_value=[SENT_VIDEO])
        monkeypatch.setattr(handlers.delivery, "send_post", send_post)
        provider = FakeProvider(post=make_post(tmp_path))
        message, bot = make_message(), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)

        assert provider.calls == [REEL_URL]  # re-extracted
        stored = cache.get(REEL_UID)
        assert stored is not None
        assert stored.items == [CachedItem(kind="video", file_id="vid-1")]  # entry replaced

    async def test_busy_user_refused(self, cache: CacheRepository, gate: ExtractionGate) -> None:
        gate.acquire_user(111)
        provider = FakeProvider()
        message, bot = make_message(), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)
        assert provider.calls == []
        message.answer.assert_awaited_once()
        assert "previous link" in message.answer.await_args.args[0]

    async def test_no_url_in_text(self, cache: CacheRepository, gate: ExtractionGate) -> None:
        message, bot = make_message(text="just words"), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(FakeProvider()), cache, gate)
        message.answer.assert_awaited_once()
        assert "link" in message.answer.await_args.args[0]

    async def test_unsupported_url_no_status_message(
        self, cache: CacheRepository, gate: ExtractionGate
    ) -> None:
        message, bot = make_message(text="https://example.com/watch/123"), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(FakeProvider()), cache, gate)
        message.answer.assert_awaited_once()  # only the refusal, no "downloading" status
        assert message.answer.await_args.args[0] == handlers.friendly_error(UnsupportedUrl("x"))

    async def test_error_edits_status(self, cache: CacheRepository, gate: ExtractionGate) -> None:
        provider = FakeProvider(error=RateLimited("429"))
        message, bot = make_message(), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)
        status = message.answer.return_value
        status.edit_text.assert_awaited_once_with(handlers.friendly_error(RateLimited("429")))
        status.delete.assert_not_awaited()
        bot.send_message.assert_not_awaited()  # no admin ping for rate limits
        assert cache.get(REEL_UID) is None  # failures are not cached
        assert gate.acquire_user(111) is True  # user slot released on failure

    async def test_auth_expired_notifies_admin(
        self, cache: CacheRepository, gate: ExtractionGate
    ) -> None:
        provider = FakeProvider(error=AuthExpired("cookies"))
        message, bot = make_message(), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)
        bot.send_message.assert_awaited_once()
        assert bot.send_message.await_args.kwargs["chat_id"] == 999

    async def test_delivery_failure_cleans_up_and_reraises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: CacheRepository,
        gate: ExtractionGate,
    ) -> None:
        post = make_post(tmp_path)
        provider = FakeProvider(post=post)
        monkeypatch.setattr(
            handlers.delivery, "send_post", AsyncMock(side_effect=RuntimeError("boom"))
        )
        message, bot = make_message(), AsyncMock()
        with pytest.raises(RuntimeError):
            await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)
        status = message.answer.return_value
        status.edit_text.assert_awaited_once_with(handlers._FALLBACK_REPLY)
        assert not post.items[0].path.parent.exists()
        assert cache.get(REEL_UID) is None
        assert gate.acquire_user(111) is True


class FlakyProvider:
    """Provider double that raises the queued errors first, then succeeds."""

    def __init__(self, post: MediaPost, errors: list[Exception]) -> None:
        self.post = post
        self.errors = errors
        self.calls: list[str] = []

    async def resolve(self, url: str) -> MediaPost:
        self.calls.append(url)
        if self.errors:
            raise self.errors.pop(0)
        return self.post


class TestRetryOnce:
    async def test_transient_failure_retried_and_succeeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cache: CacheRepository,
        gate: ExtractionGate,
    ) -> None:
        post = make_post(tmp_path)
        provider = FlakyProvider(post, errors=[ExtractionFailed("blip")])
        media_router = MediaRouter()
        media_router.register("instagram", provider)
        monkeypatch.setattr(handlers.delivery, "send_post", AsyncMock(return_value=[SENT_VIDEO]))
        message, bot = make_message(), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, media_router, cache, gate)

        assert provider.calls == [REEL_URL, REEL_URL]  # one retry
        message.answer.return_value.delete.assert_awaited_once()  # ended in success
        assert cache.get(REEL_UID) is not None

    async def test_second_failure_not_retried_again(
        self, tmp_path: Path, cache: CacheRepository, gate: ExtractionGate
    ) -> None:
        post = make_post(tmp_path)
        provider = FlakyProvider(post, errors=[ExtractionFailed("a"), ExtractionFailed("b")])
        media_router = MediaRouter()
        media_router.register("instagram", provider)
        message, bot = make_message(), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, media_router, cache, gate)

        assert provider.calls == [REEL_URL, REEL_URL]  # exactly two attempts
        status = message.answer.return_value
        status.edit_text.assert_awaited_once_with(handlers._FALLBACK_REPLY)

    async def test_stable_errors_not_retried(
        self, cache: CacheRepository, gate: ExtractionGate
    ) -> None:
        provider = FakeProvider(error=PostUnavailable("gone"))
        message, bot = make_message(), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, make_router(provider), cache, gate)

        assert provider.calls == [REEL_URL]  # no retry for non-transient errors


class TestAdminOnly:
    async def test_allows_admin(self) -> None:
        assert await handlers.AdminOnly()(make_message(user_id=999), CONFIG) is True

    async def test_denies_non_admin(self) -> None:
        assert await handlers.AdminOnly()(make_message(user_id=111), CONFIG) is False


class TestHealth:
    async def test_reports_all_sections(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache: CacheRepository
    ) -> None:
        cookies = tmp_path / "ig.txt"
        cookies.write_text("# netscape cookies")
        config = replace_config(CONFIG, ig_cookies_file=cookies)
        versions = {"yt-dlp": "2026.01.01", "gallery-dl": None}

        async def fake_tool_version(tool: str, **kwargs: object) -> str | None:
            return versions[tool]

        monkeypatch.setattr(handlers.diagnostics, "tool_version", fake_tool_version)
        message = make_message(text="/health", user_id=999)

        from time import monotonic

        await handlers.cmd_health(message, config, cache, started_at=monotonic() - 3600)

        reply = message.answer.await_args.args[0]
        assert "reelsbot" in reply and "mediagrab" in reply
        assert "✅ yt-dlp 2026.01.01" in reply
        assert "❌ gallery-dl" in reply
        assert f"✅ IG cookies: {cookies}" in reply
        assert "TikTok cookies: not configured" in reply
        assert "✅ cache: 0 post(s)" in reply
        assert "uptime: 1h 0m" in reply

    async def test_missing_cookies_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache: CacheRepository
    ) -> None:
        async def fake_tool_version(tool: str, **kwargs: object) -> str | None:
            return "1.0"

        monkeypatch.setattr(handlers.diagnostics, "tool_version", fake_tool_version)
        config = replace_config(CONFIG, ig_cookies_file=tmp_path / "gone.txt")
        message = make_message(text="/health", user_id=999)

        await handlers.cmd_health(message, config, cache, started_at=0.0)

        reply = message.answer.await_args.args[0]
        assert "❌ IG cookies" in reply and "does not exist" in reply


def replace_config(config: Config, **changes: object) -> Config:
    from dataclasses import replace as dc_replace

    return dc_replace(config, **changes)
