from pathlib import Path

from mediagrab.models import MediaItem, MediaPost


def test_media_item_optional_fields_default_to_none() -> None:
    item = MediaItem(kind="photo", path=Path("/tmp/x.jpg"))
    assert item.width is None
    assert item.height is None
    assert item.duration is None


def test_media_post_holds_items_and_metadata() -> None:
    video = MediaItem(kind="video", path=Path("/tmp/x.mp4"), width=1080, height=1920, duration=12.5)
    post = MediaPost(
        items=[video],
        caption="hello",
        author="someone",
        source_url="https://www.instagram.com/reel/ABC123/",
        uid="ABC123",
    )
    assert post.items == [video]
    assert post.uid == "ABC123"
