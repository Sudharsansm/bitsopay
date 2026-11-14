<p align="center">
  <img src="https://raw.githubusercontent.com/Sudharsansm/Bitsopay/main/assets/bitsopay-logo.png" alt="Bitsopay" width="420">
</p>

<p align="center"><b>Dynamic UPI QR codes and tamper-proof payment links, with no payment gateway.</b></p>

<p align="center">
  <a href="https://pypi.org/project/bitsopay/"><img alt="PyPI" src="https://img.shields.io/pypi/v/bitsopay?label=PyPI&color=blue"></a>
  <a href="https://github.com/Sudharsansm/Bitsopay/blob/main/pyproject.toml"><img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg"></a>
  <a href="https://github.com/Sudharsansm/Bitsopay/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Sudharsansm/Bitsopay/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <a href="https://docs.astral.sh/ruff/"><img alt="Ruff" src="https://img.shields.io/badge/lint-ruff-261230.svg"></a>
  <img alt="Typed" src="https://img.shields.io/badge/typing-strict-2a6db2.svg">
</p>

<p align="center">
  <a href="README.md">README</a> ·
  <a href="CODE_OF_CONDUCT.md">Code of conduct</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="LICENSE">MIT license</a> ·
  <a href="SECURITY.md">Security</a>
</p>

---

## About

**Bitsopay** turns a UPI ID and an amount into a QR code or a shareable payment link. The customer scans
it with any UPI app (GPay, PhonePe, Paytm, BHIM, and others) and the amount is already filled in. Money goes
straight to *your* UPI ID.

