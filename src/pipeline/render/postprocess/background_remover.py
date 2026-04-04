"""Background remover — wraps rembg for portrait background removal."""

from __future__ import annotations


def remove_background(image_bytes: bytes) -> bytes:
    """Remove the background from *image_bytes* using rembg (u2net).

    Returns RGBA PNG bytes with the background made transparent.
    """
    import rembg

    from pipeline.step_d_make_abbreviation import _get_rembg_session

    return rembg.remove(image_bytes, session=_get_rembg_session())
