"""Phase 0 smoke test: every module is importable."""

import importlib

import pytest

MODULES = [
    "mediagrab",
    "mediagrab.models",
    "mediagrab.errors",
    "mediagrab.router",
    "mediagrab._proc",
    "mediagrab.providers",
    "mediagrab.providers.base",
    "mediagrab.providers.instagram",
    "mediagrab.providers.instagram.provider",
    "mediagrab.providers.instagram.ytdlp",
    "mediagrab.providers.instagram.gallerydl",
    "mediagrab.providers.instagram._classify",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module: str) -> None:
    importlib.import_module(module)
