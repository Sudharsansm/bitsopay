"""Field validation and normalisation helpers."""

from __future__ import annotations

import re
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional, Union

from .exceptions import ValidationError

# handle@psp  -  handle: 2-256 chars, psp: letters/digits (e.g. okhdfcbank, ybl)
_VPA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{1,255}@[A-Za-z][A-Za-z0-9]{1,63}$")
_REF_RE = re.compile(r"^[A-Za-z0-9._\-]{1,35}$")
_MCC_RE = re.compile(r"^\d{4}$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")

MAX_NAME_LEN = 99
MAX_NOTE_LEN = 80

Number = Union[int, float, str, Decimal]


def validate_vpa(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("UPI ID must be a string")
    vpa = value.strip()
    if not _VPA_RE.match(vpa):
        raise ValidationError(f"Invalid UPI ID: {value!r} (expected format 'name@bank')")
    return vpa


def validate_text(value: Optional[str], field: str, max_len: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    cleaned = _CTRL_RE.sub(" ", value).strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters")
    return cleaned


def validate_amount(value: Optional[Number], max_amount: Decimal) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValidationError("Amount must be a number")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError(f"Invalid amount: {value!r}") from None
    if not amount.is_finite():
        raise ValidationError("Amount must be a finite number")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ValidationError("Amount must be greater than zero")
    if amount > max_amount:
        raise ValidationError(f"Amount exceeds the maximum of {max_amount}")
    return amount


def validate_reference(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    ref = value.strip()
    if not _REF_RE.match(ref):
        raise ValidationError("Reference must be 1-35 chars of letters, digits, '.', '_' or '-'")
    return ref


def validate_mcc(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    code = str(value).strip()
    if not _MCC_RE.match(code):
        raise ValidationError("Merchant category code must be 4 digits")
    return code


def new_reference(prefix: str = "BP") -> str:
    """Generate a unique transaction reference (<= 35 chars)."""
    ref = f"{prefix}{uuid.uuid4().hex[:16].upper()}"
    return validate_reference(ref) or ref
