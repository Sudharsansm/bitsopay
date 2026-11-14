import json

import pytest

from bitsopay import MemoryStore, PaymentStore, StatelessLinks, ValidationError
from bitsopay.ratelimit import FailureLimiter
from bitsopay.server import create_app
from conftest import SECRET, TOKEN, make_caller

CREATE = {"upi_id": "shop@okhdfcbank", "payee_name": "My Shop", "amount": 100}


@pytest.fixture
def app(clock):
    return create_app(store=MemoryStore(), admin_token=TOKEN, base_url="https://pay.example.com", clock=clock)


@pytest.fixture
def call(app):
    return make_caller(app)


def create(call, **extra):
    return call("/api/payments", method="POST", body={**CREATE, **extra}, token=TOKEN)


# ---- headers & transport ------------------------------------------------------------------------


def test_security_headers_on_every_response(call):
    ref = json.loads(create(call)[2])["reference"]
    for path in ("/health", f"/p/{ref}", f"/p/{ref}/qr.png", "/nope"):
        _, h, _ = call(path)
        assert h["X-Content-Type-Options"] == "nosniff"
        assert h["X-Frame-Options"] == "DENY"
        assert h["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
        assert h["Strict-Transport-Security"].startswith("max-age=")
    assert "script-src 'unsafe-inline'" in call(f"/p/{ref}")[1]["Content-Security-Policy"]
    assert "script-src" not in call("/health")[1]["Content-Security-Policy"]


def test_no_hsts_over_plain_http(call):
    assert "Strict-Transport-Security" not in call("/health", scheme="http")[1]


def test_request_id_generated_or_echoed(call):
    first = call("/health")[1]["X-Request-ID"]
    assert len(first) == 16
    assert call("/health", headers={"X-Request-ID": "trace-123"})[1]["X-Request-ID"] == "trace-123"
    assert call("/health", headers={"X-Request-ID": "bad id\r\nX: y"})[1]["X-Request-ID"] != "bad id\r\nX: y"


def test_head_has_headers_but_no_body(call):
    ref = json.loads(create(call)[2])["reference"]
    status, headers, body = call(f"/p/{ref}", method="HEAD")
    assert status.startswith("200") and body == b"" and int(headers["Content-Length"]) > 0


def test_405_lists_allowed_methods(call):
    status, headers, _ = call("/p/BPABCDEFGH12", method="DELETE")
    assert status.startswith("405") and headers["Allow"] == "GET, HEAD"


# ---- probes & failure handling -----------------------------------------------------------------


def test_ready_ok_and_store_down():
    class Broken(MemoryStore):
        def list(self, *args, **kwargs):
            raise RuntimeError("db down")

    assert make_caller(create_app(store=MemoryStore()))("/ready")[0].startswith("200")
    status, _, body = make_caller(create_app(store=Broken()))("/ready")
    assert status.startswith("503") and b"db down" not in body
    assert make_caller(create_app(SECRET))("/ready")[0].startswith("200")  # no store: nothing to check


def test_unhandled_error_is_generic_with_request_id(clock):
    class Exploding(MemoryStore):
        def get(self, reference):
            raise RuntimeError("secret internal detail")

    call = make_caller(create_app(store=Exploding(), clock=clock))
    status, headers, body = call("/p/BPABCDEFGH12345")
    assert status.startswith("500")
    assert b"secret internal detail" not in body
    assert json.loads(body)["request_id"] == headers["X-Request-ID"]


# ---- input validation --------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["limit=-1", "limit=0", "limit=501", "limit=abc", "offset=-1", "offset=x"])
def test_history_paging_is_validated(call, query):
    assert call("/api/payments", query=query, token=TOKEN)[0].startswith("400")


def test_history_paging_works(call):
    for _ in range(3):
        create(call)
    rows = json.loads(call("/api/payments", query="limit=2&offset=1", token=TOKEN)[2])["payments"]
    assert len(rows) == 2


@pytest.mark.parametrize("bad", ["3600", 1.5, True, [1], {"a": 1}])
def test_expires_in_must_be_a_whole_number(call, bad):
    status, _, body = create(call, expires_in=bad)
    assert status.startswith("400") and b"expires_in" in body


def test_expires_in_zero_or_negative_rejected_and_null_means_never(call):
    assert create(call, expires_in=0)[0].startswith("400")
    assert create(call, expires_in=-5)[0].startswith("400")
    status, _, body = create(call, expires_in=None)
    assert status.startswith("201") and json.loads(body)["expires_at"] is None


def test_stateless_expires_in_validated(clock):
    links = StatelessLinks("shop@okhdfcbank", "My Shop", SECRET, clock=clock)
    call = make_caller(create_app(stateless=links, admin_token=TOKEN, base_url="https://pay.example.com", clock=clock))
    assert call("/api/payments", method="POST", body={"amount": 5, "expires_in": "soon"}, token=TOKEN)[0].startswith(
        "400"
    )
    assert call("/api/payments", method="POST", body={"amount": 5, "expires_in": None}, token=TOKEN)[0].startswith(
        "201"
    )


def test_body_limits_and_json_errors(call):
    assert call("/api/payments", method="POST", raw=b"x" * 20000, token=TOKEN)[0].startswith("413")
    assert call("/api/payments", method="POST", raw=b"{nope", token=TOKEN)[0].startswith("400")
    assert call("/api/payments", method="POST", raw=b"[1,2]", token=TOKEN)[0].startswith("400")
    assert call("/api/payments", method="POST", raw=b"\xff\xfe", token=TOKEN)[0].startswith("400")
    assert call("/api/payments", method="POST", token=TOKEN, content_length="abc")[0].startswith("400")
    assert call("/api/payments", method="POST", token=TOKEN, content_length="-5")[0].startswith("400")


def test_paid_note_body_is_bounded(call):
    ref = json.loads(create(call)[2])["reference"]
    assert call(f"/api/payments/{ref}/paid", method="POST", raw=b"x" * 20000, token=TOKEN)[0].startswith("413")
    assert call(f"/api/payments/{ref}/paid", method="POST", body={"note": "x" * 500}, token=TOKEN)[0].startswith("400")


def test_unknown_api_routes(call):
    ref = json.loads(create(call)[2])["reference"]
    assert call("/api/unknown", token=TOKEN)[0].startswith("404")
    assert call(f"/api/payments/{ref}/refund", method="POST", token=TOKEN)[0].startswith("404")
    assert call("/api/payments", method="PUT", token=TOKEN)[0].startswith("404")


def test_idempotent_status_changes(call):
    ref = json.loads(create(call)[2])["reference"]
    for _ in range(2):
        assert call(f"/api/payments/{ref}/paid", method="POST", token=TOKEN)[0].startswith("200")
    ref2 = json.loads(create(call)[2])["reference"]
    for _ in range(2):
        assert call(f"/api/payments/{ref2}/cancel", method="POST", token=TOKEN)[0].startswith("200")
    assert call(f"/api/payments/{ref2}/paid", method="POST", token=TOKEN)[0].startswith("409")


# ---- brute-force protection --------------------------------------------------------------------


def test_admin_token_brute_force_is_throttled(clock):
    call = make_caller(create_app(store=MemoryStore(), admin_token=TOKEN, clock=clock))
    for _ in range(10):
        assert call("/api/payments", token="wrong-wrong-wrong-wrong")[0].startswith("401")
    status, headers, _ = call("/api/payments", token="wrong-wrong-wrong-wrong")
    assert status.startswith("429") and int(headers["Retry-After"]) > 0
    # the right token is refused too while blocked, but other clients are unaffected
    assert call("/api/payments", token=TOKEN)[0].startswith("429")
    assert call("/api/payments", token=TOKEN, remote="198.51.100.7")[0].startswith("200")
    clock.t += 61
    assert call("/api/payments", token=TOKEN)[0].startswith("200")


def test_success_resets_failure_count(clock):
    call = make_caller(
        create_app(store=MemoryStore(), admin_token=TOKEN, clock=clock, limiter=FailureLimiter(3, 60, clock=clock))
    )
    for _ in range(2):
        call("/api/payments", token="wrong-wrong-wrong-wrong")
    assert call("/api/payments", token=TOKEN)[0].startswith("200")
    for _ in range(2):
        assert call("/api/payments", token="wrong-wrong-wrong-wrong")[0].startswith("401")


def test_trust_proxy_uses_last_forwarded_hop(clock):
    app = create_app(
        store=MemoryStore(),
        admin_token=TOKEN,
        clock=clock,
        trust_proxy=True,
        limiter=FailureLimiter(2, 60, clock=clock),
    )
    call = make_caller(app)
    spoof = {"X-Forwarded-For": "1.1.1.1, 10.0.0.5"}  # client-supplied first hop, proxy-appended last hop
    for _ in range(2):
        call("/api/payments", token="wrong-wrong-wrong-wrong", headers=spoof)
    # same real client behind the proxy, different spoofed prefix: still blocked
    assert call("/api/payments", token=TOKEN, headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.5"})[0].startswith("429")
    assert call("/api/payments", token=TOKEN, headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.6"})[0].startswith("200")
    # scheme comes from X-Forwarded-Proto
    assert "Strict-Transport-Security" not in call("/health", scheme="https", headers={"X-Forwarded-Proto": "http"})[1]


def test_proxy_headers_ignored_unless_trusted(clock):
    call = make_caller(
        create_app(store=MemoryStore(), admin_token=TOKEN, clock=clock, limiter=FailureLimiter(2, 60, clock=clock))
    )
    for i in range(2):
        call("/api/payments", token="wrong-wrong-wrong-wrong", headers={"X-Forwarded-For": f"8.8.8.{i}"})
    assert call("/api/payments", token=TOKEN, headers={"X-Forwarded-For": "8.8.4.4"})[0].startswith("429")


# ---- configuration -----------------------------------------------------------------------------


def test_short_secret_fails_at_startup():
    with pytest.raises(ValidationError, match="16"):
        create_app("too-short")


def test_environment_configuration(monkeypatch, tmp_path, clock):
    monkeypatch.setenv("BITSOPAY_DB", str(tmp_path / "env.db"))
    monkeypatch.setenv("BITSOPAY_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("BITSOPAY_BASE_URL", "https://env.example.com/")
    monkeypatch.setenv("BITSOPAY_TRUST_PROXY", "yes")
    monkeypatch.setenv("BITSOPAY_LOG_LEVEL", "warning")
    with create_app(clock=clock) as app:
        status, _, body = create(make_caller(app))
    assert status.startswith("201") and json.loads(body)["url"].startswith("https://env.example.com/p/BP")
    assert (tmp_path / "env.db").exists()


def test_store_abc_is_exported():
    assert PaymentStore.__abstractmethods__ >= {"add", "get", "save", "list", "record_view"}


def test_log_level_configures_a_handler_and_rejects_junk(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("BITSOPAY_LOG_LEVEL", "info")
    logger = logging.getLogger("bitsopay")
    before = list(logger.handlers)
    try:
        call = make_caller(create_app(store=MemoryStore()))
        assert logger.level == logging.INFO and len(logger.handlers) == len(before) + 1
        with caplog.at_level(logging.INFO, logger="bitsopay.server"):
            call("/health")
        assert "GET /health -> 200" in caplog.text
    finally:
        logger.handlers[:] = before
        logger.setLevel(logging.NOTSET)
    monkeypatch.setenv("BITSOPAY_LOG_LEVEL", "loud")
    with pytest.raises(ValueError, match="BITSOPAY_LOG_LEVEL"):
        create_app(store=MemoryStore())
