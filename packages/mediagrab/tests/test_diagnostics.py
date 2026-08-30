"""diagnostics: tool_version reporting with the subprocess faked."""

from mediagrab import _proc, diagnostics
from mediagrab._proc import ToolResult
from mediagrab.errors import ExtractionFailed


def install_fake(monkeypatch, handler):
    calls: list[list[str]] = []

    async def fake_run_tool(cmd, *, timeout):
        calls.append(list(cmd))
        return handler(list(cmd))

    monkeypatch.setattr(_proc, "run_tool", fake_run_tool)
    return calls


async def test_reports_first_line_of_version_output(monkeypatch):
    calls = install_fake(monkeypatch, lambda cmd: ToolResult(0, "2026.01.01\nextra noise\n", ""))
    assert await diagnostics.tool_version("yt-dlp") == "2026.01.01"
    assert calls[0][-1] == "--version"


async def test_nonzero_exit_reports_none(monkeypatch):
    install_fake(monkeypatch, lambda cmd: ToolResult(1, "", "boom"))
    assert await diagnostics.tool_version("yt-dlp") is None


async def test_empty_output_reports_none(monkeypatch):
    install_fake(monkeypatch, lambda cmd: ToolResult(0, "", ""))
    assert await diagnostics.tool_version("gallery-dl") is None


async def test_missing_tool_reports_none(monkeypatch):
    def raise_missing(cmd):
        raise ExtractionFailed(f"{cmd[0]} is not installed or not on PATH")

    install_fake(monkeypatch, raise_missing)
    assert await diagnostics.tool_version("gallery-dl") is None
