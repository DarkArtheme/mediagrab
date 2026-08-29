"""handlers: url extraction, error mapping, whitelist filter, link-handler flow."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
from reelsbot.config import Config

CONFIG = Config(
    bot_token="123:abc",
    whitelist=frozenset({111}),
    admin_user_id=999,
    api_url=None,
    ig_cookies_file=None,
    db_path=Path("cache.sqlite3"),
    download_dir=None,
)

REEL_URL = "https://www.instagram.com/reel/DZu6cdBI2-A/"


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


class TestHandleLink:
    async def test_happy_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        post = make_post(tmp_path)
        provider = FakeProvider(post=post)
        send_post = AsyncMock()
        monkeypatch.setattr(handlers.delivery, "send_post", send_post)
        message, bot = make_message(), AsyncMock()

        await handlers.handle_link(message, bot, CONFIG, make_router(provider))

        assert provider.calls == [REEL_URL]
        send_post.assert_awaited_once_with(bot, 555, post)
        status = message.answer.return_value
        status.delete.assert_awaited_once()
        status.edit_text.assert_not_awaited()
        assert not post.items[0].path.parent.exists()  # temp dir cleaned up

    async def test_no_url_in_text(self) -> None:
        message, bot = make_message(text="just words"), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(FakeProvider()))
        message.answer.assert_awaited_once()
        assert "link" in message.answer.await_args.args[0]

    async def test_unsupported_url_no_status_message(self) -> None:
        message, bot = make_message(text="https://example.com/watch/123"), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(FakeProvider()))
        message.answer.assert_awaited_once()  # only the refusal, no "downloading" status
        assert message.answer.await_args.args[0] == handlers.friendly_error(UnsupportedUrl("x"))

    async def test_error_edits_status(self) -> None:
        provider = FakeProvider(error=RateLimited("429"))
        message, bot = make_message(), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(provider))
        status = message.answer.return_value
        status.edit_text.assert_awaited_once_with(handlers.friendly_error(RateLimited("429")))
        status.delete.assert_not_awaited()
        bot.send_message.assert_not_awaited()  # no admin ping for rate limits

    async def test_auth_expired_notifies_admin(self) -> None:
        provider = FakeProvider(error=AuthExpired("cookies"))
        message, bot = make_message(), AsyncMock()
        await handlers.handle_link(message, bot, CONFIG, make_router(provider))
        bot.send_message.assert_awaited_once()
        assert bot.send_message.await_args.kwargs["chat_id"] == 999

    async def test_delivery_failure_cleans_up_and_reraises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        post = make_post(tmp_path)
        provider = FakeProvider(post=post)
        monkeypatch.setattr(
            handlers.delivery, "send_post", AsyncMock(side_effect=RuntimeError("boom"))
        )
        message, bot = make_message(), AsyncMock()
        with pytest.raises(RuntimeError):
            await handlers.handle_link(message, bot, CONFIG, make_router(provider))
        status = message.answer.return_value
        status.edit_text.assert_awaited_once_with(handlers._FALLBACK_REPLY)
        assert not post.items[0].path.parent.exists()
