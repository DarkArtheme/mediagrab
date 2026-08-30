"""reelsbot: Telegram bot that turns pasted social-media links into media replies."""

from importlib.metadata import PackageNotFoundError, version

# Single source of truth is pyproject.toml; bump versions via scripts/release.sh.
try:
    __version__ = version("reelsbot")
except PackageNotFoundError:  # imported from a checkout without an install
    __version__ = "0.0.0+unknown"
