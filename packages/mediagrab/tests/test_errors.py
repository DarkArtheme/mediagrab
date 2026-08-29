import pytest

from mediagrab import errors


@pytest.mark.parametrize(
    "error",
    [
        errors.UnsupportedUrl,
        errors.PostUnavailable,
        errors.AuthExpired,
        errors.RateLimited,
        errors.ExtractionFailed,
    ],
)
def test_taxonomy_shares_a_common_base(error: type[Exception]) -> None:
    assert issubclass(error, errors.MediaGrabError)
    assert issubclass(error, Exception)
