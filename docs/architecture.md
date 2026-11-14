# Architecture

```
            ┌──────────────┐   upi://pay?...     ┌────────────┐
 customer ─▶│ payment page │────────────────────▶│  UPI app   │──▶ customer's bank ──▶ your bank
            └──────▲───────┘                     └────────────┘
                   │ GET /p/<ref>
            ┌──────┴───────────────────────────────────────┐
            │ bitsopay.server (WSGI)                       │
            │  routing · headers · limiter · logging       │
            ├──────────────┬───────────────┬───────────────┤
            │ PaymentLinks │ StatelessLinks│ signed links  │
            │ (shortlink)  │ (stateless)   │ (link)        │
            ├──────────────┴───────────────┴───────────────┤
            │ models · validators · upi · qr · page        │
            ├──────────────────────────────────────────────┤
            │ PaymentStore: SQLiteStore | MemoryStore | yours│
            └──────────────────────────────────────────────┘
 merchant ──▶ /api/* (bearer token) ──▶ create, history, mark paid, cancel
```

| Module | Responsibility |
|---|---|
| `validators`, `models`, `upi` | Validate input; build the `UPIPayment` and `upi://` URI |
| `qr`, `page` | QR rendering (segno) and the self-contained HTML payment page |
| `link`, `session` | HMAC-signed URLs and expiring session QR |
| `store`, `shortlink` | Persistence behind the `PaymentStore` interface; link lifecycle |
| `stateless` | Database-free encrypted + MACed references |
| `server`, `ratelimit` | WSGI app, security headers, admin throttling |
| `cli` | Command line front-end |

Design decisions:

- **No gateway.** Bitsopay builds standard UPI deep links; settlement happens between banks. Confirmation is manual.
- **Secrets stay server-side.** Public URLs carry a reference only (or an encrypted, signed blob).
- **One runtime dependency**, standard-library server, so it is easy to audit and deploy.
- **Pluggable storage** via `PaymentStore` (`add`, `get`, `save`, `list`, `record_view`).
