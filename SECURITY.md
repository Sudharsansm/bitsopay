# Security Policy

Bitsopay handles payment details, so security reports are taken seriously.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting:
[**Report a vulnerability**](https://github.com/Sudharsansm/Bitsopay/security/advisories/new)
(repository → *Security* → *Report a vulnerability*).

Include what you found, the affected version, steps to reproduce (a minimal script is ideal), and the impact you
see. You will get an acknowledgement within **3 business days** and a first assessment within **7 days**. We
coordinate a fix and release with you, and credit you in the advisory unless you prefer otherwise.

Please give us a reasonable time to ship a fix before any public disclosure (we aim for 90 days at most).

## In scope

- Forging, altering or extending signed or encrypted links; signature or MAC bypass
- Reading another payment's data, or amount/UPI ID leakage through public routes
- Admin API authentication or throttling bypass
- Injection (SQL, header, HTML/script) and path handling problems
- Unsafe defaults that put merchants' money or data at risk

## Out of scope

- Bitsopay does not process payments or detect payment completion; "a customer claims to have paid" is expected
  behavior. Merchants must verify in their bank or UPI app.
- Findings that need a compromised server, a leaked `BITSOPAY_SECRET` or admin token, or a misconfigured proxy
- Missing rate limiting at your reverse proxy, TLS configuration, or denial of service by raw traffic volume
- Vulnerabilities in third-party dependencies with no demonstrated impact on Bitsopay (report those upstream)

## Hardening checklist for operators

See [docs/security-model.md](docs/security-model.md): serve over HTTPS, use long random secrets, keep the
database file private, set `BITSOPAY_TRUST_PROXY` only behind a proxy you control, and rotate secrets if exposed.
