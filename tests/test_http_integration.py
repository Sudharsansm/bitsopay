"""End-to-end: a real HTTP server on a socket, driven with urllib (no WSGI shortcuts)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from bitsopay import SQLiteStore
from bitsopay.server import create_app
from conftest import TOKEN


class _Quiet(WSGIRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass


@contextmanager
def running(app: Any) -> Iterator[str]:
    httpd = make_server("127.0.0.1", 0, app, handler_class=_Quiet)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def fetch(
    url: str, *, method: str = "GET", body: Optional[Dict[str, Any]] = None, token: Optional[str] = None
) -> Tuple[int, Any, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def test_full_merchant_flow_over_http(tmp_path):
    with SQLiteStore(tmp_path / "e2e.db") as store, running(create_app(store=store, admin_token=TOKEN)) as base:
        assert fetch(f"{base}/health")[:1] == (200,)
        assert fetch(f"{base}/ready")[:1] == (200,)

        status, _, body = fetch(
            f"{base}/api/payments",
            method="POST",
            token=TOKEN,
            body={"upi_id": "shop@okhdfcbank", "payee_name": "My Shop", "amount": "499.50", "note": "Order 7"},
        )
        created = json.loads(body)
        assert status == 201 and created["url"].startswith(f"{base}/p/BP")
        ref = created["reference"]

        status, headers, page = fetch(f"{base}/p/{ref}")
        assert status == 200 and b"499.50" in page and b"My Shop" in page
        assert headers["Content-Type"].startswith("text/html")
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert headers["X-Request-ID"]

        assert fetch(f"{base}/p/{ref}/qr.png")[2].startswith(b"\x89PNG")
        assert json.loads(fetch(f"{base}/p/{ref}/status")[2])["status"] == "pending"
        assert fetch(f"{base}/p/{ref}", method="HEAD")[2] == b""

        assert fetch(f"{base}/api/payments")[0] == 401
        assert fetch(f"{base}/api/payments/{ref}/paid", method="POST", token=TOKEN, body={"note": "UTR1"})[0] == 200
        assert b"Payment received" in fetch(f"{base}/p/{ref}")[2]
        history = json.loads(fetch(f"{base}/api/payments?status=paid", token=TOKEN)[2])["payments"]
        assert [row["reference"] for row in history] == [ref]


def test_unknown_link_is_404_over_http():
    with SQLiteStore() as store, running(create_app(store=store, admin_token=TOKEN)) as base:
        assert fetch(f"{base}/p/BPDOESNOTEXIST00")[0] == 404
        assert fetch(f"{base}/nothing")[0] == 404


@pytest.mark.parametrize("path", ["/p/../../etc/passwd", "/p/%2e%2e/secret", "/api/../health"])
def test_path_traversal_attempts_never_leak(path):
    with SQLiteStore() as store, running(create_app(store=store, admin_token=TOKEN)) as base:
        status, _, body = fetch(base + path)
        assert status in (200, 400, 401, 404) and b"root:" not in body
