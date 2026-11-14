"""Secure short payment links.

The link carries **only an unguessable reference code**::

    https://pay.example.com/p/BP684BF1555E4B4907

The UPI ID, amount and note stay on your server (in a :class:`~bitsopay.store.PaymentStore`),
so nothing can be read or edited from the URL. The same reference is sent to the UPI app as the
transaction reference (``tr``), so you can match it against your bank / UPI statement and keep a
history: pending -> paid / cancelled / expired.

>>> links = PaymentLinks(SQLiteStore("payments.db"), "https://pay.example.com")
>>> link = links.create("shop@okhdfcbank", "My Shop", 499, expires_in=3600)
>>> link.url
'https://pay.example.com/p/BP684BF1555E4B4907'
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Callable, List, Optional, Union, cast

from .exceptions import DuplicateReferenceError, InvalidStateError, NotFoundError, ValidationError
from .models import UPIPayment
from .qr import save_text_qr, text_qr_png, text_qr_svg
from .store import CANCELLED, PAID, STATUSES, PaymentRecord, PaymentStore
from .validators import Number, new_reference, validate_text

DEFAULT_EXPIRES_IN = 24 * 60 * 60
_MAX_PAID_NOTE = 200


@dataclass(frozen=True)
class PaymentLink:
    """A created payment request: the stored ``record`` and its shareable ``url``."""

    record: PaymentRecord
    url: str
    clock: Callable[[], float] = time.time

    @property
    def reference(self) -> str:
        return self.record.reference

    @property
    def expires_at(self) -> Optional[int]:
        return self.record.expires_at

    @property
    def seconds_left(self) -> Optional[int]:
        if self.record.expires_at is None:
            return None
        return max(0, int(self.record.expires_at - self.clock()))

    def png(self, *, scale: int = 10, border: int = 4, error: str = "M") -> bytes:
        """PNG of a QR that encodes the short ``url`` (stops working when the link expires)."""
        return text_qr_png(self.url, scale=scale, border=border, error=error)

    def svg(self, *, scale: int = 10, border: int = 4, error: str = "M") -> str:
        return text_qr_svg(self.url, scale=scale, border=border, error=error)

    def save(self, path: Union[str, Path], *, scale: int = 10, border: int = 4, error: str = "M") -> Path:
        return save_text_qr(self.url, path, scale=scale, border=border, error=error)


class PaymentLinks:
    """Create and manage short payment links backed by a :class:`PaymentStore`.

    ``base_url`` is the public root of the server running :mod:`bitsopay.server`,
    e.g. ``https://pay.example.com`` (no trailing path).
    """

    def __init__(
        self,
        store: PaymentStore,
        base_url: Optional[str] = None,
        *,
        prefix: str = "BP",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.base_url = base_url.rstrip("/") if base_url else None
        self.prefix = prefix
        self.clock = clock

    # -- helpers -----------------------------------------------------------
    def url_for(self, reference: str, base_url: Optional[str] = None) -> str:
        base = (base_url or self.base_url or "").rstrip("/")
        if not base.lower().startswith(("https://", "http://")):
            raise ValidationError("base_url must start with http:// or https://")
        return f"{base}/p/{reference}"

    def _require(self, reference: str) -> PaymentRecord:
        rec = self.store.get(reference)
        if rec is None:
            raise NotFoundError(reference)
        return rec

    # -- create ------------------------------------------------------------
    def create(
        self,
        upi_id: str,
        payee_name: str,
        amount: Optional[Number] = None,
        *,
        note: Optional[str] = None,
        merchant_code: Optional[str] = None,
        expires_in: Optional[int] = DEFAULT_EXPIRES_IN,
        base_url: Optional[str] = None,
    ) -> PaymentLink:
        """Validate, store and return a new link. ``expires_in=None`` never expires."""
        if expires_in is not None and expires_in <= 0:
            raise ValidationError("expires_in must be a positive number of seconds (or None)")
        payment = UPIPayment(
            upi_id=upi_id, payee_name=payee_name, amount=amount, note=note, merchant_code=merchant_code
        )
        now = int(self.clock())
        for _ in range(5):
            record = PaymentRecord(
                reference=new_reference(self.prefix),
                upi_id=payment.upi_id,
                payee_name=payment.payee_name,
                amount=cast(Optional[Decimal], payment.amount),  # validated + normalised by UPIPayment
                note=payment.note,
                merchant_code=payment.merchant_code,
                created_at=now,
                expires_at=None if expires_in is None else now + int(expires_in),
            )
            try:
                self.store.add(record)
            except DuplicateReferenceError:  # astronomically unlikely; just retry
                continue
            return PaymentLink(record, self.url_for(record.reference, base_url), self.clock)
        raise RuntimeError("Could not generate a unique reference")  # pragma: no cover

    # -- read --------------------------------------------------------------
    def get(self, reference: str) -> Optional[PaymentRecord]:
        return self.store.get(reference)

    def status_of(self, record: PaymentRecord) -> str:
        return record.effective_status(self.clock())

    def history(self, status: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[PaymentRecord]:
        if status is not None and status not in STATUSES:
            raise ValidationError(f"status must be one of {list(STATUSES)}")
        return self.store.list(status=status, limit=limit, offset=offset, now=self.clock())

    def record_view(self, reference: str) -> None:
        self.store.record_view(reference)

    # -- merchant actions (after you verify the payment manually) -----------
    def mark_paid(self, reference: str, note: Optional[str] = None) -> PaymentRecord:
        """Record that you verified the payment. Allowed even after the link expired."""
        rec = self._require(reference)
        if rec.status == PAID:
            return rec
        if rec.status == CANCELLED:
            raise InvalidStateError("A cancelled payment cannot be marked paid")
        text = validate_text(note, "note", _MAX_PAID_NOTE)
        return self.store.save(replace(rec, status=PAID, paid_at=int(self.clock()), paid_note=text))

    def cancel(self, reference: str) -> PaymentRecord:
        """Disable the link. Only pending payments can be cancelled."""
        rec = self._require(reference)
        if rec.status == CANCELLED:
            return rec
        if rec.status == PAID:
            raise InvalidStateError("A paid payment cannot be cancelled")
        return self.store.save(replace(rec, status=CANCELLED))
