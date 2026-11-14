# Usage guide

## Payments and QR codes

```python
from bitsopay import UPIPayment, qr_png, qr_svg, qr_data_uri, save_qr, build_app_uri

pay = UPIPayment(upi_id="shop@okhdfcbank", payee_name="My Shop", amount="499.00",
                 note="Order 1042", reference="ORDER1042", merchant_code="5411")
pay.uri                         # the upi://pay deep link
qr_png(pay); qr_svg(pay)        # bytes / str
save_qr(pay, "pay.svg")         # extension picks the format
build_app_uri(pay, "gpay")      # app-specific deep link
```

Validation is strict and raises `bitsopay.ValidationError` (a `ValueError`) for: malformed UPI IDs, amounts that
are not positive with at most 2 decimals, notes over 80 characters, control characters and bad references.

## Short links with history

```python
from bitsopay import PaymentLinks, SQLiteStore

with SQLiteStore("payments.db") as store:
    links = PaymentLinks(store, "https://pay.example.com")
    link = links.create("shop@okhdfcbank", "My Shop", 499, note="Order 1042", expires_in=3600)
    links.get(link.reference)
    links.history(status="pending", limit=20, offset=0)
    links.mark_paid(link.reference, note="UTR 4123...")
    links.cancel(other_reference)
```

- Statuses: `pending`, `paid`, `cancelled`, `expired` (a pending link past its time).
- `mark_paid` and `cancel` are idempotent; cancelling a paid link (or paying a cancelled one) raises `InvalidStateError`.
- `SQLiteStore` uses WAL mode and a lock, so it is safe across threads. Use `MemoryStore` in tests, or subclass
  `PaymentStore` to back it with your own database.

## Database-free links

```python
from bitsopay import StatelessLinks
links = StatelessLinks("shop@okhdfcbank", "My Shop", secret=SECRET, base_url="https://pay.example.com")
link = links.create(499, expires_in=3600)       # amount=None lets the payer type it
payment, expires_at = links.decode(link.reference)
```

No history, no cancel, no mark-paid; see the comparison table in the [README](../README.md).

## Signed links and session QR codes

```python
from bitsopay import create_payment_link, verify_payment_link, create_session_qr

url = create_payment_link("https://pay.example.com/pay", pay, SECRET, expires_in=900)
payment, expires_at = verify_payment_link(url, SECRET)       # raises SignatureError / LinkExpiredError

session = create_session_qr("https://pay.example.com/pay", pay, SECRET, expires_in=300)
session.png(); session.seconds_left; session.expired
```

## Errors

All library errors derive from `bitsopay.BitsoPayError`: `ValidationError`, `SignatureError`, `LinkExpiredError`,
`NotFoundError`, `InvalidStateError`, `DuplicateReferenceError`.

## Embedding the server in your app

`bitsopay.server.create_app(...)` returns a plain WSGI callable, so it mounts in Flask, Django, or any WSGI
host (for example with `werkzeug.middleware.dispatcher.DispatcherMiddleware`). Close it with `app.close()` or use
`with create_app(...) as app:` if it opened the SQLite store from `BITSOPAY_DB`.
