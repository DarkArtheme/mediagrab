"""Bot startup: dispatcher wiring, long polling, and graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from time import monotonic

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from dotenv import load_dotenv

from mediagrab import InstagramProvider, TikTokProvider
from mediagrab import Router as MediaRouter
from reelsbot import handlers
from reelsbot.cache import CacheRepository
from reelsbot.config import Config
from reelsbot.throttle import ExtractionGate

log = logging.getLogger(__name__)

# How long shutdown waits for in-flight downloads/deliveries before giving up.
# Keep this below the container's stop grace period so the wait can finish.
SHUTDOWN_GRACE = 30.0

# Per-post temp dirs the providers create under DOWNLOAD_DIR (mkdtemp prefixes).
_TEMP_DIR_PREFIXES = ("ig-", "tt-")


def build_media_router(config: Config) -> MediaRouter:
    media_router = MediaRouter()
    media_router.register(
        "instagram",
        InstagramProvider(
            cookies_file=config.ig_cookies_file,
            download_dir=config.download_dir,
        ),
    )
    media_router.register(
        "tiktok",
        TikTokProvider(
            cookies_file=config.tiktok_cookies_file,
            download_dir=config.download_dir,
        ),
    )
    return media_router


def sweep_download_dir(download_dir: Path | None) -> int:
    """Remove per-post temp dirs a previous run left behind (e.g. a crash
    mid-download). Only known-prefix directories are touched, so a shared
    DOWNLOAD_DIR never loses unrelated files. Returns the number removed."""
    if download_dir is None or not download_dir.is_dir():
        return 0
    removed = 0
    for entry in download_dir.iterdir():
        if entry.is_dir() and entry.name.startswith(_TEMP_DIR_PREFIXES):
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    if removed:
        log.info("removed %d leftover download dir(s) from %s", removed, download_dir)
    return removed


async def on_shutdown(gate: ExtractionGate, cache: CacheRepository) -> None:
    """Drain in-flight jobs, then release resources.

    aiogram stops polling on SIGINT/SIGTERM but does not await handler tasks
    that are still running; waiting on the gate lets active downloads finish
    delivering before the cache (and then the bot session) is closed.
    """
    busy = gate.busy_count()
    if busy:
        log.info("shutdown: waiting up to %gs for %d in-flight job(s)", SHUTDOWN_GRACE, busy)
        if not await gate.wait_idle(SHUTDOWN_GRACE):
            log.warning("shutdown: grace expired with %d job(s) unfinished", gate.busy_count())
    cache.close()
    log.info("shutdown complete")


async def run(config: Config) -> None:
    session = None
    if config.api_url:
        session = AiohttpSession(api=TelegramAPIServer.from_base(config.api_url))
    bot = Bot(token=config.bot_token, session=session)

    dispatcher = Dispatcher()
    dispatcher.include_router(handlers.router)
    dispatcher.shutdown.register(on_shutdown)

    sweep_download_dir(config.download_dir)

    log.info("starting long polling (%d whitelisted users)", len(config.whitelist))
    await bot.delete_webhook()
    await dispatcher.start_polling(
        bot,
        config=config,
        media_router=build_media_router(config),
        cache=CacheRepository(config.db_path),
        gate=ExtractionGate(),
        started_at=monotonic(),
    )


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(Config.from_env()))
