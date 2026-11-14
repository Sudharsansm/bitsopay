import io
import json
import re
from decimal import Decimal

import pytest

from bitsopay import LinkExpiredError, SignatureError, StatelessLinks, ValidationError
from bitsopay.cli import main
from bitsopay.server import create_app

SECRET = "stateless-secret-long-enough"
TOKEN = "admin-token-long-enough"


class Clock:
    def __init__(self, t=1_800_000_000):
        self.t = t

    def __call__(self):
        return self.t


def make(clock=None, **kw):
    return StatelessLinks("shop@okhdfcbank", "My Shop", SECRET, "https://pay.example.com", clock=clock or Clock(), **kw)


def test_id_format_and_no_data_in_url():
    link = make().create(499, expires_in=3600)
    assert re.fullmatch(r"BP[A-Z2-7]{31}", link.reference) and len(link.reference) <= 35
    assert link.url == f"https://pay.example.com/p/{link.reference}"
    for bit in ("shop", "okhdfcbank", "499", "My"):
        assert bit not in link.url


def test_roundtrip_and_reference_is_tr():
    sl = make()
    link = sl.create("499.50", expires_in=60)
    pay, exp = sl.decode(link.reference)
    assert pay.amount == Decimal("499.50") and pay.upi_id == "shop@okhdfcbank"
    assert pay.reference == link.reference and f"tr={link.reference}" in pay.uri
    assert exp == link.expires_at
    assert sl.decode(link.reference.lower())[0] == pay  # case-insensitive


def test_open_amount_and_never_expires():
    clock = Clock()
    sl = make(clock)
    link = sl.create(None, expires_in=None)
    pay, exp = sl.decode(link.reference)
    assert pay.amount is None and exp is None and link.seconds_left is None
    clock.t += 10**8
    sl.decode(link.reference)


def test_expiry():
    clock = Clock()
    sl = make(clock)
    link = sl.create(10, expires_in=60)
    clock.t += 59
    sl.decode(link.reference)
    clock.t += 2
    with pytest.raises(LinkExpiredError):
        sl.decode(link.reference)


def test_unique_and_amount_hidden():
    sl = make()
    ids = [sl.create(100, expires_in=3600).reference for _ in range(300)]
    assert len(set(ids)) == 300
    # same amount + expiry must not produce a common ciphertext block
    bodies = {i[2 + 5 : 2 + 18] for i in ids}
    assert len(bodies) > 290


def test_every_character_is_protected():
    sl = make()
    ref = sl.create(250, expires_in=3600).reference
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    bad = 0
    for i in range(2, len(ref)):
        flipped = ref[:i] + alphabet[(alphabet.index(ref[i]) + 1) % 32] + ref[i + 1 :]
        try:
            sl.decode(flipped)
        except SignatureError:
            bad += 1
    assert bad == len(ref) - 2


def test_wrong_secret_wrong_upi_and_garbage():
    ref = make().create(5, expires_in=60).reference
    with pytest.raises(SignatureError):
        StatelessLinks("shop@okhdfcbank", "My Shop", "another-secret-long-enough", clock=Clock()).decode(ref)
    with pytest.raises(SignatureError):
        StatelessLinks("other@okhdfcbank", "My Shop", SECRET, clock=Clock()).decode(ref)
    for junk in ("", "BP", "XX" + ref[2:], ref[:-1], ref + "A", "BP" + "!" * 31):
        with pytest.raises(SignatureError):
            make().decode(junk)


def test_validation():
    sl = make()
    for bad in (0, -1, "abc", 50_000_000):
        with pytest.raises(ValidationError):
            sl.create(bad)
    with pytest.raises(ValidationError):
        sl.create(5, expires_in=0)
    with pytest.raises(ValidationError):
        StatelessLinks("bad", "n", SECRET)
    with pytest.raises(ValidationError):
        StatelessLinks("shop@okhdfcbank", "n", "short")
    with pytest.raises(ValidationError):
        StatelessLinks("shop@okhdfcbank", "n", SECRET, prefix="bp")
    with pytest.raises(ValidationError):
        StatelessLinks("shop@okhdfcbank", "n", SECRET).create(5)  # no base_url


def test_qr_of_link(tmp_path):
    link = make().create(5)
    assert link.png().startswith(b"\x89PNG") and "<svg" in link.svg()
    link.save(tmp_path / "q.png")
    assert link.seconds_left == 86400


