"""Command-line entry point: ``mediagrab URL [URL ...]``.

Machine-first output for agent pipelines: one JSON object per URL on stdout
(JSONL), progress on stderr. Exit code 0 when every URL succeeded, 1 when any
failed, 2 on bad invocation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mediagrab.grab import MediaGrab


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mediagrab",
        description=(
            "Download Instagram reels/posts and TikTok videos/slideshows; "
            "print one JSON result per URL (JSONL) to stdout."
        ),
    )
    parser.add_argument("urls", nargs="*", metavar="URL", help="post URLs to download")
    parser.add_argument(
        "--input",
        type=Path,
        metavar="FILE",
        help="file with one URL per line ('-' for stdin); blank lines and # comments skipped",
    )
    parser.add_argument(
        "--out",
        type=Path,
        metavar="DIR",
        help="directory to download into (default: system temp)",
    )
    parser.add_argument(
        "--ig-cookies",
        type=Path,
        metavar="FILE",
        help="Instagram cookies.txt (default: $IG_COOKIES_FILE)",
    )
    parser.add_argument(
        "--tiktok-cookies",
        type=Path,
        metavar="FILE",
        help="TikTok cookies.txt (default: $TIKTOK_COOKIES_FILE; usually not needed)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="max simultaneous downloads (default: 2)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="per-post extractor timeout in seconds (default: 600)",
    )
    return parser


def _read_url_file(path: Path) -> list[str]:
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    urls = list(args.urls)
    if args.input is not None:
        urls.extend(_read_url_file(args.input))
    if not urls:
        parser.error("no URLs given (pass them as arguments or via --input)")

    grabber = MediaGrab(
        download_dir=args.out,
        instagram_cookies=args.ig_cookies,
        tiktok_cookies=args.tiktok_cookies,
        timeout=args.timeout,
    )

    print(f"downloading {len(urls)} post(s)…", file=sys.stderr)
    results = asyncio.run(grabber.fetch_many(urls, concurrency=args.concurrency))

    failures = 0
    for result in results:
        if not result.ok:
            failures += 1
        print(json.dumps(result.to_dict(), ensure_ascii=False), flush=True)

    print(f"done: {len(results) - failures} ok, {failures} failed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
