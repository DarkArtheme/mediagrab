"""Config.from_env parsing."""

from pathlib import Path

import pytest

from reelsbot.config import Config, ConfigError

FULL_ENV = {
    "BOT_TOKEN": "123:abc",
    "WHITELIST_USER_IDS": "111, 222 ,333",
    "ADMIN_USER_ID": "111",
    "TELEGRAM_API_URL": "http://telegram-bot-api:8081",
    "IG_COOKIES_FILE": "/data/cookies/instagram.txt",
    "TIKTOK_COOKIES_FILE": "/data/cookies/tiktok.txt",
    "DB_PATH": "/data/db/cache.sqlite3",
    "DOWNLOAD_DIR": "/data/tmp",
}


def test_full_env() -> None:
    config = Config.from_env(FULL_ENV)
    assert config.bot_token == "123:abc"
    assert config.whitelist == frozenset({111, 222, 333})
    assert config.admin_user_id == 111
    assert config.api_url == "http://telegram-bot-api:8081"
    assert config.ig_cookies_file == Path("/data/cookies/instagram.txt")
    assert config.tiktok_cookies_file == Path("/data/cookies/tiktok.txt")
    assert config.db_path == Path("/data/db/cache.sqlite3")
    assert config.download_dir == Path("/data/tmp")


def test_minimal_env_defaults() -> None:
    config = Config.from_env(
        {"BOT_TOKEN": "123:abc", "WHITELIST_USER_IDS": "111", "ADMIN_USER_ID": "111"}
    )
    assert config.api_url is None
    assert config.ig_cookies_file is None
    assert config.tiktok_cookies_file is None
    assert config.db_path == Path("cache.sqlite3")
    assert config.download_dir is None


def test_empty_strings_mean_unset() -> None:
    env = FULL_ENV | {"TELEGRAM_API_URL": "", "IG_COOKIES_FILE": "", "DOWNLOAD_DIR": ""}
    config = Config.from_env(env)
    assert config.api_url is None
    assert config.ig_cookies_file is None
    assert config.download_dir is None


@pytest.mark.parametrize("missing", ["BOT_TOKEN", "WHITELIST_USER_IDS", "ADMIN_USER_ID"])
def test_required_vars(missing: str) -> None:
    env = {k: v for k, v in FULL_ENV.items() if k != missing}
    with pytest.raises(ConfigError):
        Config.from_env(env)


def test_bad_whitelist() -> None:
    with pytest.raises(ConfigError):
        Config.from_env(FULL_ENV | {"WHITELIST_USER_IDS": "111,bogus"})


def test_bad_admin_id() -> None:
    with pytest.raises(ConfigError):
        Config.from_env(FULL_ENV | {"ADMIN_USER_ID": "not-a-number"})
