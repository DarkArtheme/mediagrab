"""Bot startup: dispatcher wiring and long polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from dotenv import load_dotenv

from mediagrab import InstagramProvider
from mediagrab import Router as MediaRouter
from reelsbot import handlers
from reelsbot.cache import CacheRepository
from reelsbot.config import Config
from reelsbot.throttle import ExtractionGate

log = logging.getLogger(__name__)


def build_media_router(config: Config) -> MediaRouter:
    media_router = MediaRouter()
    media_router.register(
        "instagram",
        InstagramProvider(
            cookies_file=config.ig_cookies_file,
            download_dir=config.download_dir,
        ),
    )
    return media_router


async def run(config: Config) -> None:
    session = None
    if config.api_url:
        session = AiohttpSession(api=TelegramAPIServer.from_base(config.api_url))
    bot = Bot(token=config.bot_token, session=session)

    dispatcher = Dispatcher()
    dispatcher.include_router(handlers.router)

    log.info("starting long polling (%d whitelisted users)", len(config.whitelist))
    await bot.delete_webhook()
    await dispatcher.start_polling(
        bot,
        config=config,
        media_router=build_media_router(config),
        cache=CacheRepository(config.db_path),
        gate=ExtractionGate(),
    )


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run(Config.from_env()))
