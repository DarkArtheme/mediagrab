"""delivery: caption splitting and send call shapes (Bot is mocked)."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import InputMediaPhoto, InputMediaVideo

from mediagrab import MediaItem, MediaPost
from reelsbot.cache import CachedItem, CachedPost
from reelsbot.delivery import (
    ALBUM_LIMIT,
    CAPTION_LIMIT,
    TEXT_LIMIT,
    extract_file_ids,
    send_cached,
    send_post,
    split_caption,
)


def _post(items: list[MediaItem], caption: str = "hi") -> MediaPost:
    return MediaPost(
        items=items,
        caption=caption,
        author="someone",
        source_url="https://www.instagram.com/p/ABC/",
        uid="ABC",
    )


def _video(name: str = "v.mp4") -> MediaItem:
    return MediaItem(
        kind="video", path=Path(f"/tmp/{name}"), width=1080, height=1920, duration=12.6
    )


def _photo(name: str = "p.jpg") -> MediaItem:
    return MediaItem(kind="photo", path=Path(f"/tmp/{name}"))


class TestSplitCaption:
    def test_short_passes_through(self) -> None:
        assert split_caption("hello") == ("hello", [])

    def test_exactly_at_limit(self) -> None:
        text = "x" * CAPTION_LIMIT
        assert split_caption(text) == (text, [])

    def test_long_truncates_and_sends_full_text(self) -> None:
        text = "x" * (CAPTION_LIMIT + 5)
        caption, follow_ups = split_caption(text)
        assert len(caption) == CAPTION_LIMIT
        assert caption.endswith("…")
        assert follow_ups == [text]

    def test_very_long_chunks_follow_ups(self) -> None:
        text = "x" * (TEXT_LIMIT + 100)
        _, follow_ups = split_caption(text)
        assert [len(c) for c in follow_ups] == [TEXT_LIMIT, 100]
        assert "".join(follow_ups) == text


class TestSendPost:
    async def test_single_video(self) -> None:
        bot = AsyncMock()
        await send_post(bot, 42, _post([_video()], caption="a reel"))
        bot.send_video.assert_awaited_once()
        kwargs = bot.send_video.await_args.kwargs
        assert kwargs["chat_id"] == 42
        assert kwargs["caption"] == "a reel"
        assert kwargs["supports_streaming"] is True
        assert kwargs["width"] == 1080
        assert kwargs["height"] == 1920
        assert kwargs["duration"] == 13
        assert kwargs["request_timeout"] > 60  # big uploads outlive the default timeout
        bot.send_media_group.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    async def test_single_photo(self) -> None:
        bot = AsyncMock()
        await send_post(bot, 42, _post([_photo()]))
        bot.send_photo.assert_awaited_once()
        assert bot.send_photo.await_args.kwargs["caption"] == "hi"

    async def test_empty_caption_becomes_none(self) -> None:
        bot = AsyncMock()
        await send_post(bot, 42, _post([_photo()], caption=""))
        assert bot.send_photo.await_args.kwargs["caption"] is None

    async def test_album_caption_on_first_item_only(self) -> None:
        bot = AsyncMock()
        items = [_photo("1.jpg"), _video("2.mp4"), _photo("3.jpg")]
        await send_post(bot, 42, _post(items, caption="album"))
        bot.send_media_group.assert_awaited_once()
        media = bot.send_media_group.await_args.kwargs["media"]
        assert [type(m) for m in media] == [InputMediaPhoto, InputMediaVideo, InputMediaPhoto]
        assert media[0].caption == "album"
        assert media[1].caption is None
        assert media[2].caption is None
        assert media[1].supports_streaming is True

    async def test_big_album_chunked(self) -> None:
        bot = AsyncMock()
        items = [_photo(f"{i}.jpg") for i in range(ALBUM_LIMIT + 2)]
        await send_post(bot, 42, _post(items, caption="big"))
        assert bot.send_media_group.await_count == 2
        first, second = bot.send_media_group.await_args_list
        assert len(first.kwargs["media"]) == ALBUM_LIMIT
        assert len(second.kwargs["media"]) == 2
        # caption only on the very first item of the first chunk
        assert first.kwargs["media"][0].caption == "big"
        assert second.kwargs["media"][0].caption is None

    async def test_long_caption_follow_up_messages(self) -> None:
        bot = AsyncMock()
        text = "y" * (CAPTION_LIMIT + 10)
        await send_post(bot, 42, _post([_video()], caption=text))
        assert bot.send_video.await_args.kwargs["caption"].endswith("…")
        bot.send_message.assert_awaited_once()
        assert bot.send_message.await_args.kwargs["text"] == text

    async def test_returns_all_sent_messages(self) -> None:
        bot = AsyncMock()
        bot.send_media_group.return_value = ["m1", "m2"]
        bot.send_message.return_value = "m3"
        text = "z" * (CAPTION_LIMIT + 1)
        sent = await send_post(bot, 42, _post([_photo("1.jpg"), _photo("2.jpg")], caption=text))
        assert sent == ["m1", "m2", "m3"]


def _cached(items: list[CachedItem], caption: str = "hi") -> CachedPost:
    return CachedPost(uid="ABC", provider="instagram", kind="post", items=items, caption=caption)


class TestSendCached:
    async def test_single_video_by_file_id(self) -> None:
        bot = AsyncMock()
        await send_cached(bot, 42, _cached([CachedItem(kind="video", file_id="vid-1")]))
        kwargs = bot.send_video.await_args.kwargs
        assert kwargs["video"] == "vid-1"
        assert kwargs["caption"] == "hi"
        assert kwargs["supports_streaming"] is True

    async def test_single_photo_by_file_id(self) -> None:
        bot = AsyncMock()
        await send_cached(bot, 42, _cached([CachedItem(kind="photo", file_id="ph-1")]))
        assert bot.send_photo.await_args.kwargs["photo"] == "ph-1"

    async def test_album_from_file_ids(self) -> None:
        bot = AsyncMock()
        items = [CachedItem(kind="photo", file_id="p1"), CachedItem(kind="video", file_id="v1")]
        await send_cached(bot, 42, _cached(items, caption="album"))
        media = bot.send_media_group.await_args.kwargs["media"]
        assert [type(m) for m in media] == [InputMediaPhoto, InputMediaVideo]
        assert media[0].media == "p1"
        assert media[0].caption == "album"
        assert media[1].caption is None


class TestExtractFileIds:
    def test_picks_video_and_largest_photo_skips_text(self) -> None:
        messages = [
            SimpleNamespace(video=SimpleNamespace(file_id="vid-1"), photo=None),
            SimpleNamespace(
                video=None,
                photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")],
            ),
            SimpleNamespace(video=None, photo=None),  # follow-up text message
        ]
        assert extract_file_ids(messages) == [  # type: ignore[arg-type]
            CachedItem(kind="video", file_id="vid-1"),
            CachedItem(kind="photo", file_id="big"),
        ]
