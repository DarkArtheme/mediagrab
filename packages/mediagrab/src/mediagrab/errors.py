"""Error taxonomy. All user-facing failures map to one of these; the bot
translates them to human messages and never sees raw extractor errors."""


class MediaGrabError(Exception):
    """Base class for all mediagrab errors."""


class UnsupportedUrl(MediaGrabError):
    """The URL is not one any registered provider can handle."""


class PostUnavailable(MediaGrabError):
    """The post is deleted, private, geo-blocked, or otherwise inaccessible."""


class AuthExpired(MediaGrabError):
    """The provider's credentials (e.g. Instagram session cookies) no longer work."""


class RateLimited(MediaGrabError):
    """The platform is throttling us; retrying later may succeed."""


class ExtractionFailed(MediaGrabError):
    """The extractor failed for a reason not covered by the other errors."""
