"""Bot configuration from env: token, whitelist, cookies path, API server URL."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """A required environment variable is missing or malformed."""


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    whitelist: frozenset[int]
    admin_user_id: int
    api_url: str | None
    ig_cookies_file: Path | None
    tiktok_cookies_file: Path | None
    db_path: Path
    download_dir: Path | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        token = env.get("BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError("BOT_TOKEN is required")

        raw_whitelist = env.get("WHITELIST_USER_IDS", "")
        try:
            whitelist = frozenset(int(part) for part in raw_whitelist.split(",") if part.strip())
        except ValueError as exc:
            msg = f"WHITELIST_USER_IDS must be comma-separated integers: {exc}"
            raise ConfigError(msg) from exc
        if not whitelist:
            raise ConfigError("WHITELIST_USER_IDS must list at least one user id")

        raw_admin = env.get("ADMIN_USER_ID", "").strip()
        if not raw_admin:
            raise ConfigError("ADMIN_USER_ID is required")
        try:
            admin_user_id = int(raw_admin)
        except ValueError as exc:
            raise ConfigError("ADMIN_USER_ID must be an integer") from exc

        api_url = env.get("TELEGRAM_API_URL", "").strip() or None
        cookies = env.get("IG_COOKIES_FILE", "").strip()
        # TikTok works anonymously; this stays unset unless that stops being true.
        tiktok_cookies = env.get("TIKTOK_COOKIES_FILE", "").strip()
        download_dir = env.get("DOWNLOAD_DIR", "").strip()

        return cls(
            bot_token=token,
            whitelist=whitelist,
            admin_user_id=admin_user_id,
            api_url=api_url,
            ig_cookies_file=Path(cookies) if cookies else None,
            tiktok_cookies_file=Path(tiktok_cookies) if tiktok_cookies else None,
            db_path=Path(env.get("DB_PATH", "").strip() or "cache.sqlite3"),
            download_dir=Path(download_dir) if download_dir else None,
        )
