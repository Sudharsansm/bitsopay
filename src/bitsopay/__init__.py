"""Bitsopay: dynamic UPI QR codes and signed payment links.

>>> from bitsopay import UPIPayment, qr_png, create_payment_link
>>> pay = UPIPayment(upi_id="shop@okhdfcbank", payee_name="My Shop", amount=499)
>>> pay.uri
'upi://pay?pa=shop@okhdfcbank&pn=My%20Shop&am=499.00&cu=INR'
"""

from __future__ import annotations

__version__ = "0.1.1"

from .exceptions import (
    BitsoPayError,
    DuplicateReferenceError,
    InvalidStateError,
    LinkExpiredError,
    NotFoundError,
    SignatureError,
    ValidationError,
)
from .link import create_payment_link, parse_payment_link, verify_payment_link
from .models import UPIPayment
from .page import render_payment_page
from .qr import qr_data_uri, qr_png, qr_svg, save_qr
from .session import SessionQR, create_session_qr
from .shortlink import PaymentLink, PaymentLinks
from .stateless import StatelessLink, StatelessLinks
from .store import MemoryStore, PaymentRecord, PaymentStore, SQLiteStore
from .upi import build_app_uri, build_upi_uri
from .validators import new_reference

__all__ = [
    "BitsoPayError",
    "DuplicateReferenceError",
    "InvalidStateError",
    "LinkExpiredError",
    "MemoryStore",
    "NotFoundError",
    "PaymentLink",
    "PaymentLinks",
    "PaymentRecord",
    "PaymentStore",
    "SQLiteStore",
    "SessionQR",
    "SignatureError",
    "StatelessLink",
    "StatelessLinks",
    "UPIPayment",
    "ValidationError",
    "__version__",
    "build_app_uri",
    "build_upi_uri",
    "create_payment_link",
    "create_session_qr",
    "new_reference",
    "parse_payment_link",
    "qr_data_uri",
    "qr_png",
    "qr_svg",
    "render_payment_page",
    "save_qr",
    "verify_payment_link",
]
