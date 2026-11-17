"""A brand logo in the centre of a QR code.

QR codes survive a covered centre because of their error correction. Bitsopay keeps the logo small
(about a fifth of the QR width, on a white rounded badge) and, whenever a logo is drawn, raises the
error correction to level **H** (about 30% of the symbol may be damaged), so the code still scans
in every UPI app. Output is deterministic: the same inputs always give the same image.

``logo`` arguments accept:

* ``True`` (default): the bundled Bitsopay logo, or the file named by ``$BITSOPAY_LOGO``
  (set ``BITSOPAY_LOGO=none`` to turn the logo off everywhere)
* ``False`` / ``None``: no logo
* a path (``str`` / ``Path``) or the raw bytes of a PNG / JPEG / WebP image
"""

from __future__ import annotations

import base64
import functools
import io
import os
from importlib import resources
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageDraw, UnidentifiedImageError

from .exceptions import ValidationError

LogoLike = Union[bool, str, "os.PathLike[str]", bytes, None]

ENV_VAR = "BITSOPAY_LOGO"
LOGO_RATIO = 0.22  # longest side of the logo, relative to the side of the QR symbol (border excluded)
PAD_RATIO = 0.12  # white padding around the logo, relative to the logo's longest side
SVG_BADGE_PX = 256  # resolution of the logo image embedded in an SVG
ERROR_WITH_LOGO = "H"

_OFF = {"0", "false", "no", "off", "none"}
_MAX_LOGO_BYTES = 5 * 1024 * 1024


@functools.lru_cache(maxsize=1)
def _bundled() -> bytes:
    return resources.files("bitsopay").joinpath("assets/logo.png").read_bytes()


def _read_file(path: Union[str, os.PathLike[str]]) -> bytes:
    file = Path(path).expanduser()
    if not file.is_file():
        raise ValidationError(f"Logo file not found: {file}")
    if file.stat().st_size > _MAX_LOGO_BYTES:
        raise ValidationError("Logo file is too large (limit 5 MiB)")
    return file.read_bytes()


def resolve(logo: LogoLike) -> Optional[bytes]:
    """The image bytes to draw for ``logo``, or ``None`` when no logo is wanted."""
    if logo is None or logo is False:
        return None
    if logo is True:
        env = os.environ.get(ENV_VAR, "").strip()
        if not env:
            return _bundled()
        return None if env.lower() in _OFF else _read_file(env)
    if isinstance(logo, (bytes, bytearray)):
        if len(logo) > _MAX_LOGO_BYTES:
            raise ValidationError("Logo image is too large (limit 5 MiB)")
        return bytes(logo)
    if isinstance(logo, (str, os.PathLike)):
        return _read_file(logo)
    raise ValidationError("logo must be True, False, None, a file path or image bytes")


@functools.lru_cache(maxsize=16)
def _badge(raw: bytes, longest: int) -> Image.Image:
    """The logo (``longest`` px on its long side) on a white rounded badge. Never modify the result."""
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            logo = opened.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Could not read the logo image (use PNG, JPEG or WebP)") from None
    bbox = logo.getchannel("A").getbbox()
    if bbox is None:
        raise ValidationError("The logo image is empty")
    logo = logo.crop(bbox)
    logo.thumbnail((longest, longest), Image.Resampling.LANCZOS)
    pad = max(2, round(longest * PAD_RATIO))
    width, height = logo.size[0] + 2 * pad, logo.size[1] + 2 * pad
    ss = 4  # supersample the rounded corners
    mask = Image.new("L", (width * ss, height * ss), 0)
    radius = round(min(width, height) * 0.22) * ss
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width * ss - 1, height * ss - 1), radius=radius, fill=255)
    mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    badge = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    badge.paste(Image.new("RGBA", (width, height), (255, 255, 255, 255)), (0, 0), mask)
    badge.alpha_composite(logo, (pad, pad))
    return badge


def _longest(symbol_px: int) -> int:
    return max(8, round(symbol_px * LOGO_RATIO))


def overlay_png(png: bytes, raw: bytes, symbol_px: int) -> bytes:
    """Draw the logo in the middle of a QR PNG. ``symbol_px`` is the QR side without its border."""
    badge = _badge(raw, _longest(symbol_px))
    with Image.open(io.BytesIO(png)) as opened:
        base = opened.convert("RGB")
    x, y = (base.width - badge.width) // 2, (base.height - badge.height) // 2
    base.paste(badge, (x, y), badge)
    out = io.BytesIO()
    base.save(out, format="PNG", optimize=True)
    return out.getvalue()


def overlay_svg(svg: str, raw: bytes, width: int, height: int, symbol_px: int) -> str:
    """Add the logo to the middle of a QR SVG whose user units are pixels (``width`` x ``height``)."""
    badge = _badge(raw, SVG_BADGE_PX)
    unit = _longest(symbol_px) / SVG_BADGE_PX
    w, h = badge.width * unit, badge.height * unit
    buf = io.BytesIO()
    badge.save(buf, format="PNG", optimize=True)
    href = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    element = (
        f'<image x="{(width - w) / 2:.2f}" y="{(height - h) / 2:.2f}" width="{w:.2f}" height="{h:.2f}" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="{href}" href="{href}"/>'
    )
    head, sep, tail = svg.rpartition("</svg>")
    if not sep:  # pragma: no cover - segno always closes the root element
        raise ValidationError("Unexpected SVG output")
    return f"{head}{element}</svg>{tail}"
