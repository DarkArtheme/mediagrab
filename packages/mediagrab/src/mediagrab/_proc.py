"""Async subprocess runner shared by all extractor wrappers.

Every external tool call goes through :func:`run_tool`, so tool-not-installed
and timeout failures surface as :class:`ExtractionFailed` instead of leaking
raw OS exceptions past the provider.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from mediagrab.errors import ExtractionFailed


@dataclass(slots=True)
class ToolResult:
    returncode: int
    stdout: str
    stderr: str


async def run_tool(cmd: Sequence[str], *, timeout: float) -> ToolResult:
    """Run ``cmd``, capture output, and enforce ``timeout`` seconds."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ExtractionFailed(f"{cmd[0]} is not installed or not on PATH") from exc

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise ExtractionFailed(f"{cmd[0]} timed out after {timeout:g}s") from exc

    return ToolResult(
        returncode=proc.returncode or 0,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )
