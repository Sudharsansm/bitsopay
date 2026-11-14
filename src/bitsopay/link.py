"""Signed, tamper-proof web payment links.

A *payment link* is a normal HTTPS URL the merchant shares (WhatsApp, SMS, email).
It carries the UPI ID, amount, etc. plus an HMAC-SHA256 signature and an expiry, so
a customer cannot edit the amount in the URL. Open on a phone, the page offers a
"Pay with UPI app" button; on desktop it shows a QR code to scan.

Serve the links with :mod:`bitsopay.server` (a ready WSGI app) or render the page
yourself with :func:`bitsopay.page.render_payment_page`.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Dict, List, Mapping, Optional, Tuple, Union
from urllib.parse import parse_qs, urlencode, urlparse

from .exceptions import LinkExpiredError, SignatureError, ValidationError
from .models import UPIPayment

_SIGNED_KEYS = ("pa", "pn", "am", "tn", "tr", "mc", "cu", "exp")
DEFAULT_EXPIRY_SECONDS = 24 * 60 * 60


def _secret_bytes(secret: Union[str, bytes]) -> bytes:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(key) < 16:
        raise ValidationError("Signing secret must be at least 16 bytes long")
    return key


def _fields(payment: UPIPayment, exp: Optional[int]) -> Dict[str, str]:
    data: Dict[str, str] = {"pa": payment.upi_id, "pn": payment.payee_name, "cu": payment.currency}
    if payment.amount is not None:
        data["am"] = f"{payment.amount:.2f}"
    if payment.note:
        data["tn"] = payment.note
    if payment.reference:
        data["tr"] = payment.reference
    if payment.merchant_code:
        data["mc"] = payment.merchant_code
    if exp is not None:
        data["exp"] = str(exp)
    return data


def _sign(fields: Mapping[str, str], secret: Union[str, bytes]) -> str:
    message = "\n".join(f"{k}={fields[k]}" for k in _SIGNED_KEYS if k in fields)
    return hmac.new(_secret_bytes(secret), message.encode("utf-8"), hashlib.sha256).hexdigest()


def create_payment_link(
    base_url: str,
    payment: UPIPayment,
    secret: Union[str, bytes],
    *,
    expires_in: Optional[int] = DEFAULT_EXPIRY_SECONDS,
    now: Optional[float] = None,
) -> str:
    """Return ``base_url?...&sig=...`` for ``payment``.

    ``base_url`` is the full URL of your payment page, e.g. ``https://pay.example.com/pay``.
    Pass ``expires_in=None`` for a link that never expires.
    """
    if not base_url.lower().startswith(("https://", "http://")):
        raise ValidationError("base_url must start with http:// or https://")
    exp = None if expires_in is None else int((now if now is not None else time.time()) + expires_in)
    fields = _fields(payment, exp)
    fields["sig"] = _sign(fields, secret)
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{urlencode(fields)}"


def verify_payment_link(
    link_or_query: str,
    secret: Union[str, bytes],
    *,
    now: Optional[float] = None,
) -> Tuple[UPIPayment, Optional[int]]:
    """Verify signature and expiry; return ``(payment, expires_at_unix_or_None)``.

    Accepts a full URL or just the query string. Raises :class:`SignatureError`
    or :class:`LinkExpiredError`.
    """
    query = urlparse(link_or_query).query if "?" in link_or_query or "://" in link_or_query else link_or_query
    raw: Dict[str, List[str]] = parse_qs(query, keep_blank_values=False)
    fields = {k: vals[0] for k, vals in raw.items() if k in _SIGNED_KEYS and vals}
    sig = (raw.get("sig") or [""])[0]
    if not sig or "pa" not in fields:
        raise SignatureError("Missing signature")
    if not hmac.compare_digest(sig, _sign(fields, secret)):
        raise SignatureError("Invalid signature")
    exp: Optional[int] = None
    if "exp" in fields:
        try:
            exp = int(fields["exp"])
        except ValueError:
            raise SignatureError("Invalid expiry") from None
        if (now if now is not None else time.time()) > exp:
            raise LinkExpiredError("This payment link has expired")
    payment = UPIPayment(
        upi_id=fields["pa"],
        payee_name=fields.get("pn", ""),
        amount=fields.get("am"),
        note=fields.get("tn"),
        reference=fields.get("tr"),
        merchant_code=fields.get("mc"),
        currency=fields.get("cu", "INR"),
    )
    return payment, exp


def parse_payment_link(
    link_or_query: str,
    secret: Union[str, bytes],
    *,
    now: Optional[float] = None,
) -> UPIPayment:
    """Like :func:`verify_payment_link` but returns only the :class:`UPIPayment`."""
    return verify_payment_link(link_or_query, secret, now=now)[0]
