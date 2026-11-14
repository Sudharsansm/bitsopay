"""Payment record storage (history) for short links.

Two stores ship with the package:

* :class:`MemoryStore`  - for tests and prototypes (lost on restart)
* :class:`SQLiteStore`  - durable, standard library only, safe for one process with many
  threads and for several worker processes sharing one database file

Implement :class:`PaymentStore` to plug in Postgres, Redis, Django ORM, etc.
"""

from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .exceptions import DuplicateReferenceError, NotFoundError
from .models import UPIPayment

PENDING = "pending"
PAID = "paid"
CANCELLED = "cancelled"
EXPIRED = "expired"  # derived: a pending record past its expiry time
STATUSES = (PENDING, PAID, CANCELLED, EXPIRED)


@dataclass(frozen=True)
class PaymentRecord:
    """One payment request in the history. Times are unix seconds."""

    reference: str
    upi_id: str
    payee_name: str
    amount: Optional[Decimal]
    note: Optional[str]
    merchant_code: Optional[str]
    created_at: int
    expires_at: Optional[int]
    status: str = PENDING  # stored: pending | paid | cancelled
    paid_at: Optional[int] = None
    paid_note: Optional[str] = None
    views: int = 0

    def effective_status(self, now: float) -> str:
        """Stored status, but ``expired`` for a pending record past its expiry."""
        if self.status == PENDING and self.expires_at is not None and now > self.expires_at:
            return EXPIRED
        return self.status

    def to_payment(self) -> UPIPayment:
        return UPIPayment(
            upi_id=self.upi_id,
            payee_name=self.payee_name,
            amount=self.amount,
            note=self.note,
            reference=self.reference,
            merchant_code=self.merchant_code,
        )

    def to_dict(self, now: Optional[float] = None) -> Dict[str, object]:
        return {
            "reference": self.reference,
            "status": self.effective_status(now) if now is not None else self.status,
            "upi_id": self.upi_id,
            "payee_name": self.payee_name,
            "amount": None if self.amount is None else f"{self.amount:.2f}",
            "note": self.note,
            "merchant_code": self.merchant_code,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "paid_at": self.paid_at,
            "paid_note": self.paid_note,
            "views": self.views,
        }


def _matches(rec: PaymentRecord, status: Optional[str], now: float) -> bool:
    return status is None or rec.effective_status(now) == status


class PaymentStore(ABC):
    @abstractmethod
    def add(self, record: PaymentRecord) -> None:
        """Insert; raise :class:`DuplicateReferenceError` if the reference exists."""

    @abstractmethod
    def get(self, reference: str) -> Optional[PaymentRecord]: ...

    @abstractmethod
    def save(self, record: PaymentRecord) -> PaymentRecord:
        """Replace an existing record; raise :class:`NotFoundError` if missing."""

    @abstractmethod
    def record_view(self, reference: str) -> None:
        """Increment the page-view counter."""

    @abstractmethod
    def list(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0, now: float = 0
    ) -> List[PaymentRecord]:
        """Newest first. ``status`` may be any of :data:`STATUSES`."""


class MemoryStore(PaymentStore):
    def __init__(self) -> None:
        self._items: Dict[str, PaymentRecord] = {}
        self._lock = threading.RLock()

    def add(self, record: PaymentRecord) -> None:
        with self._lock:
            if record.reference in self._items:
                raise DuplicateReferenceError(record.reference)
            self._items[record.reference] = record

    def get(self, reference: str) -> Optional[PaymentRecord]:
        with self._lock:
            return self._items.get(reference)

    def save(self, record: PaymentRecord) -> PaymentRecord:
        with self._lock:
            if record.reference not in self._items:
                raise NotFoundError(record.reference)
            self._items[record.reference] = record
            return record

    def record_view(self, reference: str) -> None:
        with self._lock:
            rec = self._items.get(reference)
            if rec is not None:
                self._items[reference] = replace(rec, views=rec.views + 1)

    def list(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0, now: float = 0
    ) -> List[PaymentRecord]:
        with self._lock:
            # newest first; among equal timestamps the most recently inserted comes first
            ordered = sorted(reversed(list(self._items.values())), key=lambda r: -r.created_at)  # noqa: C414
        rows = [r for r in ordered if _matches(r, status, now)]
        return rows[offset : offset + limit]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    reference     TEXT PRIMARY KEY,
    upi_id        TEXT NOT NULL,
    payee_name    TEXT NOT NULL,
    amount        TEXT,
    note          TEXT,
    merchant_code TEXT,
    created_at    INTEGER NOT NULL,
    expires_at    INTEGER,
    status        TEXT NOT NULL,
    paid_at       INTEGER,
    paid_note     TEXT,
    views         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_payments_created ON payments (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status);
