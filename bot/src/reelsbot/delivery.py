"""Media delivery: sendVideo / sendPhoto / sendMediaGroup, caption overflow handling.

Telegram limits: 1024 chars for a media caption, 4096 for a text message,
10 items per media group. A too-long caption is truncated (with an ellipsis)
on the media itself and the full text follows as separate text message(s).
In albums only the first item carries the caption.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo, Message

from mediagrab import MediaItem, MediaPost

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096
ALBUM_LIMIT = 10


def split_caption(text: str) -> tuple[str, list[str]]:
    """Return ``(media_caption, follow_up_messages)`` for ``text``.

    Fits within :data:`CAPTION_LIMIT` → unchanged, no follow-ups. Otherwise the
    caption is truncated with an ellipsis and the *full* text is chunked into
    follow-up messages of at most :data:`TEXT_LIMIT` chars each.
    """
    if len(text) <= CAPTION_LIMIT:
        return text, []
    truncated = text[: CAPTION_LIMIT - 1] + "…"
    chunks = [text[i : i + TEXT_LIMIT] for i in range(0, len(text), TEXT_LIMIT)]
    return truncated, chunks


def _input_media(item: MediaItem, caption: str | None) -> InputMediaPhoto | InputMediaVideo:
    file = FSInputFile(item.path)
    if item.kind == "video":
        return InputMediaVideo(
            media=file,
            caption=caption,
            supports_streaming=True,
            width=item.width,
            height=item.height,
            duration=round(item.duration) if item.duration else None,
        )
    return InputMediaPhoto(media=file, caption=caption)


async def send_post(bot: Bot, chat_id: int, post: MediaPost) -> list[Message]:
    """Send ``post`` to ``chat_id``; return every message sent (for caching)."""
    caption, follow_ups = split_caption(post.caption)
    sent: list[Message] = []

    if len(post.items) == 1:
        item = post.items[0]
        if item.kind == "video":
            sent.append(
                await bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(item.path),
                    caption=caption or None,
                    supports_streaming=True,
                    width=item.width,
                    height=item.height,
                    duration=round(item.duration) if item.duration else None,
                )
            )
        else:
            sent.append(
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(item.path),
                    caption=caption or None,
                )
            )
    else:
        first = True
        for start in range(0, len(post.items), ALBUM_LIMIT):
            chunk = post.items[start : start + ALBUM_LIMIT]
            media = []
            for item in chunk:
                media.append(_input_media(item, (caption or None) if first else None))
                first = False
            sent.extend(await bot.send_media_group(chat_id=chat_id, media=media))

    for text in follow_ups:
        sent.append(await bot.send_message(chat_id=chat_id, text=text))
    return sent
