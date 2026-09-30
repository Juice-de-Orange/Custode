"""Pure tests for the blob storage adapter + image normalization (no DB, no network)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.kernel.http.problem import ProblemException
from app.kernel.images import normalize_image
from app.kernel.storage import FilesystemStorage, NullStorage


def _png(color: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (12, 8), color).save(out, format="PNG")
    return out.getvalue()


def test_normalize_image_reencodes_to_jpeg() -> None:
    result = normalize_image(_png())
    assert result[:2] == b"\xff\xd8"  # JPEG magic — re-encoded (so any EXIF is gone)
    assert Image.open(io.BytesIO(result)).format == "JPEG"


def test_normalize_image_caps_dimensions() -> None:
    out = io.BytesIO()
    Image.new("RGB", (4000, 3000), "blue").save(out, format="PNG")
    image = Image.open(io.BytesIO(normalize_image(out.getvalue())))
    assert max(image.size) <= 1600


def test_normalize_image_rejects_non_image() -> None:
    with pytest.raises(ProblemException) as exc:
        normalize_image(b"definitely not an image")
    assert exc.value.status == 422


def test_filesystem_storage_roundtrip(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    assert storage.enabled is True
    storage.put("recipe-1.jpg", b"bytes")
    assert storage.get("recipe-1.jpg") == b"bytes"
    assert storage.get("missing.jpg") is None
    storage.delete("recipe-1.jpg")
    assert storage.get("recipe-1.jpg") is None


def test_filesystem_storage_rejects_traversal_keys(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)
    storage.put("../escape.jpg", b"x")  # sanitized to the last segment
    assert not (tmp_path.parent / "escape.jpg").exists()
    assert storage.get("escape.jpg") == b"x"


def test_null_storage_is_disabled() -> None:
    storage = NullStorage()
    assert storage.enabled is False
    assert storage.get("k") is None
    with pytest.raises(RuntimeError):
        storage.put("k", b"x")
