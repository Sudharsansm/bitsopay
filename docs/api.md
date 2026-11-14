# HTTP API reference

Base URL: your `BITSOPAY_BASE_URL`. All responses carry `X-Request-ID` (send your own `X-Request-ID` to propagate a
trace id) and the security headers listed in [security-model.md](security-model.md).

## Public routes

| Method | Path | Response |
|---|---|---|
| GET/HEAD | `/p/<ref>` | HTML payment page; `410` if expired or cancelled; "Payment received" page if paid; `404` if unknown |
| GET/HEAD | `/p/<ref>/qr.png`, `/p/<ref>/qr.svg` | QR image; `410` when not payable |
| GET/HEAD | `/p/<ref>/status` | `{"reference","status","expires_at"}` |
| GET | `/health` | `200 ok` while the process is up |
| GET | `/ready` | `200 ready`, or `503` if the store is unreachable |

## Merchant API

Requires `Authorization: Bearer <BITSOPAY_ADMIN_TOKEN>`. If no token is configured the API answers `404`.
After 10 failed attempts within a minute a client IP gets `429` with `Retry-After`. The counter is per worker process, so with N gunicorn workers the effective limit is up to 10×N; add proxy-level rate limiting too.

### `POST /api/payments`

```json
{"upi_id": "shop@okhdfcbank", "payee_name": "My Shop", "amount": 499,
 "note": "Order 1042", "merchant_code": "5411", "expires_in": 3600}
```

`amount` may be omitted/`null` for an open amount. `expires_in` is whole seconds (default 86400); `null` means never.
In database-free mode only `amount` and `expires_in` are used. Returns `201` with the record and its `url`.

### `GET /api/payments?status=&limit=&offset=`

`status` is `pending|paid|cancelled|expired`. `limit` is 1 to 500 (default 50), `offset` is 0 or more.

### `GET /api/payments/<ref>`, `POST /api/payments/<ref>/paid`, `POST /api/payments/<ref>/cancel`

`paid` accepts an optional `{"note": "UTR ..."}`.

## Errors

JSON `{"error": "message"}` with:

| Status | Meaning |
|---|---|
| 400 | Invalid input (bad JSON, field, `limit`, `expires_in`, ...) |
| 401 | Missing or wrong token |
| 404 | Unknown route or payment, or API disabled |
| 409 | Invalid state change (for example cancelling a paid payment) |
| 413 | Body over 16 KiB |
| 429 | Too many failed authentication attempts |
| 500 | Unexpected error; body contains a `request_id` to find it in the logs |
| 501 | Operation needs a store (`BITSOPAY_DB`) |
