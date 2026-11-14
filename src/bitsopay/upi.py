"""Build UPI deep links (NPCI ``upi://pay`` intent format)."""

from __future__ import annotations

from typing import Dict, List, Tuple
from urllib.parse import quote

from .models import UPIPayment

# App specific schemes that open a particular UPI app directly.
APP_SCHEMES: Dict[str, str] = {
    "gpay": "gpay://upi/pay",
    "phonepe": "phonepe://pay",
    "paytm": "paytmmp://pay",
}


def _params(p: UPIPayment) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = [("pa", p.upi_id), ("pn", p.payee_name)]
    if p.amount is not None:
        items.append(("am", f"{p.amount:.2f}"))
    items.append(("cu", p.currency))
    if p.note:
        items.append(("tn", p.note))
    if p.reference:
        items.append(("tr", p.reference))
    if p.merchant_code:
        items.append(("mc", p.merchant_code))
    return items


def _query(p: UPIPayment) -> str:
    return "&".join(f"{k}={quote(val, safe='@')}" for k, val in _params(p))


def build_upi_uri(payment: UPIPayment) -> str:
    """Return ``upi://pay?pa=...&pn=...&am=...`` for the payment."""
    return f"upi://pay?{_query(payment)}"


def build_app_uri(payment: UPIPayment, app: str) -> str:
    """Return a deep link targeting a specific app (``gpay``, ``phonepe``, ``paytm``)."""
    try:
        base = APP_SCHEMES[app]
    except KeyError:
        raise ValueError(f"Unknown app {app!r}; choose from {sorted(APP_SCHEMES)}") from None
    return f"{base}?{_query(payment)}"
