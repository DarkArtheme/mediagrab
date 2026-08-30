"""Message handlers: whitelist filter, /start, /help, and the link handler."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import replace

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, Filter
from aiogram.types import Message

from mediagrab import MediaPost
from mediagrab import Router as MediaRouter
from mediagrab.errors import (
    AuthExpired,
    MediaGrabError,
    PostUnavailable,
    RateLimited,
    UnsupportedUrl,
)
from reelsbot import delivery
from reelsbot.cache import CachedPost, CacheRepository
from reelsbot.config import Config
from reelsbot.throttle import ExtractionGate

log = logging.getLogger(__name__)

router = Router(name="reelsbot")

_URL_RE = re.compile(r"(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}/\S+", re.IGNORECASE)

_ERROR_REPLIES = {
    UnsupportedUrl: "I don't recognize that link. Send me an Instagram or TikTok post URL.",
    PostUnavailable: "That post can't be fetched — it may be private, deleted, or blocked.",
    AuthExpired: "The session expired; the admin has been notified. Please try again later.",
    RateLimited: "The platform is rate-limiting right now. Please try again in a few minutes.",
}
_FALLBACK_REPLY = "Something went wrong while fetching that link. Please try again later."


def friendly_error(err: MediaGrabError) -> str:
    """Map a mediagrab error onto a human reply."""
    for err_type, reply in _ERROR_REPLIES.items():
        if isinstance(err, err_type):
            return reply
    return _FALLBACK_REPLY


def first_url(text: str) -> str | None:
    """Return the first URL-looking token in ``text``, or None."""
    match = _URL_RE.search(text)
    return match.group(0) if match else None


class Whitelisted(Filter):
    """Pass only messages from whitelisted user ids."""

    async def __call__(self, message: Message, config: Config) -> bool:
        return message.from_user is not None and message.from_user.id in config.whitelist


@router.message(Command("start", "help"), Whitelisted())
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Send me an Instagram or TikTok link and I'll reply with the media and its "
        "description.\n\n"
        "Supported: Instagram reels (https://www.instagram.com/reel/…) and posts "
        "(https://www.instagram.com/p/…), including photo and mixed carousels; "
        "TikTok videos and photo slideshows, including short share links "
        "(https://vt.tiktok.com/…)."
    )


@router.message(Whitelisted(), F.text)
async def handle_link(
    message: Message,
    bot: Bot,
    config: Config,
    media_router: MediaRouter,
    cache: CacheRepository,
    gate: ExtractionGate,
) -> None:
    url = first_url(message.text or "")
    if url is None:
        await message.answer("Send me an Instagram or TikTok link and I'll fetch it.")
        return

    try:
        provider, route = media_router.resolve(url)
    except UnsupportedUrl as err:
        await message.answer(friendly_error(err))
        return

    cached = cache.get(route.uid)
    if cached is not None:
        try:
            await delivery.send_cached(bot, message.chat.id, cached)
            return
        except TelegramBadRequest:
            # file_ids can go stale (e.g. after a Bot API server switch);
            # drop the entry and fall through to a fresh extraction.
            log.warning("stale cache entry for %s; re-extracting", route.uid)
            cache.delete(route.uid)

    assert message.from_user is not None  # guaranteed by Whitelisted
    if not gate.acquire_user(message.from_user.id):
        await message.answer("Hold on — I'm still working on your previous link.")
        return

    status = await message.answer("⏳ Downloading…")
    post: MediaPost | None = None
    try:
        async with gate.slot():
            post = await provider.resolve(route.canonical_url)
        sent = await delivery.send_post(bot, message.chat.id, post)
        record = CachedPost(
            uid=route.uid,
            provider=route.provider,
            kind=route.kind,
            items=delivery.extract_file_ids(sent),
            caption=post.caption,
        )
        cache.put(record)
        if post.uid != route.uid:
            # Short links (vt.tiktok.com/…) route under their token but resolve
            # to the real post id; caching both keys lets the same token and
            # the long URL hit the cache on later pastes.
            cache.put(replace(record, uid=post.uid))
    except MediaGrabError as err:
        log.warning("resolve failed for %s: %r", route.canonical_url, err)
        await status.edit_text(friendly_error(err))
        if isinstance(err, AuthExpired):
            await _notify_admin(bot, config, route.provider, route.canonical_url)
    except Exception:
        log.exception("unexpected failure for %s", route.canonical_url)
        await status.edit_text(_FALLBACK_REPLY)
        raise
    else:
        await status.delete()
    finally:
        gate.release_user(message.from_user.id)
        _cleanup(post)


@router.message(Whitelisted())
async def non_text(message: Message) -> None:
    """Whitelisted, but not a text message."""
    await message.answer("Send me an Instagram or TikTok link and I'll fetch it.")


@router.message()
async def refuse(message: Message) -> None:
    """Anything that got here was not whitelisted."""
    await message.answer("Sorry, this is a private bot — you're not on the access list.")


_COOKIES_ENV_VARS = {"instagram": "IG_COOKIES_FILE", "tiktok": "TIKTOK_COOKIES_FILE"}


async def _notify_admin(bot: Bot, config: Config, provider: str, url: str) -> None:
    env_var = _COOKIES_ENV_VARS.get(provider, "the cookies file")
    try:
        await bot.send_message(
            chat_id=config.admin_user_id,
            text=f"⚠️ {provider} cookies look expired (AuthExpired while fetching {url}). "
            f"Refresh {env_var}.",
        )
    except Exception:
        log.exception("failed to notify admin about AuthExpired")


def _cleanup(post: MediaPost | None) -> None:
    """Delete the temp directory the provider downloaded ``post`` into."""
    if post is None or not post.items:
        return
    shutil.rmtree(post.items[0].path.parent, ignore_errors=True)