"""

_COLS = (
    "reference, upi_id, payee_name, amount, note, merchant_code, created_at, "
    "expires_at, status, paid_at, paid_note, views"
)
# Built once from the constant column list above; every runtime value goes through ``?`` placeholders.
_SELECT = f"SELECT {_COLS} FROM payments"  # noqa: S608
_INSERT = f"INSERT INTO payments ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"  # noqa: S608


def _row(r: sqlite3.Row) -> PaymentRecord:
    return PaymentRecord(
        reference=r["reference"],
        upi_id=r["upi_id"],
        payee_name=r["payee_name"],
        amount=None if r["amount"] is None else Decimal(r["amount"]),
        note=r["note"],
        merchant_code=r["merchant_code"],
        created_at=r["created_at"],
        expires_at=r["expires_at"],
        status=r["status"],
        paid_at=r["paid_at"],
        paid_note=r["paid_note"],
        views=r["views"],
    )


def _values(rec: PaymentRecord) -> Tuple[Any, ...]:
    return (
        rec.reference,
        rec.upi_id,
        rec.payee_name,
        None if rec.amount is None else f"{rec.amount:.2f}",
        rec.note,
        rec.merchant_code,
        rec.created_at,
        rec.expires_at,
        rec.status,
        rec.paid_at,
        rec.paid_note,
        rec.views,
    )


class SQLiteStore(PaymentStore):
    """Durable store in a single SQLite file (``":memory:"`` for tests)."""

    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            if str(path) != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def add(self, record: PaymentRecord) -> None:
        try:
            with self._lock, self._db:
                self._db.execute(_INSERT, _values(record))
        except sqlite3.IntegrityError:
            raise DuplicateReferenceError(record.reference) from None

    def get(self, reference: str) -> Optional[PaymentRecord]:
        with self._lock:
            r = self._db.execute(f"{_SELECT} WHERE reference=?", (reference,)).fetchone()
        return _row(r) if r else None

    def save(self, record: PaymentRecord) -> PaymentRecord:
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE payments SET upi_id=?, payee_name=?, amount=?, note=?, merchant_code=?, "
                "created_at=?, expires_at=?, status=?, paid_at=?, paid_note=?, views=? WHERE reference=?",
                (*_values(record)[1:], record.reference),
            )
            if cur.rowcount == 0:
                raise NotFoundError(record.reference)
        return record

    def record_view(self, reference: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE payments SET views = views + 1 WHERE reference=?", (reference,))

    def list(
        self, status: Optional[str] = None, limit: int = 50, offset: int = 0, now: float = 0
    ) -> List[PaymentRecord]:
        where = ""
        args: List[Any] = []
        if status == PENDING:
            where, args = "WHERE status='pending' AND (expires_at IS NULL OR expires_at >= ?)", [now]
        elif status == EXPIRED:
            where, args = "WHERE status='pending' AND expires_at IS NOT NULL AND expires_at < ?", [now]
        elif status in (PAID, CANCELLED):
            where, args = "WHERE status=?", [status]
        elif status is not None:
            return []
        with self._lock:
            rows = self._db.execute(
                f"{_SELECT} {where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                [*args, int(limit), int(offset)],
            ).fetchall()
        return [_row(r) for r in rows]
