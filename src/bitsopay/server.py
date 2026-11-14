"""A dependency-free WSGI app for Bitsopay payment links.

Production::

    export BITSOPAY_DB=/var/lib/bitsopay/payments.db
    export BITSOPAY_ADMIN_TOKEN="a-long-random-token"        # merchant API (>= 16 chars)
    export BITSOPAY_BASE_URL=https://pay.example.com         # public root URL
    gunicorn "bitsopay.server:create_app()"

Public routes (short links; need a store)
-----------------------------------------
``GET /p/<ref>``            payment page (QR + UPI app buttons + countdown)
``GET /p/<ref>/qr.png``     UPI QR code, ``/qr.svg`` for SVG
``GET /p/<ref>/status``     ``{"reference", "status", "expires_at"}`` (no amount / UPI ID)

Merchant API (``Authorization: Bearer <BITSOPAY_ADMIN_TOKEN>``)
---------------------------------------------------------------
``POST /api/payments``                 create ``{"upi_id","payee_name","amount","note","expires_in"}``
``GET  /api/payments?status=&limit=``  history
``GET  /api/payments/<ref>``           one record
``POST /api/payments/<ref>/paid``      mark paid after you verified it ``{"note": "..."}``
``POST /api/payments/<ref>/cancel``    disable the link

Database-free mode: set ``BITSOPAY_SECRET``, ``BITSOPAY_UPI_ID`` and ``BITSOPAY_PAYEE_NAME`` (no
``BITSOPAY_DB``); ``/p/<id>`` links then carry their own encrypted amount + expiry, and
``POST /api/payments`` creates them.

Legacy signed links (``BITSOPAY_SECRET``): ``/pay``, ``/qr.png``, ``/qr.svg``.

Probes: ``/health`` (process is up) and ``/ready`` (the store answers).

Other environment variables: ``BITSOPAY_TRUST_PROXY=1`` (read the client IP and scheme from
``X-Forwarded-*``; only behind a proxy you control) and ``BITSOPAY_LOG_LEVEL``.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple, Union
from urllib.parse import parse_qs

from .exceptions import (
    InvalidStateError,
    LinkExpiredError,
    NotFoundError,
    SignatureError,
    ValidationError,
)
from .link import verify_payment_link
from .page import render_message_page, render_payment_page
from .qr import qr_png, qr_svg
from .ratelimit import FailureLimiter
from .shortlink import PaymentLinks
from .stateless import StatelessLinks
from .store import EXPIRED, PAID, PENDING, PaymentStore, SQLiteStore

log = logging.getLogger("bitsopay.server")

Headers = List[Tuple[str, str]]
Environ = Dict[str, Any]
StartResponse = Callable[..., Any]
WSGIApp = Callable[[Environ, StartResponse], Iterable[bytes]]


class BitsoPayApp:
    """The WSGI callable returned by :func:`create_app`.

    Use it like any WSGI app. Call :meth:`close` (or use ``with``) to release the SQLite
    connection that :func:`create_app` opened from ``$BITSOPAY_DB``; a store you passed in
    yourself is never closed for you.
    """

    def __init__(self, handler: WSGIApp, owned_store: Optional[SQLiteStore] = None) -> None:
        self._handler = handler
        self._owned_store = owned_store

    def __call__(self, environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        return self._handler(environ, start_response)

    def close(self) -> None:
        if self._owned_store is not None:
            self._owned_store.close()
            self._owned_store = None

    def __enter__(self) -> BitsoPayApp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


_REF_RE = re.compile(r"^[A-Za-z0-9]{8,35}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
_MAX_BODY = 16 * 1024
_MAX_PAGE_LIMIT = 500
_TRUTHY = {"1", "true", "yes", "on"}

# The payment page is self-contained (inline style + script, data: QR image) and needs no network.
_CSP_PAGE = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
_CSP_STRICT = "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
_SECURITY_HEADERS: Headers = [
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cache-Control", "no-store"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"),
]


class _Resp(NamedTuple):
    status: str
    body: bytes
    ctype: str
    extra: Tuple[Tuple[str, str], ...] = ()


def _text(status: str, message: str, extra: Optional[Headers] = None) -> _Resp:
    return _Resp(status, message.encode("utf-8"), "text/plain; charset=utf-8", tuple(extra or ()))


def _html(status: str, html: str) -> _Resp:
    return _Resp(status, html.encode("utf-8"), "text/html; charset=utf-8")


def _json(status: str, obj: Any, extra: Optional[Headers] = None) -> _Resp:
    return _Resp(status, json.dumps(obj).encode("utf-8"), "application/json", tuple(extra or ()))


def _query_dict(qs: str) -> Dict[str, str]:
    return {k: v[0] for k, v in parse_qs(qs).items() if v}


def _int_param(params: Dict[str, str], name: str, default: int, lo: int, hi: int) -> int:
    raw = params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError(f"{name} must be an integer") from None
    if not lo <= value <= hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}")
    return value


def _expires_in(data: Dict[str, Any], default: int = 86400) -> Optional[int]:
    """``expires_in`` from a JSON body: a positive integer, or ``null`` for no expiry."""
    if "expires_in" not in data:
        return default
    value = data["expires_in"]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("expires_in must be a whole number of seconds (or null)")
    return int(value)


def _read_json(environ: Environ) -> Dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise ValidationError("Invalid Content-Length") from None
    if length < 0:
        raise ValidationError("Invalid Content-Length")
    if length > _MAX_BODY:
        raise _TooLarge()
    if length == 0:
        return {}
    raw = environ["wsgi.input"].read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError("Body must be valid JSON") from None
    if not isinstance(data, dict):
        raise ValidationError("Body must be a JSON object")
    return data


class _TooLarge(Exception):
    """Request body over the size cap."""


def _configure_logging(level: str) -> None:
    """Send ``bitsopay.*`` logs to stderr at ``level`` (once), for gunicorn/Docker setups."""
    logger = logging.getLogger("bitsopay")
    try:
        logger.setLevel(level.upper())
    except ValueError:
        raise ValueError(f"Invalid BITSOPAY_LOG_LEVEL: {level!r}") from None
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


def create_app(
    secret: Optional[Union[str, bytes]] = None,
    *,
    store: Optional[PaymentStore] = None,
    admin_token: Optional[str] = None,
    base_url: Optional[str] = None,
    stateless: Optional[StatelessLinks] = None,
    clock: Callable[[], float] = time.time,
    trust_proxy: Optional[bool] = None,
    limiter: Optional[FailureLimiter] = None,
) -> BitsoPayApp:
    """Build the WSGI app.

    * ``secret``      (``$BITSOPAY_SECRET``)       enables legacy signed links
    * ``store``       (``$BITSOPAY_DB`` = SQLite path) enables short links + merchant API
    * ``admin_token`` (``$BITSOPAY_ADMIN_TOKEN``)  enables the merchant API
    * ``base_url``    (``$BITSOPAY_BASE_URL``)     public root used in returned links
    * ``stateless``   database-free short links; built from ``$BITSOPAY_UPI_ID`` +
      ``$BITSOPAY_PAYEE_NAME`` + ``$BITSOPAY_SECRET`` when those are set
    * ``trust_proxy`` (``$BITSOPAY_TRUST_PROXY``)  trust ``X-Forwarded-For/Proto`` (proxy you control)
    * ``limiter``     failed-login limiter for the merchant API (default: 10 failures / minute / IP)
    """
    env = os.environ
    if env.get("BITSOPAY_LOG_LEVEL"):
        _configure_logging(env["BITSOPAY_LOG_LEVEL"])
    key = secret if secret is not None else (env.get("BITSOPAY_SECRET") or None)
    owned_store: Optional[SQLiteStore] = None
    if store is None and env.get("BITSOPAY_DB"):
        store = owned_store = SQLiteStore(env["BITSOPAY_DB"])
    env_upi, env_name = env.get("BITSOPAY_UPI_ID"), env.get("BITSOPAY_PAYEE_NAME")
    if stateless is None and key and env_upi and env_name:
        stateless = StatelessLinks(env_upi, env_name, key, clock=clock)
    if not key and store is None and stateless is None:
        raise RuntimeError(
            "Set BITSOPAY_DB (short links), BITSOPAY_SECRET (+ BITSOPAY_UPI_ID and "
            "BITSOPAY_PAYEE_NAME for database-free links), or pass store= / secret= / stateless= to create_app()"
        )
    if key is not None and len(key) < 16:
        raise ValidationError("BITSOPAY_SECRET must be at least 16 characters")
    token = admin_token if admin_token is not None else env.get("BITSOPAY_ADMIN_TOKEN")
    if token and len(token) < 16:
        raise ValueError("Admin token must be at least 16 characters")
    public_base = (base_url or env.get("BITSOPAY_BASE_URL") or "").rstrip("/")
    behind_proxy = trust_proxy if trust_proxy is not None else env.get("BITSOPAY_TRUST_PROXY", "").lower() in _TRUTHY
    fail_limiter = limiter or FailureLimiter(clock=clock)
    links = PaymentLinks(store, clock=clock) if store is not None else None

    # ---- request helpers -----------------------------------------------
    def client_ip(environ: Environ) -> str:
        if behind_proxy:
            forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
            if forwarded:  # the last hop is the one our own proxy appended
                return forwarded.split(",")[-1].strip() or "unknown"
        return str(environ.get("REMOTE_ADDR") or "unknown")

    def scheme(environ: Environ) -> str:
        if behind_proxy and environ.get("HTTP_X_FORWARDED_PROTO"):
            return str(environ["HTTP_X_FORWARDED_PROTO"]).split(",")[-1].strip().lower()
        return str(environ.get("wsgi.url_scheme", "https"))

    # ---- short links ---------------------------------------------------
    def pending(
        environ: Environ,
        sub: str,
        payment: Any,
        expires_at: Optional[int],
        on_view: Optional[Callable[[], None]] = None,
    ) -> _Resp:
        if sub == "":
            if on_view is not None and environ.get("REQUEST_METHOD") == "GET":
                on_view()
            return _html("200 OK", render_payment_page(payment, expires_at))
        if sub == "qr.png":
            return _Resp("200 OK", qr_png(payment), "image/png")
        return _Resp("200 OK", qr_svg(payment).encode("utf-8"), "image/svg+xml")

    def gone(sub: str, ref: str, state: str) -> _Resp:
        if sub != "":
            return _text("410 Gone", f"Payment {state}")
        msg = "This payment link has expired." if state == EXPIRED else "This payment link was cancelled."
        return _html("410 Gone", render_message_page("Link unavailable", msg + " Please request a new one.", ref))

    def short(environ: Environ, path: str) -> _Resp:
        parts = path[len("/p/") :].split("/")
        ref, sub = parts[0], (parts[1] if len(parts) > 1 else "")
        if len(parts) > 2 or sub not in ("", "qr.png", "qr.svg", "status") or not _REF_RE.match(ref):
            return _text("404 Not Found", "Not found")
        rec = links.get(ref) if links is not None else None
        if links is not None and rec is not None:
            state = links.status_of(rec)
            if sub == "status":
                return _json("200 OK", {"reference": rec.reference, "status": state, "expires_at": rec.expires_at})
            if state == PAID:
                if sub != "":
                    return _text("410 Gone", "Payment paid")
                return _html(
                    "200 OK",
                    render_message_page(
                        "Payment received", "This payment has been confirmed. Thank you!", rec.reference
                    ),
                )
            if state != PENDING:
                return gone(sub, rec.reference, state)
            return pending(environ, sub, rec.to_payment(), rec.expires_at, lambda: links.record_view(ref))
        if stateless is not None:
            try:
                payment, exp = stateless.decode(ref)
            except LinkExpiredError:
                if sub == "status":
                    return _json("200 OK", {"reference": ref.upper(), "status": EXPIRED, "expires_at": None})
                return gone(sub, ref.upper(), EXPIRED)
            except (SignatureError, ValidationError):
                pass
            else:
                if sub == "status":
                    return _json("200 OK", {"reference": payment.reference, "status": PENDING, "expires_at": exp})
                return pending(environ, sub, payment, exp)
        if sub == "":
            return _html("404 Not Found", render_message_page("Link not found", "This payment link is not valid."))
        return _text("404 Not Found", "Not found")

    # ---- merchant API --------------------------------------------------
    def authorised(environ: Environ) -> Optional[_Resp]:
        """``None`` when the bearer token is right, otherwise the error response."""
        ip = client_ip(environ)
        wait = fail_limiter.retry_after(ip)
        if wait:
            return _json("429 Too Many Requests", {"error": "too many failed attempts"}, [("Retry-After", str(wait))])
        auth = environ.get("HTTP_AUTHORIZATION", "")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token or not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
            fail_limiter.record_failure(ip)
            log.warning("admin auth failed ip=%s", ip)
            return _json(
                "401 Unauthorized", {"error": "unauthorized"}, [("WWW-Authenticate", 'Bearer realm="bitsopay"')]
            )
        fail_limiter.reset(ip)
        return None

    def admin(environ: Environ, path: str) -> _Resp:
        if not token:
            return _json("404 Not Found", {"error": "merchant API disabled"})
        denied = authorised(environ)
        if denied is not None:
            return denied
        method = environ.get("REQUEST_METHOD")
        parts = [p for p in path[len("/api/") :].split("/") if p]
        host = environ.get("HTTP_HOST") or environ.get("SERVER_NAME", "localhost")
        base = public_base or f"{scheme(environ)}://{host}"
        if links is None and not (parts == ["payments"] and method == "POST"):
            return _json("501 Not Implemented", {"error": "history and status changes need a store (BITSOPAY_DB)"})
        try:
            if parts == ["payments"] and method == "POST":
                data = _read_json(environ)
                if links is None:
                    if stateless is None:  # pragma: no cover - guarded by create_app
                        return _json("501 Not Implemented", {"error": "no link backend configured"})
                    sl = stateless.create(data.get("amount"), expires_in=_expires_in(data), base_url=base)
                    return _json(
                        "201 Created",
                        {
                            "reference": sl.reference,
                            "status": PENDING,
                            "url": sl.url,
                            "amount": None if sl.amount is None else f"{sl.amount:.2f}",
                            "expires_at": sl.expires_at,
                        },
                    )
                link = links.create(
                    data.get("upi_id", ""),
                    data.get("payee_name", ""),
                    data.get("amount"),
                    note=data.get("note"),
                    merchant_code=data.get("merchant_code"),
                    expires_in=_expires_in(data),
                    base_url=base,
                )
                out = link.record.to_dict(clock())
                out["url"] = link.url
                return _json("201 Created", out)
            if links is None:  # pragma: no cover - guarded above
                return _json("501 Not Implemented", {"error": "needs a store"})
            if parts == ["payments"] and method == "GET":
                q = _query_dict(environ.get("QUERY_STRING", ""))
                rows = links.history(
                    q.get("status"),
                    _int_param(q, "limit", 50, 1, _MAX_PAGE_LIMIT),
                    _int_param(q, "offset", 0, 0, 10**9),
                )
                now = clock()
                return _json("200 OK", {"payments": [r.to_dict(now) for r in rows]})
            if len(parts) == 2 and parts[0] == "payments" and method == "GET":
                rec = links.get(parts[1])
                if rec is None:
                    raise NotFoundError(parts[1])
                out = rec.to_dict(clock())
                out["url"] = links.url_for(rec.reference, base)
                return _json("200 OK", out)
            if len(parts) == 3 and parts[0] == "payments" and method == "POST":
                if parts[2] == "paid":
                    rec = links.mark_paid(parts[1], _read_json(environ).get("note"))
                elif parts[2] == "cancel":
                    rec = links.cancel(parts[1])
                else:
                    return _json("404 Not Found", {"error": "not found"})
                return _json("200 OK", rec.to_dict(clock()))
        except _TooLarge:
            return _json("413 Payload Too Large", {"error": "body too large"})
        except ValidationError as exc:
            return _json("400 Bad Request", {"error": str(exc)})
        except NotFoundError:
            return _json("404 Not Found", {"error": "payment not found"})
        except InvalidStateError as exc:
            return _json("409 Conflict", {"error": str(exc)})
        except ValueError:
            return _json("400 Bad Request", {"error": "invalid request"})
        return _json("404 Not Found", {"error": "not found"})

    # ---- legacy signed links -------------------------------------------
    def legacy(environ: Environ, path: str) -> _Resp:
        if key is None:  # pragma: no cover - guarded by caller
            return _text("404 Not Found", "Not found")
        try:
            payment, expires_at = verify_payment_link(environ.get("QUERY_STRING", ""), key)
        except LinkExpiredError:
            return _text("410 Gone", "This payment link has expired")
        except (SignatureError, ValidationError):
            return _text("400 Bad Request", "Invalid payment link")
        if path == "/pay":
            return _html("200 OK", render_payment_page(payment, expires_at))
        if path == "/qr.png":
            return _Resp("200 OK", qr_png(payment), "image/png")
        return _Resp("200 OK", qr_svg(payment).encode("utf-8"), "image/svg+xml")

    # ---- probes --------------------------------------------------------
    def ready() -> _Resp:
        if store is not None:
            try:
                store.list(limit=1, now=clock())
            except Exception:
                log.exception("readiness check failed")
                return _text("503 Service Unavailable", "store unavailable")
        return _text("200 OK", "ready")

    # ---- dispatch ------------------------------------------------------
    def route(environ: Environ) -> _Resp:
        method = environ.get("REQUEST_METHOD")
        path = environ.get("PATH_INFO", "/")
        if path == "/health":
            return _text("200 OK", "ok")
        if path == "/ready":
            return ready()
        if path.startswith("/api/") and (links is not None or stateless is not None):
            return admin(environ, path)
        if method not in ("GET", "HEAD"):
            return _text("405 Method Not Allowed", "Method not allowed", [("Allow", "GET, HEAD")])
        if (links is not None or stateless is not None) and path.startswith("/p/"):
            return short(environ, path)
        if key and path in ("/pay", "/qr.png", "/qr.svg"):
            return legacy(environ, path)
        return _text("404 Not Found", "Not found")

    def app(environ: Environ, start_response: StartResponse) -> Iterable[bytes]:
        began = time.perf_counter()
        supplied_id = environ.get("HTTP_X_REQUEST_ID", "")
        request_id = supplied_id if _REQUEST_ID_RE.match(supplied_id) else secrets.token_hex(8)
        try:
            resp = route(environ)
        except Exception:
            log.exception("unhandled error id=%s", request_id)
            resp = _json("500 Internal Server Error", {"error": "internal error", "request_id": request_id})
        body = resp.body
        headers: Headers = [("Content-Type", resp.ctype), ("Content-Length", str(len(body)))]
        headers += _SECURITY_HEADERS
        headers.append(("Content-Security-Policy", _CSP_PAGE if resp.ctype.startswith("text/html") else _CSP_STRICT))
        headers.append(("X-Request-ID", request_id))
        if scheme(environ) == "https":
            headers.append(("Strict-Transport-Security", "max-age=31536000"))
        headers += list(resp.extra)
        start_response(resp.status, headers)
        if log.isEnabledFor(logging.INFO):
            log.info(
                "%s %s -> %s %.1fms ip=%s id=%s",
                environ.get("REQUEST_METHOD"),
                environ.get("PATH_INFO"),
                resp.status.split(" ", 1)[0],
                (time.perf_counter() - began) * 1000,
                client_ip(environ),
                request_id,
            )
        return [] if environ.get("REQUEST_METHOD") == "HEAD" else [body]

    return BitsoPayApp(app, owned_store)


def serve(
    secret: Optional[Union[str, bytes]] = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    store: Optional[PaymentStore] = None,
    admin_token: Optional[str] = None,
    base_url: Optional[str] = None,
    stateless: Optional[StatelessLinks] = None,
) -> None:
    """Run a development server (use gunicorn/uwsgi in production)."""
    from wsgiref.simple_server import make_server

    with (
        create_app(secret, store=store, admin_token=admin_token, base_url=base_url, stateless=stateless) as app,
        make_server(host, port, app) as httpd,
    ):
        print(f"bitsopay serving on http://{host}:{port}  (Ctrl+C to stop; development server only)")
        httpd.serve_forever()
