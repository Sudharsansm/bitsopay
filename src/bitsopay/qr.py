"""QR code rendering for UPI payments (powered by ``segno``, pure Python)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Union

import segno

from .models import UPIPayment

_ERROR_LEVELS = {"L", "M", "Q", "H"}


def _make(payment: UPIPayment, error: str) -> segno.QRCode:
    error = error.upper()
    if error not in _ERROR_LEVELS:
        raise ValueError(f"error must be one of {sorted(_ERROR_LEVELS)}")
    return segno.make(payment.uri, error=error, micro=False)


def qr_png(payment: UPIPayment, *, scale: int = 10, border: int = 4, error: str = "M") -> bytes:
    """Return the QR code as PNG bytes."""
    buf = io.BytesIO()
    _make(payment, error).save(buf, kind="png", scale=scale, border=border)
    return buf.getvalue()


def qr_svg(payment: UPIPayment, *, scale: int = 10, border: int = 4, error: str = "M") -> str:
    """Return the QR code as an SVG document string."""
    buf = io.BytesIO()
    _make(payment, error).save(buf, kind="svg", scale=scale, border=border, xmldecl=False)
    return buf.getvalue().decode("utf-8")


def qr_data_uri(payment: UPIPayment, *, scale: int = 10, border: int = 4, error: str = "M") -> str:
    """Return a ``data:image/png;base64,...`` URI, ready for an ``<img src>``."""
    return _make(payment, error).png_data_uri(scale=scale, border=border)


def save_qr(
    payment: UPIPayment,
    path: Union[str, Path],
    *,
    scale: int = 10,
    border: int = 4,
    error: str = "M",
) -> Path:
    """Write the QR code to ``path``; format is chosen by extension (.png / .svg)."""
    target = Path(path)
    ext = target.suffix.lower()
    if ext not in {".png", ".svg"}:
        raise ValueError("Output path must end in .png or .svg")
    _make(payment, error).save(str(target), scale=scale, border=border)
    return target


# --- QR codes for arbitrary text (used for expiring session QR codes) -------


def _make_text(text: str, error: str) -> segno.QRCode:
    error = error.upper()
    if error not in _ERROR_LEVELS:
        raise ValueError(f"error must be one of {sorted(_ERROR_LEVELS)}")
    return segno.make(text, error=error, micro=False)


def text_qr_png(text: str, *, scale: int = 10, border: int = 4, error: str = "M") -> bytes:
    """PNG bytes of a QR code encoding ``text`` (e.g. a payment link URL)."""
    buf = io.BytesIO()
    _make_text(text, error).save(buf, kind="png", scale=scale, border=border)
    return buf.getvalue()


def text_qr_svg(text: str, *, scale: int = 10, border: int = 4, error: str = "M") -> str:
    buf = io.BytesIO()
    _make_text(text, error).save(buf, kind="svg", scale=scale, border=border, xmldecl=False)
    return buf.getvalue().decode("utf-8")


def save_text_qr(text: str, path: Union[str, Path], *, scale: int = 10, border: int = 4, error: str = "M") -> Path:
    target = Path(path)
    if target.suffix.lower() not in {".png", ".svg"}:
        raise ValueError("Output path must end in .png or .svg")
    _make_text(text, error).save(str(target), scale=scale, border=border)
    return target
