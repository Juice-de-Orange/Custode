"""Normalize user image uploads (Pillow). Re-encodes to JPEG — which **strips all EXIF** (incl. GPS,
which is PII) — and caps the dimensions. Rejects anything that isn't a decodable image (422)."""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

from app.kernel.http.problem import ProblemException

_MAX_DIM = 1600
_JPEG_QUALITY = 82


def normalize_image(raw: bytes) -> bytes:
    """Return a clean JPEG (EXIF stripped, dimensions capped). Raises 422 on a non-image."""
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()  # force decode now — catches truncated / bomb inputs here, not later
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ProblemException(
            slug="invalid_image", title="Kein gültiges Bild", status=422
        ) from exc
    rgb = image.convert("RGB")  # drop alpha + any EXIF; the JPEG re-save carries no metadata
    rgb.thumbnail((_MAX_DIM, _MAX_DIM))
    out = io.BytesIO()
    rgb.save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue()
