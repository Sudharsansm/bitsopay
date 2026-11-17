"""Static QR Code: one reusable QR per UPI id, open amount, short rolling expiry."""

import json

import pytest

from bitsopay import StaticSession, LinkExpiredError, MemoryStore, SignatureError, ValidationError, verify_payment_link
from bitsopay.server import create_app
from conftest import SECRET, TOKEN, FakeClock, make_caller

BASE = "https://pay.example.com/pay"


def make(clock=None, **kw):
    return StaticSession("shop@okhdfcbank", "My Shop", SECRET, BASE, clock=clock or FakeClock(1000), **kw)


# ---- reuse within the window ------------------------------------------------------


def test_same_upi_id_reuses_the_qr_within_the_window():
    session = make(window=300)
    a = session.create(now=1000)
    b = session.create(now=1200)
    assert a.url == b.url and a.reference == b.reference


def test_window_lapsing_mints_a_new_qr():
    session = make(window=300)
    a = session.create(now=1000)
    b = session.create(now=1301)
    assert a.url != b.url


def test_changing_the_upi_id_mints_a_new_qr_immediately():
    session = make(window=300)
    a = session.create(now=1000)
    b = session.create(upi_id="other@okaxis", now=1000)
    assert a.url != b.url and b.upi_id == "other@okaxis"
    # and it's remembered for later calls
    c = session.create(now=1100)
    assert c.url == b.url


def test_open_amount_and_default_window():
    qr = make().create(now=0)
    payment, _ = verify_payment_link(qr.url, SECRET, now=0)
    assert payment.amount is None
    assert qr.expires_at - qr.issued_at == 300


def test_reference_is_generated_like_the_demo():
    qr = make().create(now=0)
    assert qr.reference.startswith("BP")


def test_window_must_be_positive():
    with pytest.raises(ValidationError):
        make(window=0)


def test_base_url_required_somewhere():
    session = StaticSession("shop@okhdfcbank", "My Shop", SECRET)
    with pytest.raises(ValidationError):
        session.create(now=0)
    qr = session.create(base_url=BASE, now=0)
    assert qr.url.startswith(BASE)


def test_qr_outputs(tmp_path):
    qr = make().create(now=0)
    assert qr.png().startswith(b"\x89PNG") and "<svg" in qr.svg()
    saved = qr.save(tmp_path / "counter.png")
    assert saved.exists()


def test_wrong_secret_is_rejected():
    qr = make().create(now=0)
    with pytest.raises(SignatureError):
        verify_payment_link(qr.url, "another-secret-long-enough", now=0)


def test_expired_qr_is_rejected_by_verification():
    qr = make(window=60).create(now=0)
    with pytest.raises(LinkExpiredError):
        verify_payment_link(qr.url, SECRET, now=61)


# ---- server -------------------------------------------------------------------


@pytest.fixture
def served():
    clock = FakeClock(1000)
    app = create_app(sessions=make(clock), admin_token=TOKEN, base_url="https://pay.example.com", clock=clock)
    return make_caller(app), clock


def rotate(call, **body):
    status, _, raw = call("/api/sessions", method="POST", token=TOKEN, body=body)
    return status, json.loads(raw)


def test_server_serves_the_current_qr(served):
    call, _ = served
    status, headers, png = call("/s/qr.png")
    assert status.startswith("200") and headers["Content-Type"] == "image/png" and png.startswith(b"\x89PNG")
    status, headers, svg = call("/s/qr.svg")
    assert status.startswith("200") and headers["Content-Type"] == "image/svg+xml" and b"<svg" in svg
    status, _, raw = call("/s/status")
    out = json.loads(raw)
    assert status.startswith("200") and out["upi_id"] == "shop@okhdfcbank" and "reference" in out


def test_server_reuses_the_qr_across_requests(served):
    call, clock = served
    first = json.loads(call("/s/status")[2])
    clock.t += 10
    second = json.loads(call("/s/status")[2])
    assert first["reference"] == second["reference"]


def test_server_rotates_the_qr_when_upi_id_changes(served):
    call, _ = served
    before = json.loads(call("/s/status")[2])
    status, out = rotate(call, upi_id="other@okaxis")
    assert status.startswith("201") and out["upi_id"] == "other@okaxis"
    after = json.loads(call("/s/status")[2])
    assert after["upi_id"] == "other@okaxis" and after["reference"] != before["reference"]


def test_server_unknown_subpaths_404(served):
    call, _ = served
    assert call("/s/other")[0].startswith("404")
    assert call("/s/qr.png/extra")[0].startswith("404")
    assert call("/s/")[0].startswith("404")


def test_server_without_sessions_configured():
    clock = FakeClock(1000)
    call = make_caller(create_app(store=MemoryStore(), admin_token=TOKEN, base_url=BASE, clock=clock))
    assert call("/s/qr.png")[0].startswith("404")
    status, _, raw = call("/api/sessions", method="POST", token=TOKEN, body={})
    assert status.startswith("501") and b"BITSOPAY_UPI_ID" in raw


def test_server_sessions_only_needs_no_secret_or_database():
    clock = FakeClock(1000)
    call = make_caller(create_app(sessions=make(clock), clock=clock))
    assert call("/s/qr.png")[0].startswith("200")
    assert call("/health")[0].startswith("200")


def test_server_sessions_from_environment(monkeypatch):
    monkeypatch.setenv("BITSOPAY_SECRET", SECRET)
    monkeypatch.setenv("BITSOPAY_UPI_ID", "shop@okhdfcbank")
    monkeypatch.setenv("BITSOPAY_PAYEE_NAME", "My Shop")
    monkeypatch.setenv("BITSOPAY_ADMIN_TOKEN", TOKEN)
    call = make_caller(create_app())
    assert call("/s/qr.png")[0].startswith("200")
    status, out = rotate(call)
    assert status.startswith("201") and out["upi_id"] == "shop@okhdfcbank"