# ---- server (no database) -----------------------------------------------------


def call(app, path, method="GET", body=None, token=None, query=""):
    out = {}

    def start(status, headers):
        out["status"] = status

    raw = json.dumps(body).encode() if body is not None else b""
    env = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "wsgi.input": io.BytesIO(raw),
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.url_scheme": "https",
        "HTTP_HOST": "pay.test",
    }
    if token:
        env["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return (out.setdefault("status", None) and None) or (b"".join(app(env, start)), out["status"])


@pytest.fixture
def served():
    clock = Clock()
    app = create_app(stateless=make(clock), admin_token=TOKEN, base_url="https://pay.example.com", clock=clock)
    return app, clock


def test_server_without_database(served):
    app, clock = served
    body, status = call(app, "/api/payments", "POST", {"amount": 321, "expires_in": 120}, TOKEN)
    assert status.startswith("201")
    out = json.loads(body)
    ref = out["reference"]
    assert out["url"] == f"https://pay.example.com/p/{ref}"
    page, status = call(app, f"/p/{ref}")
    assert status.startswith("200") and b"My Shop" in page and b"321.00" in page and f"tr={ref}".encode() in page
    assert call(app, f"/p/{ref}/qr.png")[0].startswith(b"\x89PNG")
    assert b"<svg" in call(app, f"/p/{ref}/qr.svg")[0]
    st = json.loads(call(app, f"/p/{ref}/status")[0])
    assert st["status"] == "pending" and b"shop@" not in call(app, f"/p/{ref}/status")[0]
    clock.t += 121
    assert call(app, f"/p/{ref}")[1].startswith("410")
    assert call(app, f"/p/{ref}/qr.png")[1].startswith("410")
    assert json.loads(call(app, f"/p/{ref}/status")[0])["status"] == "expired"


def test_server_tamper_and_admin_limits(served):
    app, _ = served
    ref = json.loads(call(app, "/api/payments", "POST", {"amount": 5}, TOKEN)[0])["reference"]
    flipped = ref[:-1] + ("A" if ref[-1] != "A" else "B")
    assert call(app, f"/p/{flipped}")[1].startswith("404")
    assert call(app, "/p/BPNOTAVALIDID0000000000000000000")[1].startswith("404")
    assert call(app, "/api/payments", "POST", {"amount": 5})[1].startswith("401")
    assert call(app, "/api/payments", token=TOKEN)[1].startswith("501")  # history needs a store
    assert call(app, f"/api/payments/{ref}/paid", "POST", token=TOKEN)[1].startswith("501")
    assert call(app, "/api/payments", "POST", {"amount": -3}, TOKEN)[1].startswith("400")


def test_env_configuration(monkeypatch):
    monkeypatch.setenv("BITSOPAY_SECRET", SECRET)
    monkeypatch.setenv("BITSOPAY_UPI_ID", "shop@okhdfcbank")
    monkeypatch.setenv("BITSOPAY_PAYEE_NAME", "My Shop")
    monkeypatch.setenv("BITSOPAY_ADMIN_TOKEN", TOKEN)
    app = create_app()
    out = json.loads(call(app, "/api/payments", "POST", {"amount": 9}, TOKEN)[0])
    assert call(app, "/p/" + out["reference"])[1].startswith("200")


def test_store_and_stateless_together():
    from bitsopay import MemoryStore

    clock = Clock()
    app = create_app(
        store=MemoryStore(), stateless=make(clock), admin_token=TOKEN, base_url="https://pay.example.com", clock=clock
    )
    db_ref = json.loads(
        call(app, "/api/payments", "POST", {"upi_id": "shop@okhdfcbank", "payee_name": "My Shop", "amount": 7}, TOKEN)[
            0
        ]
    )["reference"]
    sl_ref = make(clock).create(8).reference
    assert call(app, f"/p/{db_ref}")[1].startswith("200") and call(app, f"/p/{sl_ref}")[1].startswith("200")


def test_cli_quick_link(tmp_path, capsys):
    rc = main(
        [
            "quick-link",
            "--upi-id",
            "shop@okhdfcbank",
            "--name",
            "My Shop",
            "--amount",
            "75",
            "--base-url",
            "https://pay.example.com",
            "--secret",
            SECRET,
            "-o",
            str(tmp_path / "q.png"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "https://pay.example.com/p/BP" in out and (tmp_path / "q.png").exists()
