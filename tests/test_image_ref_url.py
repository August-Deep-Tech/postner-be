from __future__ import annotations

from app.posts import service as post_service


def test_rebuilds_url_from_key_against_current_settings(settings):
    """A URL cached at upload time under an old storage host must not win
    once the storage backend/domain has changed -- the key is durable, the
    cached url is not."""
    ref = {
        "key": "tenants/t1/posts/p1/sources/image.png",
        "url": "http://localhost:9000/postner/tenants/t1/posts/p1/sources/image.png",
    }

    rebuilt = post_service._image_ref_url(ref, settings)

    assert rebuilt == (
        f"{settings.storage_public_base_url.rstrip('/')}"
        "/tenants/t1/posts/p1/sources/image.png"
    )
    assert "localhost:9000" not in rebuilt


def test_falls_back_to_stored_url_without_settings():
    ref = {
        "key": "tenants/t1/posts/p1/sources/image.png",
        "url": "https://pub-example.r2.dev/tenants/t1/posts/p1/sources/image.png",
    }

    assert post_service._image_ref_url(ref) == ref["url"]


def test_falls_back_to_stored_url_when_no_key():
    ref = {"url": "https://pub-example.r2.dev/legacy.png"}

    assert post_service._image_ref_url(ref, None) == ref["url"]


def test_legacy_string_ref_is_returned_as_is(settings):
    assert (
        post_service._image_ref_url("https://pub-example.r2.dev/legacy.png", settings)
        == "https://pub-example.r2.dev/legacy.png"
    )


def test_missing_ref_returns_none(settings):
    assert post_service._image_ref_url(None, settings) is None
    assert post_service._image_ref_url({}, settings) is None
