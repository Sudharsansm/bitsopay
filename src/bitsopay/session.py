"""Expiring ("session") QR codes.

A normal UPI QR (``upi://pay?...``) works forever: the payment details live inside the
image. A **session QR** instead encodes a signed HTTPS link to *your* server. When the
session time ends the server refuses the link (HTTP 410), so a saved or screenshotted
QR stops working.

Trade-offs:

* Scan it with a phone camera or Google Lens / the scanner inside a UPI app that opens
  links; it lands on the payment page, which then opens the UPI app.
* It needs your server online (``bitsopay.server``) and is useless offline.
* Once a customer has *already* tapped "Pay" and is inside their UPI app, the session
  cannot be cancelled; verify payments manually as usual.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .link import create_payment_link
from .models import UPIPayment
from .qr import save_text_qr, text_qr_png, text_qr_svg


@dataclass(frozen=True)
class SessionQR:
    """An expiring QR: the signed ``url`` it encodes and its expiry (unix seconds)."""

    url: str
    expires_at: int

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    def png(self, *, scale: int = 10, border: int = 4, error: str = "M") -> bytes:
        return text_qr_png(self.url, scale=scale, border=border, error=error)

    def svg(self, *, scale: int = 10, border: int = 4, error: str = "M") -> str:
        return text_qr_svg(self.url, scale=scale, border=border, error=error)

    def save(self, path: Union[str, Path], *, scale: int = 10, border: int = 4, error: str = "M") -> Path:
        return save_text_qr(self.url, path, scale=scale, border=border, error=error)


def create_session_qr(
    base_url: str,
    payment: UPIPayment,
    secret: Union[str, bytes],
    *,
    expires_in: int = 300,
    now: Optional[float] = None,
) -> SessionQR:
    """Create a QR that stops working ``expires_in`` seconds from now (default 5 min)."""
    if expires_in <= 0:
        raise ValueError("expires_in must be a positive number of seconds")
    start = now if now is not None else time.time()
    url = create_payment_link(base_url, payment, secret, expires_in=expires_in, now=start)
    return SessionQR(url=url, expires_at=int(start + expires_in))
