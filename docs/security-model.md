# Security model

## What Bitsopay protects

| Threat | Mitigation |
|---|---|
| Customer edits the amount in a URL | Short links hold only a reference; signed/stateless links carry an HMAC that covers every field |
| Guessing another customer's link | References have 64 random bits (stored) or a 64-bit MAC (database-free); non-canonical spellings are rejected |
| Reading amount/UPI ID from public routes | `/status` returns status and expiry only; database-free links encrypt the amount; the UPI ID is never in the URL |
| Admin token brute force | Constant-time comparison, minimum length 16, 10 failures/min/IP limiter per worker, with `Retry-After` |
| XSS / clickjacking / sniffing | All dynamic values HTML-escaped; CSP (`default-src 'none'`, inline-only page), `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, HSTS over HTTPS |
| SQL injection | Parameterised queries only; SQL text is built from constants |
| Information leaks on errors | Generic 500 with a request id; details only in server logs |
| Resource abuse | 16 KiB body cap; bounded history page size; bounded limiter memory |

## What it does not do

- **It cannot verify payment.** Anyone can claim to have paid. Confirm in your bank/UPI app, then call `mark_paid`.
- **A leaked `BITSOPAY_SECRET` or admin token** lets an attacker forge links or use the API. Rotate immediately.
- **Database-free amount confidentiality is best-effort.** The cipher nonce is 24 bits, so after a few thousand
  links two links may share a keystream and reveal the XOR of their amounts. Integrity is unaffected (a MAC covers
  everything). Use stored short links if amounts must stay private.
- **Status races.** Concurrent `mark_paid` and `cancel` on the same record are last-writer-wins at the store level.
- **The limiter is per process** and keyed by client IP; add proxy-level limits for strict guarantees.
- **TLS, firewalling, backups and OS hardening** are your responsibility.

## Operator checklist

- HTTPS everywhere; do not expose the app on plain HTTP.
- Long random secrets from a secret manager, not committed to git.
- `BITSOPAY_TRUST_PROXY=1` only behind your own proxy (otherwise clients can spoof their IP).
- Keep the database file private (`chmod 600`) and backed up.
- Reconcile `pending` links against your bank statement regularly; the `tr` reference is the order/link reference.
- Subscribe to GitHub releases/advisories for this project.
