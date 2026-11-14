"""Exception hierarchy for bitsopay."""

from __future__ import annotations


class BitsoPayError(Exception):
    """Base class for all bitsopay errors."""


class ValidationError(BitsoPayError, ValueError):
    """Raised when a UPI ID, amount or other field is invalid."""


class SignatureError(BitsoPayError):
    """Raised when a signed payment link has a missing or invalid signature."""


class LinkExpiredError(BitsoPayError):
    """Raised when a signed payment link is past its expiry time."""


class NotFoundError(BitsoPayError):
    """Raised when a payment reference does not exist."""


class InvalidStateError(BitsoPayError):
    """Raised for a status change that is not allowed (e.g. cancelling a paid payment)."""


class DuplicateReferenceError(BitsoPayError):
    """Raised by a store when a reference already exists."""
