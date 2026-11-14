import time
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from bitsopay import (
    LinkExpiredError,
    SignatureError,
    UPIPayment,
    ValidationError,
    build_app_uri,
    create_payment_link,
    create_session_qr,
    new_reference,
    parse_payment_link,
    qr_data_uri,
    qr_png,
    qr_svg,
    render_payment_page,
    save_qr,
    verify_payment_link,
)
from bitsopay.cli import main
from bitsopay.server import create_app

SECRET = "a-long-enough-test-secret-key"


def pay(**kw):
    base = {"upi_id": "shop@okhdfcbank", "payee_name": "My Shop", "amount": "499"}
    base.update(kw)
    return UPIPayment(**base)


# ---- validation -----------------------------------------------------------


@pytest.mark.parametrize("vpa", ["a", "no-at-sign", "x@", "@bank", "a b@bank", "ab@1bank"])
def test_bad_vpa(vpa):
    with pytest.raises(ValidationError):
        pay(upi_id=vpa)


@pytest.mark.parametrize("amt", [0, -5, "abc", "nan", "inf", True, 10**9])
def test_bad_amount(amt):
    with pytest.raises(ValidationError):
        pay(amount=amt)


def test_amount_rounding_and_open_amount():
    assert pay(amount="10.005").amount == Decimal("10.01")
    assert pay(amount=None).amount is None


def test_name_required_and_limits():
    with pytest.raises(ValidationError):
        pay(payee_name="  ")
    with pytest.raises(ValidationError):
        pay(note="x" * 81)
    with pytest.raises(ValidationError):
        pay(reference="bad ref!")
    with pytest.raises(ValidationError):
        pay(merchant_code="12")


def test_new_reference_valid_and_unique():
    a, b = new_reference(), new_reference()
    assert a != b and len(a) <= 35
    assert pay().with_reference().reference.startswith("BP")


# ---- uri -----------------------------------------------------------------


def test_uri_format():
    p = pay(note="Order #12", reference="ORD123")
    assert p.uri == ("upi://pay?pa=shop@okhdfcbank&pn=My%20Shop&am=499.00&cu=INR&tn=Order%20%2312&tr=ORD123")


def test_uri_open_amount_has_no_am():
    assert "am=" not in pay(amount=None).uri


def test_uri_escapes_injection():
    p = pay(payee_name="A&B=C?x")
    q = parse_qs(urlparse(p.uri).query)
    assert q["pn"] == ["A&B=C?x"] and q["pa"] == ["shop@okhdfcbank"]


def test_app_uri():
    assert build_app_uri(pay(), "gpay").startswith("gpay://upi/pay?pa=")
    with pytest.raises(ValueError):
        build_app_uri(pay(), "nope")


# ---- qr ------------------------------------------------------------------


def test_qr_outputs(tmp_path):
    assert qr_png(pay()).startswith(b"\x89PNG")
    assert "<svg" in qr_svg(pay())
    assert qr_data_uri(pay()).startswith("data:image/png;base64,")
    out = save_qr(pay(), tmp_path / "q.png")
    assert out.read_bytes().startswith(b"\x89PNG")
    save_qr(pay(), tmp_path / "q.svg")
    with pytest.raises(ValueError):
        save_qr(pay(), tmp_path / "q.jpg")
    with pytest.raises(ValueError):
        qr_png(pay(), error="Z")


# ---- signed links --------------------------------------------------------


def test_link_roundtrip():
    p = pay(note="hi", reference="R1", merchant_code="5411")
    url = create_payment_link("https://pay.example.com/pay", p, SECRET)
    back = parse_payment_link(url, SECRET)
    assert back == p
    assert parse_payment_link(urlparse(url).query, SECRET) == p


def test_link_tamper_detected():
    url = create_payment_link("https://x.test/pay", pay(), SECRET)
    with pytest.raises(SignatureError):
        parse_payment_link(url.replace("am=499.00", "am=1.00"), SECRET)
    with pytest.raises(SignatureError):
        parse_payment_link(url, "another-long-enough-secret-key")
    with pytest.raises(SignatureError):
        parse_payment_link("https://x.test/pay?pa=a@b", SECRET)


def test_link_expiry():
    url = create_payment_link("https://x.test/pay", pay(), SECRET, expires_in=60, now=1000)
    parse_payment_link(url, SECRET, now=1030)
    with pytest.raises(LinkExpiredError):
        parse_payment_link(url, SECRET, now=1061)
    never = create_payment_link("https://x.test/pay", pay(), SECRET, expires_in=None)
    parse_payment_link(never, SECRET, now=time.time() + 10**8)


