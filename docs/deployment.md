# Deployment

## Checklist

1. Generate secrets: `python -c "import secrets; print(secrets.token_urlsafe(32))"` for `BITSOPAY_ADMIN_TOKEN` (and `BITSOPAY_SECRET` if used).
2. Put the app behind **HTTPS** (nginx, Caddy, or a cloud load balancer). UPI apps and browsers expect it.
3. Store the SQLite file on persistent disk, readable only by the service user. Back it up (`sqlite3 payments.db ".backup out.db"`).
4. Set `BITSOPAY_BASE_URL` to the public URL; set `BITSOPAY_TRUST_PROXY=1` **only** if a proxy you control sets `X-Forwarded-*`.
5. Rate-limit `/api/` at the proxy as well (the built-in limiter is per process).
6. Point monitoring at `/health` (liveness) and `/ready` (readiness).

## gunicorn

```bash
pip install "bitsopay[server]"
gunicorn -c deploy/gunicorn.conf.py "bitsopay.server:create_app()"
```

SQLite with WAL handles several worker processes on one host. For multiple hosts, implement a `PaymentStore` on a
networked database.

## Docker

```bash
cp deploy/.env.example .env      # edit the values
docker compose up -d --build
curl http://localhost:8080/health
```

The image runs as a non-root user, keeps data in the `bitsopay-data` volume, and has a health check.

## systemd and nginx

Ready-to-edit files: `deploy/bitsopay.service` and `deploy/nginx.conf`.

## Upgrading

The SQLite schema is created automatically. Read the [changelog](../CHANGELOG.md) before upgrading; back up the
database first. Changing `BITSOPAY_SECRET` or `BITSOPAY_UPI_ID` invalidates previously issued database-free and signed links.
