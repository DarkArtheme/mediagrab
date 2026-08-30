import json
from pathlib import Path

import pytest

from mediagrab import cli
from mediagrab.errors import PostUnavailable
from mediagrab.grab import GrabResult
from mediagrab.models import MediaItem, MediaPost

GOOD_URL = "https://www.instagram.com/reel/AAAAAAA/"
BAD_URL = "https://www.instagram.com/reel/DEADDEAD/"


class FakeGrab:
    """Records constructor kwargs; succeeds unless the URL contains DEADDEAD."""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs) -> None:
        FakeGrab.last_kwargs = kwargs

    async def fetch_many(self, urls, *, concurrency=2):
        results = []
        for url in urls:
            if "DEADDEAD" in url:
                results.append(GrabResult(url=url, error=PostUnavailable(url)))
            else:
                post = MediaPost(
                    items=[MediaItem(kind="video", path=Path("/tmp/a.mp4"))],
                    caption="hi",
                    author="a",
                    source_url=url,
                    uid="AAAAAAA",
                )
                results.append(GrabResult(url=url, post=post))
        return results


@pytest.fixture(autouse=True)
def fake_grab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "MediaGrab", FakeGrab)


def read_jsonl(capsys: pytest.CaptureFixture) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line]


def test_success_exit_code_and_jsonl(capsys: pytest.CaptureFixture) -> None:
    code = cli.main([GOOD_URL])
    assert code == 0
    (record,) = read_jsonl(capsys)
    assert record["ok"] is True
    assert record["post"]["uid"] == "AAAAAAA"


def test_failure_sets_exit_code(capsys: pytest.CaptureFixture) -> None:
    code = cli.main([GOOD_URL, BAD_URL])
    assert code == 1
    records = read_jsonl(capsys)
    assert [r["ok"] for r in records] == [True, False]
    assert records[1]["error"]["type"] == "PostUnavailable"


def test_input_file_with_comments(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    urls = tmp_path / "urls.txt"
    urls.write_text(f"# list\n{GOOD_URL}\n\n{GOOD_URL}\n", encoding="utf-8")
    code = cli.main(["--input", str(urls)])
    assert code == 0
    assert len(read_jsonl(capsys)) == 2


def test_no_urls_is_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_options_reach_mediagrab(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cli.main(
        [
            GOOD_URL,
            "--out",
            str(tmp_path),
            "--ig-cookies",
            "/secrets/ig.txt",
            "--timeout",
            "30",
        ]
    )
    assert FakeGrab.last_kwargs == {
        "download_dir": tmp_path,
        "instagram_cookies": Path("/secrets/ig.txt"),
        "tiktok_cookies": None,
        "timeout": 30.0,
    }
