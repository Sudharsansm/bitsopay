"""Shared test helpers."""

from __future__ import annotations

import io
import json
from typing import Any, Callable, Dict, Optional, Tuple

import pytest

TOKEN = "admin-token-long-enough"
SECRET = "0123456789abcdef-secret"


class FakeClock:
    def __init__(self, t: float = 1_000_000) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


Result = Tuple[str, Dict[str, str], bytes]


def make_caller(app: Callable[..., Any]) -> Callable[..., Result]:
    """Return ``call(path, ...)`` that drives a WSGI app directly, without a socket."""

    def call(
        path: str,
        *,
        query: str = "",
        method: str = "GET",
        body: Any = None,
        raw: Optional[bytes] = None,
        token: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        scheme: str = "https",
        remote: str = "203.0.113.9",
        content_length: Optional[str] = None,
    ) -> Result:
        out: Dict[str, Any] = {}

        def start(status: str, hdrs: Any) -> None:
            out["status"], out["headers"] = status, dict(hdrs)

        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        env: Dict[str, Any] = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "wsgi.input": io.BytesIO(payload),
            "CONTENT_LENGTH": content_length if content_length is not None else str(len(payload)),
            "wsgi.url_scheme": scheme,
            "HTTP_HOST": "pay.test",
            "REMOTE_ADDR": remote,
        }
        if token:
            env["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        for k, v in (headers or {}).items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
        data = b"".join(app(env, start))
        return out["status"], out["headers"], data

    return call


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(autouse=True)
def _restore_bitsopay_logger():
    """create_app() may configure the 'bitsopay' logger; keep tests independent."""
    import logging

    logger = logging.getLogger("bitsopay")
    handlers, level = list(logger.handlers), logger.level
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
