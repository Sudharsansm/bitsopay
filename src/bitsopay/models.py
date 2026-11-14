"""The :class:`UPIPayment` value object."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from . import validators as v
from .exceptions import ValidationError

DEFAULT_MAX_AMOUNT = Decimal("10000000.00")  # sanity cap: 1 crore INR


@dataclass(frozen=True)
class UPIPayment:
    """A validated request to pay ``amount`` INR to ``upi_id``.

    ``amount=None`` produces an *open amount* request where the payer types the amount.
    """

    upi_id: str
    payee_name: str
    amount: Optional[v.Number] = None
    note: Optional[str] = None
    reference: Optional[str] = None
    merchant_code: Optional[str] = None
    currency: str = "INR"
    max_amount: Decimal = DEFAULT_MAX_AMOUNT

    def __post_init__(self) -> None:
        name = v.validate_text(self.payee_name, "payee_name", v.MAX_NAME_LEN)
        if not name:
            raise ValidationError("payee_name is required")
        if self.currency != "INR":
            raise ValidationError("Only INR is supported by UPI")
        max_amount = Decimal(str(self.max_amount))
        object.__setattr__(self, "max_amount", max_amount)
        object.__setattr__(self, "upi_id", v.validate_vpa(self.upi_id))
        object.__setattr__(self, "payee_name", name)
        object.__setattr__(self, "amount", v.validate_amount(self.amount, max_amount))
        object.__setattr__(self, "note", v.validate_text(self.note, "note", v.MAX_NOTE_LEN))
        object.__setattr__(self, "reference", v.validate_reference(self.reference))
        object.__setattr__(self, "merchant_code", v.validate_mcc(self.merchant_code))

    @property
    def uri(self) -> str:
        """The ``upi://pay`` deep link / QR payload."""
        from .upi import build_upi_uri

        return build_upi_uri(self)

    def with_reference(self, reference: Optional[str] = None) -> UPIPayment:
        """Return a copy with a (generated, if omitted) transaction reference."""
        from dataclasses import replace

        return replace(self, reference=reference or v.new_reference())