It is a framework developed by **[Bitsophia](https://github.com/Sudharsansm)**, in the same family as
[Bitscrape](https://github.com/Sudharsansm/Bitscrape).

> **Bitsopay is not a payment gateway.** It never sees or moves money, and it cannot detect that a customer
> has paid. You confirm the payment in your bank or UPI app, then record it with `mark_paid`. In exchange there are
> no API keys, no gateway fees and no KYC with a third party.

## Features

- **QR from UPI ID + amount**: PNG, SVG or base64 data URI, with validated UPI IDs, `Decimal` amounts, notes and references.
- **Three kinds of payment link**:
  - *Short links with history*: the URL holds only a reference; UPI ID and amount stay on your server (SQLite or your own store).
  - *Database-free short links*: amount and expiry are encrypted and signed inside the URL.
  - *Signed links*: HMAC-SHA256 with expiry, for existing sites.
- **Payment page**: mobile-friendly, QR, UPI app buttons, live countdown, no external requests.
- **Production WSGI server**: merchant API, `/health` and `/ready` probes, security headers (CSP, HSTS), request IDs,
  structured logging, admin brute-force throttling.
- **CLI** for scripting and operations.
- **One dependency** ([`segno`](https://pypi.org/project/segno/), pure Python). Python 3.11+. Fully typed (`mypy --strict`).

## Install

```bash
pip install bitsopay            # library + CLI
pip install "bitsopay[server]"  # plus gunicorn for production serving
```

## Quick start

### 1. A QR code

```python
from bitsopay import UPIPayment, new_reference, save_qr, qr_data_uri

pay = UPIPayment(
    upi_id="shop@okhdfcbank",
    payee_name="My Shop",
    amount=499,                 # None lets the customer type the amount
    note="Order 1042",
    reference=new_reference(),  # use it to match the payment when you verify
)
pay.uri                         # upi://pay?pa=shop@okhdfcbank&pn=My%20Shop&am=499.00&cu=INR&...
save_qr(pay, "order-1042.png")  # or .svg
html_src = qr_data_uri(pay)     # <img src="...">
```

### 2. Short links with payment history

```python
from bitsopay import PaymentLinks, SQLiteStore

with SQLiteStore("payments.db") as store:
    links = PaymentLinks(store, "https://pay.example.com")
    link = links.create("shop@okhdfcbank", "My Shop", 499, note="Order 1042", expires_in=3600)
    print(link.url)             # https://pay.example.com/p/BP684BF1555E4B4907  -> send to the customer
    link.save("link-qr.png")

    # after YOU confirmed the money in your bank / UPI app:
    links.mark_paid(link.reference, note="UTR 4123...")
    links.history(status="pending", limit=20)   # paid | pending | cancelled | expired
```

### 3. Database-free links

```python
from bitsopay import StatelessLinks

links = StatelessLinks("shop@okhdfcbank", "My Shop", secret=SECRET, base_url="https://pay.example.com")
link = links.create(499, expires_in=3600)
link.url
```

More in [docs/usage.md](docs/usage.md) and [`examples/`](examples).

## Run the server

```bash
pip install "bitsopay[server]"
export BITSOPAY_DB=/var/lib/bitsopay/payments.db
export BITSOPAY_ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export BITSOPAY_BASE_URL=https://pay.example.com
gunicorn -c deploy/gunicorn.conf.py "bitsopay.server:create_app()"
```

Or with Docker: `docker compose up -d` (see [docs/deployment.md](docs/deployment.md)).

```bash
curl -X POST https://pay.example.com/api/payments \
  -H "Authorization: Bearer $BITSOPAY_ADMIN_TOKEN" \
  -d '{"upi_id":"shop@okhdfcbank","payee_name":"My Shop","amount":499,"expires_in":3600}'
```

| Route | Purpose |
|---|---|
| `GET /p/<ref>` | Customer payment page |
| `GET /p/<ref>/qr.png` · `qr.svg` | QR image |
| `GET /p/<ref>/status` | Status only (no amount or UPI ID) |
| `POST /api/payments` | Create a link *(admin)* |
| `GET /api/payments?status=&limit=&offset=` | History *(admin)* |
| `GET /api/payments/<ref>` | One record *(admin)* |
| `POST /api/payments/<ref>/paid` · `/cancel` | Change status *(admin)* |
| `GET /health` · `/ready` | Liveness and readiness probes |

Full reference: [docs/api.md](docs/api.md).

## Command line

```bash
bitsopay qr --upi-id shop@okhdfcbank --name "My Shop" --amount 499 -o pay.png
bitsopay create-link --db payments.db --base-url https://pay.example.com \
  --upi-id shop@okhdfcbank --name "My Shop" --amount 499 --expires-in 3600
bitsopay history --db payments.db --status pending
bitsopay mark-paid BP684BF1555E4B4907 --db payments.db --note "UTR 4123..."
```

Run `bitsopay --help` for all commands. [docs/cli.md](docs/cli.md) has the details.

## Configuration

| Variable | Purpose |
|---|---|
| `BITSOPAY_DB` | SQLite path; enables short links, history and the full merchant API |
| `BITSOPAY_SECRET` | 16+ char secret for signed and database-free links |
| `BITSOPAY_UPI_ID`, `BITSOPAY_PAYEE_NAME` | Merchant identity for database-free links |
| `BITSOPAY_ADMIN_TOKEN` | 16+ char bearer token for `/api/*` (API is off without it) |
| `BITSOPAY_BASE_URL` | Public root URL used in returned links |
| `BITSOPAY_TRUST_PROXY` | `1` to trust `X-Forwarded-For/Proto` (only behind your own proxy) |
| `BITSOPAY_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, ... |

## Security

Links cannot be edited or guessed, secrets are compared in constant time, the page makes no third-party
requests, and the admin API is throttled against brute force. Read the [threat model](docs/security-model.md)
before going live, and report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Documentation

| | |
|---|---|
| [Usage guide](docs/usage.md) | Library walkthrough |
| [API reference](docs/api.md) | HTTP routes, errors and status codes |
| [CLI](docs/cli.md) | Every command |
| [Architecture](docs/architecture.md) | How the pieces fit |
| [Deployment](docs/deployment.md) | gunicorn, nginx, Docker, systemd |
| [Security model](docs/security-model.md) | Threats and limits |
| [Releasing](docs/releasing.md) | Publishing to PyPI |
| [Changelog](CHANGELOG.md) | Version history |

## Development

```bash
git clone https://github.com/Sudharsansm/Bitsopay && cd Bitsopay
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
make check        # ruff, mypy --strict, pytest with coverage
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE) © 2026 Bitsophia