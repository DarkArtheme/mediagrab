"""Media delivery: sendVideo / sendPhoto / sendMediaGroup, caption overflow handling.

Telegram limits: 1024 chars for a media caption, 4096 for a text message,
10 items per media group. A too-long caption is truncated (with an ellipsis)
on the media itself and the full text follows as separate text message(s).
In albums only the first item carries the caption.

Media can come from local files (first delivery) or from cached Telegram
file_ids (repeat delivery) — both flow through the same sender.
"""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo, Message

from mediagrab import MediaKind, MediaPost
from reelsbot.cache import CachedItem, CachedPost

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096
ALBUM_LIMIT = 10

# Media uploads can far outlive aiogram's default 60s request timeout
# (a reel is tens of MB going through the cloud Bot API).
UPLOAD_TIMEOUT = 300


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


@dataclass(slots=True)
class _Payload:
    """One media item ready to send: a local file or a Telegram file_id."""

    kind: MediaKind
    media: FSInputFile | str
    width: int | None = None
    height: int | None = None
    duration: int | None = None


def _input_media(payload: _Payload, caption: str | None) -> InputMediaPhoto | InputMediaVideo:
    if payload.kind == "video":
        return InputMediaVideo(
            media=payload.media,
            caption=caption,
            supports_streaming=True,
            width=payload.width,
            height=payload.height,
            duration=payload.duration,
        )
    return InputMediaPhoto(media=payload.media, caption=caption)


async def _deliver(
    bot: Bot, chat_id: int, payloads: list[_Payload], caption_text: str
) -> list[Message]:
    caption, follow_ups = split_caption(caption_text)
    sent: list[Message] = []

    if len(payloads) == 1:
        payload = payloads[0]
        if payload.kind == "video":
            sent.append(
                await bot.send_video(
                    chat_id=chat_id,
                    video=payload.media,
                    caption=caption or None,
                    supports_streaming=True,
                    width=payload.width,
                    height=payload.height,
                    duration=payload.duration,
                    request_timeout=UPLOAD_TIMEOUT,
                )
            )
        else:
            sent.append(
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=payload.media,
                    caption=caption or None,
                    request_timeout=UPLOAD_TIMEOUT,
                )
            )
    else:
        first = True
        for start in range(0, len(payloads), ALBUM_LIMIT):
            chunk = payloads[start : start + ALBUM_LIMIT]
            media = []
            for payload in chunk:
                media.append(_input_media(payload, (caption or None) if first else None))
                first = False
            sent.extend(
                await bot.send_media_group(
                    chat_id=chat_id, media=media, request_timeout=UPLOAD_TIMEOUT
                )
            )

    for text in follow_ups:
        sent.append(await bot.send_message(chat_id=chat_id, text=text))
    return sent


async def send_post(bot: Bot, chat_id: int, post: MediaPost) -> list[Message]:
    """Send a freshly downloaded ``post``; return every message sent."""
    payloads = [
        _Payload(
            kind=item.kind,
            media=FSInputFile(item.path),
            width=item.width,
            height=item.height,
            duration=round(item.duration) if item.duration else None,
        )
        for item in post.items
    ]
    return await _deliver(bot, chat_id, payloads, post.caption)


async def send_cached(bot: Bot, chat_id: int, cached: CachedPost) -> list[Message]:
    """Re-send a post from cached Telegram file_ids — no download involved."""
    payloads = [_Payload(kind=item.kind, media=item.file_id) for item in cached.items]
    return await _deliver(bot, chat_id, payloads, cached.caption)


def extract_file_ids(messages: list[Message]) -> list[CachedItem]:
    """Pull cacheable file_ids out of sent messages (text follow-ups skipped)."""
    items: list[CachedItem] = []
    for message in messages:
        if message.video is not None:
            items.append(CachedItem(kind="video", file_id=message.video.file_id))
        elif message.photo:
            # photo is a list of sizes; the last one is the original resolution
            items.append(CachedItem(kind="photo", file_id=message.photo[-1].file_id))
    return items
