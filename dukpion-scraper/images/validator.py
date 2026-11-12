"""Technical validation of downloaded bytes with Pillow. Never alters the image."""
from __future__ import annotations

import io

from PIL import Image
from pydantic import BaseModel

ALLOWED = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


class Validation(BaseModel):
    ok: bool
    format: str | None = None
    ext: str | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None


def validate_image_bytes(data: bytes) -> Validation:
    if not data:
        return Validation(ok=False, error="empty response")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.verify()                      # structural check
        with Image.open(io.BytesIO(data)) as im:
            im.load()                        # full decode: catches truncated files
            width, height = im.size
    except Exception as exc:  # Pillow raises many exception types
        return Validation(ok=False, error=f"not a valid image: {type(exc).__name__}: {exc}"[:200])
    if fmt not in ALLOWED:
        return Validation(ok=False, format=fmt, error=f"unsupported format {fmt}")
    return Validation(ok=True, format=fmt, ext=ALLOWED[fmt], width=width, height=height)
