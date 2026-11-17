# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-11-17

### Added
- `bitsopay_demo.py`: the generated UPI QR now carries a circular Bitsopay logo badge in its center.
- `bitsopay_demo.py`: a short, secure share link for each payment, backed by `PaymentLinks` + `SQLiteStore`.
  The link exposes only an unguessable reference (never the UPI ID, amount, or merchant name), and opens a
  minimal preview page with its own "Open UPI Payment App" action.
- `bitsopay_demo.py`: a live countdown on both the on-screen QR session and the share-link page, with the
  QR greyed out and the "Open UPI Payment App" action disabled once a session expires.
- `bitsopay_demo.py`: a "Session Expires" selector (2 / 5 / 10 / 15 / 30 minutes) on the form, sent to the
  server as `session_expires_in` and applied to both the QR session and the share link; the server clamps
  it to a 1-minute floor and 1-hour ceiling.

## [0.1.0] - 2026-11-14

First release, by Bitsophia.

### Added
- `/ready` readiness probe; `X-Request-ID` propagation; structured request logging (`bitsopay.server` logger).
- Security headers on every response: `Content-Security-Policy`, HSTS (over HTTPS), `Permissions-Policy`,
  `Cross-Origin-*`.
- Admin brute-force throttling (`bitsopay.ratelimit.FailureLimiter`, `429` + `Retry-After`).
- `BITSOPAY_TRUST_PROXY` and `BITSOPAY_LOG_LEVEL` settings; `HEAD` support.
- `python -m bitsopay`, `bitsopay --version`; `SQLiteStore` and the server app are context managers (`close()`).
- Full documentation set, Dockerfile, CI, CodeQL and PyPI Trusted Publishing workflows.

### Changed
- `server.py` rewritten with strict typing; unhandled errors now return a generic 500 with a request id.
- A short `BITSOPAY_SECRET` now fails at startup instead of at the first request.
- Package metadata, `py.typed`, `ruff` and `mypy --strict` configuration.

### Fixed
- `limit=-1` on the history endpoint returned every row (SQLite treats a negative `LIMIT` as unlimited); paging
  parameters are now validated (400).
- Non-integer `expires_in` in the API caused a 500; it is now a 400.
- SQLite connections opened by the CLI were never closed.

[Unreleased]: https://github.com/Sudharsansm/Bitsopay/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Sudharsansm/Bitsopay/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Sudharsansm/Bitsopay/releases/tag/v0.1.0