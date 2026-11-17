"""Static QR codes — one reusable QR per UPI ID.

In standard UPI/payment terminology, a **Static QR Code** is tied to *your* UPI ID.
Call :meth:`StaticSession.create` and you get back a signed HTTPS link (and, from it,
a QR image). Call it again while that QR is still valid and you get back the *exact
same* QR — so it can be printed, put on a counter or a till screen, and reused for
many payments; the payer types the amount.

It still carries a short validity window (5 minutes by default) inside its
signature, as a security measure. Once that window lapses, the next call to
:meth:`create` transparently mints a fresh QR for you. The UPI ID is itself part of
what gets signed, so if the UPI ID changes (you switch banks, rotate accounts, etc.)
you immediately get a brand-new QR - the old one cannot be reused for the new UPI ID.

(Contrast with a **Dynamic QR Code** — a fresh, fixed-amount QR generated per
transaction: see :mod:`bitsopay.session`.)

>>> session = StaticSession("shop@okhdfcbank", "My Shop", secret, "https://pay.example.com/pay")
>>> first = session.create()
>>> again = session.create()
>>> first.url == again.url          # same QR, reused, while it's still valid
True

Serve the link with :mod:`bitsopay.server` (it is an ordinary signed payment link,
verified the same way as :func:`bitsopay.link.create_payment_link`) or with your own
code via :func:`bitsopay.link.verify_payment_link`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from .link import create_payment_link
from .logo import LogoLike
from .models import UPIPayment
from .qr import save_text_qr, text_qr_png, text_qr_svg
from .validators import new_reference, validate_mcc, validate_text, validate_vpa

#: Default validity window of a static QR, in seconds (5 minutes).
DEFAULT_WINDOW = 300


@dataclass(frozen=True)
class StaticQR:
    """One issue of a static merchant QR: its ``upi_id``, signed ``url`` and expiry."""

    upi_id: str
    reference: str
    url: str
    base_url: str
    issued_at: int
    expires_at: int

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    def png(self, *, scale: int = 10, border: int = 4, error: str = "M", logo: LogoLike = True) -> bytes:
        return text_qr_png(self.url, scale=scale, border=border, error=error, logo=logo)

    def svg(self, *, scale: int = 10, border: int = 4, error: str = "M", logo: LogoLike = True) -> str:
        return text_qr_svg(self.url, scale=scale, border=border, error=error, logo=logo)

    def save(
        self, path: Union[str, Path], *, scale: int = 10, border: int = 4, error: str = "M", logo: LogoLike = True
    ) -> Path:
        return save_text_qr(self.url, path, scale=scale, border=border, error=error, logo=logo)


class StaticSession:
    """Issues (and reuses) one static QR at a time for a merchant.

    ``base_url`` is the full URL of your payment page, e.g. ``https://pay.example.com/pay``.
    The QR has an open amount (the payer enters it); give a fixed amount per payment with
    :mod:`bitsopay.session` instead.
    """

    def __init__(
        self,
        upi_id: str,
        payee_name: str,
        secret: Union[str, bytes],
        base_url: Optional[str] = None,
        *,
        merchant_code: Optional[str] = None,
        window: int = DEFAULT_WINDOW,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.upi_id = validate_vpa(upi_id)
        name = validate_text(payee_name, "payee_name", 99)
        if not name:
            from .exceptions import ValidationError

            raise ValidationError("payee_name is required")
        self.payee_name = name
        self.merchant_code = validate_mcc(merchant_code)
        self.secret = secret
        self.base_url = self._checked_base_url(base_url) if base_url is not None else None
        if window <= 0:
            from .exceptions import ValidationError

            raise ValidationError("window must be a positive number of seconds")
        self.window = window
        self.clock = clock
        self._current: Optional[StaticQR] = None

    @staticmethod
    def _checked_base_url(base_url: str) -> str:
        if not base_url.lower().startswith(("https://", "http://")):
            from .exceptions import ValidationError

            raise ValidationError("base_url must start with http:// or https://")
        return base_url

    def create(
        self, upi_id: Optional[str] = None, *, base_url: Optional[str] = None, now: Optional[float] = None
    ) -> StaticQR:
        """Return the merchant's current static QR, minting a new one only if needed.

        The existing QR is reused as-is when all of these hold: it hasn't expired yet,
        ``upi_id`` (if given) matches the UPI ID it was issued for, and ``base_url``
        (if given) matches too. Otherwise — first call, the window lapsed, the UPI ID
        changed, or the base URL changed — a fresh QR is created and becomes the one
        later calls reuse. One of the constructor's ``base_url`` or this ``base_url``
        is required.
        """
        moment = now if now is not None else self.clock()
        target_upi = validate_vpa(upi_id) if upi_id is not None else self.upi_id
        target_base = self._checked_base_url(base_url) if base_url is not None else self.base_url
        if target_base is None:
            from .exceptions import ValidationError

            raise ValidationError("base_url is required (pass it to the constructor or to create())")
        current = self._current
        if (
            current is not None
            and current.upi_id == target_upi
            and current.base_url == target_base
            and moment < current.expires_at
        ):
            return current
        self.upi_id = target_upi
        payment = UPIPayment(
            upi_id=target_upi,
            payee_name=self.payee_name,
            amount=None,
            reference=new_reference(),
            merchant_code=self.merchant_code,
        )
        url = create_payment_link(target_base, payment, self.secret, expires_in=self.window, now=moment)
        issued = StaticQR(
            upi_id=target_upi,
            reference=payment.reference,  # type: ignore[arg-type]
            url=url,
            base_url=target_base,
            issued_at=int(moment),
            expires_at=int(moment + self.window),
        )
        self._current = issued
        return issued
