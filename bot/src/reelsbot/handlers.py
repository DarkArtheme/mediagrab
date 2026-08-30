"""Message handlers: whitelist filter, /start, /help, and the link handler."""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path
from time import monotonic

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, Filter
from aiogram.types import Message

import mediagrab
import reelsbot
from mediagrab import MediaPost, diagnostics
from mediagrab import Router as MediaRouter
from mediagrab.errors import (
    AuthExpired,
    ExtractionFailed,
    MediaGrabError,
    PostUnavailable,
    RateLimited,
    UnsupportedUrl,
)
from mediagrab.providers.base import Provider
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


class AdminOnly(Filter):
    """Pass only messages from the admin user."""

    async def __call__(self, message: Message, config: Config) -> bool:
        return message.from_user is not None and message.from_user.id == config.admin_user_id


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


@router.message(Command("health"), AdminOnly())
async def cmd_health(
    message: Message, config: Config, cache: CacheRepository, started_at: float
) -> None:
    """Admin self-check: package/tool versions, cookies, cache DB, uptime."""
    lines = [f"🩺 reelsbot {reelsbot.__version__} · mediagrab {mediagrab.__version__}"]

    for tool in diagnostics.EXTRACTOR_TOOLS:
        version = await diagnostics.tool_version(tool)
        lines.append(f"✅ {tool} {version}" if version else f"❌ {tool}: not available")

    lines.append(_cookies_status("IG cookies", config.ig_cookies_file, required=True))
    if config.tiktok_cookies_file is not None:
        lines.append(_cookies_status("TikTok cookies", config.tiktok_cookies_file, required=True))
    else:
        lines.append("▫️ TikTok cookies: not configured (anonymous mode)")

    try:
        lines.append(f"✅ cache: {cache.count()} post(s) at {config.db_path}")
    except sqlite3.Error as exc:
        lines.append(f"❌ cache: {exc}")

    lines.append(f"⏱ uptime: {_format_uptime(monotonic() - started_at)}")
    await message.answer("\n".join(lines))


def _cookies_status(label: str, path: Path | None, *, required: bool) -> str:
    if path is None:
        return f"{'⚠️' if required else '▫️'} {label}: not configured"
    if not path.is_file():
        return f"❌ {label}: {path} does not exist"
    return f"✅ {label}: {path}"


def _format_uptime(seconds: float) -> str:
    minutes, _ = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


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

    assert message.from_user is not None  # guaranteed by Whitelisted
    req = uuid.uuid4().hex[:8]
    started = monotonic()
    log.info(
        "req=%s uid=%s user=%d url=%s", req, route.uid, message.from_user.id, route.canonical_url
    )

    cached = cache.get(route.uid)
    if cached is not None:
        try:
            await delivery.send_cached(bot, message.chat.id, cached)
            log.info("req=%s uid=%s cache hit, total=%.1fs", req, route.uid, monotonic() - started)
            return
        except TelegramBadRequest:
            # file_ids can go stale (e.g. after a Bot API server switch);
            # drop the entry and fall through to a fresh extraction.
            log.warning("req=%s uid=%s stale cache entry; re-extracting", req, route.uid)
            cache.delete(route.uid)

    if not gate.acquire_user(message.from_user.id):
        await message.answer("Hold on — I'm still working on your previous link.")
        return

    status = await message.answer("⏳ Downloading…")
    post: MediaPost | None = None
    try:
        async with gate.slot():
            extract_started = monotonic()
            post = await _resolve_with_retry(provider, route.canonical_url, req)
        deliver_started = monotonic()
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
        log.info(
            "req=%s uid=%s done items=%d extract=%.1fs deliver=%.1fs total=%.1fs",
            req,
            route.uid,
            len(post.items),
            deliver_started - extract_started,
            monotonic() - deliver_started,
            monotonic() - started,
        )
    except MediaGrabError as err:
        log.warning(
            "req=%s uid=%s failed after %.1fs: %r", req, route.uid, monotonic() - started, err
        )
        await status.edit_text(friendly_error(err))
        if isinstance(err, AuthExpired):
            await _notify_admin(bot, config, route.provider, route.canonical_url)
    except Exception:
        log.exception(
            "req=%s uid=%s unexpected failure after %.1fs", req, route.uid, monotonic() - started
        )
        await status.edit_text(_FALLBACK_REPLY)
        raise
    else:
        await status.delete()
    finally:
        gate.release_user(message.from_user.id)
        _cleanup(post)


async def _resolve_with_retry(provider: Provider, url: str, req: str) -> MediaPost:
    """Resolve ``url``, retrying once on :class:`ExtractionFailed`.

    Only that error is retried: it covers transient extractor hiccups (network
    blips, flaky endpoints), while the other taxonomy members are stable facts
    (bad URL, deleted post, dead cookies, throttling) a retry can't change.
    """
    try:
        return await provider.resolve(url)
    except ExtractionFailed as err:
        log.warning("req=%s transient extraction failure, retrying once: %s", req, err)
        return await provider.resolve(url)


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