def test_weak_secret_and_bad_base_url():
    with pytest.raises(ValidationError):
        create_payment_link("https://x.test/pay", pay(), "short")
    with pytest.raises(ValidationError):
        create_payment_link("ftp://x.test", pay(), SECRET)


# ---- page ----------------------------------------------------------------


def test_page_escapes_html():
    html = render_payment_page(pay(payee_name="<script>alert(1)</script>", note='"><img src=x>'))
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "src=x>" not in html.replace("&gt;", "")
    assert "upi://pay?" in html and "data:image/png;base64," in html


# ---- wsgi ----------------------------------------------------------------


def call(app, path, query="", method="GET"):
    out = {}

    def start(status, headers):
        out["status"], out["headers"] = status, dict(headers)

    body = b"".join(app({"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query}, start))
    return out["status"], out["headers"], body


def test_server_routes():
    app = create_app(SECRET)
    query = urlparse(create_payment_link("https://x.test/pay", pay(), SECRET)).query
    status, headers, body = call(app, "/pay", query)
    assert status.startswith("200") and b"My Shop" in body
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert call(app, "/qr.png", query)[2].startswith(b"\x89PNG")
    assert b"<svg" in call(app, "/qr.svg", query)[2]
    assert call(app, "/health")[0].startswith("200")
    assert call(app, "/pay", query.replace("499.00", "1.00"))[0].startswith("400")
    assert call(app, "/nope")[0].startswith("404")
    assert call(app, "/pay", query, "POST")[0].startswith("405")


def test_server_expired_and_missing_secret(monkeypatch):
    app = create_app(SECRET)
    url = create_payment_link("https://x.test/pay", pay(), SECRET, expires_in=1, now=1)
    assert call(app, "/pay", urlparse(url).query)[0].startswith("410")
    monkeypatch.delenv("BITSOPAY_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        create_app()


# ---- cli -----------------------------------------------------------------


def test_cli(tmp_path, capsys):
    common = ["--upi-id", "shop@okhdfcbank", "--name", "My Shop", "--amount", "50"]
    assert main(["uri", *common]) == 0
    assert capsys.readouterr().out.startswith("upi://pay?")
    assert main(["qr", *common, "-o", str(tmp_path / "a.png")]) == 0
    assert (tmp_path / "a.png").exists()
    assert main(["page", *common, "-o", str(tmp_path / "a.html")]) == 0
    assert main(["link", *common, "--base-url", "https://x.test/pay", "--secret", SECRET]) == 0
    assert "sig=" in capsys.readouterr().out
    assert main(["uri", "--upi-id", "bad", "--name", "n"]) == 2


# ---- session (expiring) QR ------------------------------------------------


def test_session_qr_expires():
    sq = create_session_qr("https://x.test/pay", pay(), SECRET, expires_in=300, now=1000)
    assert sq.expires_at == 1300 and sq.png().startswith(b"\x89PNG") and "<svg" in sq.svg()
    payment, exp = verify_payment_link(sq.url, SECRET, now=1200)
    assert payment == pay() and exp == 1300
    with pytest.raises(LinkExpiredError):
        verify_payment_link(sq.url, SECRET, now=1301)
    with pytest.raises(ValueError):
        create_session_qr("https://x.test/pay", pay(), SECRET, expires_in=0)


def test_session_qr_server_and_page(tmp_path):
    sq = create_session_qr("https://x.test/pay", pay(), SECRET, expires_in=300)
    status, _, body = call(create_app(SECRET), "/pay", urlparse(sq.url).query)
    assert status.startswith("200") and b'id="timer"' in body and b"Session ends in" in body
    old = create_session_qr("https://x.test/pay", pay(), SECRET, expires_in=1, now=1)
    assert call(create_app(SECRET), "/pay", urlparse(old.url).query)[0].startswith("410")
    sq.save(tmp_path / "s.png")
    assert (tmp_path / "s.png").exists()
    assert 'id="timer"' not in render_payment_page(pay())


def test_cli_session_qr(tmp_path, capsys):
    rc = main(
        [
            "session-qr",
            "--upi-id",
            "shop@okhdfcbank",
            "--name",
            "My Shop",
            "--amount",
            "50",
            "--base-url",
            "https://x.test/pay",
            "--secret",
            SECRET,
            "--expires-in",
            "120",
            "-o",
            str(tmp_path / "s.png"),
        ]
    )
    assert rc == 0 and (tmp_path / "s.png").exists() and "valid for 120s" in capsys.readouterr().out
