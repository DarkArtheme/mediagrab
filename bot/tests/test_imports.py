"""Phase 0 smoke test: every module is importable."""

import importlib

import pytest

MODULES = [
    "reelsbot",
    "reelsbot.main",
    "reelsbot.config",
    "reelsbot.handlers",
    "reelsbot.delivery",
    "reelsbot.cache",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str) -> None:
    importlib.import_module(module)
