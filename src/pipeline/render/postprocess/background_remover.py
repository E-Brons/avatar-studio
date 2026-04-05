"""Background remover — wraps rembg for portrait background removal."""

from __future__ import annotations

import rembg

_rembg_session = None


def _get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        _rembg_session = rembg.new_session("u2net")
    return _rembg_session


def remove_background(image_bytes: bytes) -> bytes:
    """Remove the background from *image_bytes* using rembg (u2net).

    Returns RGBA PNG bytes with the background made transparent.
    """
    return rembg.remove(image_bytes, session=_get_rembg_session())
