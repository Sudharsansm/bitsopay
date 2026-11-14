"""Database-free secure short links.

The link is ``https://pay.example.com/p/<id>`` where ``<id>`` is *self-contained*: it holds the
amount and expiry (encrypted) plus a random nonce and a signature, so the server needs no
database. The merchant UPI ID and name come from the server's configuration, never from the link.

``<id>`` = ``BP`` + 31 characters (33 total, within the 35-character UPI limit). It is also sent
to the UPI app as the transaction reference (``tr``), so it appears in your bank statement.

Layout of the 19 bytes behind the id (base32)::

    nonce (3) | amount in paise XOR keystream (4) + expiry XOR keystream (4) | MAC (8)

* amount and expiry are hidden with a keystream derived from HMAC-SHA256(secret, nonce)
* the MAC (HMAC-SHA256, 64 bits) covers prefix, nonce, ciphertext and the merchant UPI ID, so
  any edited character is rejected, and changing the configured UPI ID invalidates old links

Limits (no storage): no history, no cancel, no mark-paid, and the amount must fit 4 bytes of
paise (up to INR 42,949,672.95). Notes and order fields cannot fit in the id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional, Tuple, Union

from .exceptions import LinkExpiredError, SignatureError, ValidationError
from .models import UPIPayment
from .qr import save_text_qr, text_qr_png, text_qr_svg
from .validators import Number, validate_amount, validate_mcc, validate_text, validate_vpa

_NONCE, _DATA, _MAC = 3, 8, 8
_RAW_LEN = _NONCE + _DATA + _MAC  # 19 bytes
_BODY_LEN = 31  # base32 chars for 19 bytes, unpadded
_MAX_PAISE = 2**32 - 1
DEFAULT_EXPIRES_IN = 24 * 60 * 60


def _hm(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


@dataclass(frozen=True)
class StatelessLink:
    """A created database-free link."""

    reference: str
    url: str
    amount: Optional[Decimal]
    expires_at: Optional[int]
    clock: Callable[[], float] = time.time

    @property
    def seconds_left(self) -> Optional[int]:
        return None if self.expires_at is None else max(0, int(self.expires_at - self.clock()))

    def png(self, *, scale: int = 10, border: int = 4, error: str = "M") -> bytes:
        return text_qr_png(self.url, scale=scale, border=border, error=error)

    def svg(self, *, scale: int = 10, border: int = 4, error: str = "M") -> str:
        return text_qr_svg(self.url, scale=scale, border=border, error=error)

    def save(self, path: Union[str, Path], *, scale: int = 10, border: int = 4, error: str = "M") -> Path:
        return save_text_qr(self.url, path, scale=scale, border=border, error=error)


class StatelessLinks:
    """Create and decode short links with no database.

    >>> links = StatelessLinks("shop@okhdfcbank", "My Shop", secret, "https://pay.example.com")
    >>> link = links.create(499, expires_in=3600)
    >>> link.url
    'https://pay.example.com/p/BP...'
    """

    def __init__(
        self,
        upi_id: str,
        payee_name: str,
        secret: Union[str, bytes],
        base_url: Optional[str] = None,
        *,
        prefix: str = "BP",
        merchant_code: Optional[str] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.upi_id = validate_vpa(upi_id)
        name = validate_text(payee_name, "payee_name", 99)
        if not name:
            raise ValidationError("payee_name is required")
        self.payee_name = name
        self.merchant_code = validate_mcc(merchant_code)
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(key) < 16:
            raise ValidationError("Signing secret must be at least 16 bytes long")
        if not (1 <= len(prefix) <= 4 and prefix.isalnum() and prefix.isupper()):
            raise ValidationError("prefix must be 1-4 uppercase letters/digits")
        self.prefix = prefix
        self.base_url = base_url.rstrip("/") if base_url else None
        self.clock = clock
        self._enc = _hm(key, b"bitsopay/stateless/enc")
        self._mac = _hm(key, b"bitsopay/stateless/mac")

    # ------------------------------------------------------------------
    def url_for(self, reference: str, base_url: Optional[str] = None) -> str:
        base = (base_url or self.base_url or "").rstrip("/")
        if not base.lower().startswith(("https://", "http://")):
            raise ValidationError("base_url must start with http:// or https://")
        return f"{base}/p/{reference}"

    def _tag(self, nonce: bytes, ct: bytes) -> bytes:
        msg = self.prefix.encode() + b"\x00" + nonce + ct + b"\x00" + self.upi_id.encode()
        return _hm(self._mac, msg)[:_MAC]

    def _stream(self, nonce: bytes) -> bytes:
        return _hm(self._enc, b"ks" + nonce)[:_DATA]

    # ------------------------------------------------------------------
    def create(
        self,
        amount: Optional[Number] = None,
        *,
        expires_in: Optional[int] = DEFAULT_EXPIRES_IN,
        base_url: Optional[str] = None,
    ) -> StatelessLink:
        """Return a link for ``amount`` INR (None = payer enters it). ``expires_in=None`` never expires."""
        if expires_in is not None and expires_in <= 0:
            raise ValidationError("expires_in must be a positive number of seconds (or None)")
        value = validate_amount(amount, Decimal(_MAX_PAISE) / 100)
        paise = 0 if value is None else int(value * 100)
        exp = 0 if expires_in is None else int(self.clock()) + int(expires_in)
        if exp > _MAX_PAISE:
            raise ValidationError("expires_in is too large")
        nonce = secrets.token_bytes(_NONCE)
        plain = struct.pack(">II", paise, exp)
        ct = bytes(a ^ b for a, b in zip(plain, self._stream(nonce), strict=True))
        raw = nonce + ct + self._tag(nonce, ct)
        body = base64.b32encode(raw).decode("ascii").rstrip("=")
        ref = self.prefix + body
        return StatelessLink(ref, self.url_for(ref, base_url), value, exp or None, self.clock)

    def decode(self, reference: str) -> Tuple[UPIPayment, Optional[int]]:
        """Verify ``reference`` and return ``(payment, expires_at)``.

        Raises :class:`SignatureError` (malformed / tampered / wrong secret) or
        :class:`LinkExpiredError` (valid but past its time).
        """
        ref = reference.strip().upper()
        if not ref.startswith(self.prefix) or len(ref) != len(self.prefix) + _BODY_LEN:
            raise SignatureError("Invalid reference")
        body = ref[len(self.prefix) :]
        try:
            raw = base64.b32decode(body + "=" * (-len(body) % 8))
        except Exception:
            raise SignatureError("Invalid reference") from None
        # reject non-canonical spellings (the last base32 char has 3 unused bits), so every
        # link has exactly one valid reference string
        if len(raw) != _RAW_LEN or base64.b32encode(raw).decode("ascii").rstrip("=") != body:
            raise SignatureError("Invalid reference")
        nonce, ct, tag = raw[:_NONCE], raw[_NONCE : _NONCE + _DATA], raw[_NONCE + _DATA :]
        if not hmac.compare_digest(tag, self._tag(nonce, ct)):
            raise SignatureError("Invalid reference")
        paise, exp = struct.unpack(">II", bytes(a ^ b for a, b in zip(ct, self._stream(nonce), strict=True)))
        if exp and self.clock() > exp:
            raise LinkExpiredError("This payment link has expired")
        payment = UPIPayment(
            upi_id=self.upi_id,
            payee_name=self.payee_name,
            amount=None if paise == 0 else Decimal(paise).scaleb(-2),
            reference=ref,
            merchant_code=self.merchant_code,
        )
        return payment, (exp or None)