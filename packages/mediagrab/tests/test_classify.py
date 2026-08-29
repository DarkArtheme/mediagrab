import pytest

from mediagrab.errors import AuthExpired, ExtractionFailed, PostUnavailable, RateLimited
from mediagrab.providers.instagram._classify import classify_failure


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        # The combined yt-dlp message mentions both rate-limit and login;
        # with cookies configured, cookies are the actionable cause.
        ("Requested content is not available, rate-limit reached or login required", AuthExpired),
        ("Main webpage is locked behind the login page", AuthExpired),
        ("HTTP Error 401: Unauthorized", AuthExpired),
        ("HTTP Error 429: Too Many Requests", RateLimited),
        ("instagram: rate limit exceeded, slow down", RateLimited),
        ("HTTP Error 404: Not Found", PostUnavailable),
        ("This post is from a private account", PostUnavailable),
        ("The requested content does not exist", PostUnavailable),
        ("some completely novel breakage", ExtractionFailed),
        ("", ExtractionFailed),
    ],
)
def test_stderr_classification(stderr: str, expected: type[Exception]) -> None:
    error = classify_failure("yt-dlp", stderr)
    assert type(error) is expected


def test_error_message_carries_tool_and_stderr_tail() -> None:
    error = classify_failure("gallery-dl", "line1\nline2\nHTTP Error 429")
    assert "gallery-dl" in str(error)
    assert "429" in str(error)
