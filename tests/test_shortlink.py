import io
import json

import pytest

from bitsopay import (
    InvalidStateError,
    MemoryStore,
    NotFoundError,
    PaymentLinks,
    SQLiteStore,
    ValidationError,
)
from bitsopay.cli import main
from bitsopay.server import create_app

TOKEN = "admin-token-long-enough"


class Clock:
    def __init__(self, t=1_000_000):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(params=["memory", "sqlite"])
def links(request):
    store = MemoryStore() if request.param == "memory" else SQLiteStore()
    clock = Clock()
    pl = PaymentLinks(store, "https://pay.example.com", clock=clock)
    pl.clock_obj = clock
    yield pl
    if isinstance(store, SQLiteStore):
        store.close()


def make(links, **kw):
    kw.setdefault("amount", 499)
    return links.create("shop@okhdfcbank", "My Shop", **kw)


# ---- manager ---------------------------------------------------------------


def test_link_contains_only_reference(links):
    link = make(links, note="Order 7")
    assert link.url == f"https://pay.example.com/p/{link.reference}"
    assert link.reference.startswith("BP") and len(link.reference) == 18
    for secret_bit in ("shop", "okhdfcbank", "499", "Order", "My%20Shop"):
        assert secret_bit not in link.url


def test_references_unique(links):
    refs = {make(links).reference for _ in range(200)}
    assert len(refs) == 200


def test_record_matches_upi_reference(links):
    link = make(links)
    pay = links.get(link.reference).to_payment()
    assert pay.reference == link.reference and f"tr={link.reference}" in pay.uri
    assert str(pay.amount) == "499.00"


def test_validation_and_expiry_args(links):
    with pytest.raises(ValidationError):
        links.create("bad", "n", 5)
    with pytest.raises(ValidationError):
        make(links, expires_in=0)
    with pytest.raises(ValidationError):
        PaymentLinks(MemoryStore()).create("abc@okbank", "n", 5)  # no base_url anywhere


def test_lifecycle_and_history(links):
    a, b, c = make(links), make(links, amount=None), make(links, expires_in=60)
    links.mark_paid(a.reference, "UTR123")
    links.cancel(b.reference)
    links.clock_obj.t += 61
    assert links.status_of(links.get(a.reference)) == "paid"
    assert links.status_of(links.get(b.reference)) == "cancelled"
    assert links.status_of(links.get(c.reference)) == "expired"
    assert [r.reference for r in links.history("paid")] == [a.reference]
    assert [r.reference for r in links.history("expired")] == [c.reference]
    assert [r.reference for r in links.history("pending")] == []
    assert len(links.history()) == 3 and len(links.history(limit=2)) == 2
    assert links.get(a.reference).paid_note == "UTR123"
    with pytest.raises(ValidationError):
        links.history("bogus")


def test_state_rules(links):
    a = make(links)
    links.mark_paid(a.reference)
    assert links.mark_paid(a.reference).status == "paid"  # idempotent
    with pytest.raises(InvalidStateError):
        links.cancel(a.reference)
    b = make(links)
    links.cancel(b.reference)
    assert links.cancel(b.reference).status == "cancelled"
    with pytest.raises(InvalidStateError):
        links.mark_paid(b.reference)
    with pytest.raises(NotFoundError):
        links.mark_paid("BPDOESNOTEXIST000")


def test_paid_after_expiry_allowed(links):
    a = make(links, expires_in=10)
    links.clock_obj.t += 100
    assert links.mark_paid(a.reference).status == "paid"


def test_qr_encodes_short_url(links, tmp_path):
    link = make(links)
    assert link.png().startswith(b"\x89PNG") and "<svg" in link.svg()
    link.save(tmp_path / "x.png")
    assert (tmp_path / "x.png").exists() and link.seconds_left == 86400


def test_sqlite_persists(tmp_path):
    path = tmp_path / "p.db"
    with SQLiteStore(path) as first:
        ref = PaymentLinks(first, "https://x.test").create("abc@okbank", "N", 10).reference
    with SQLiteStore(path) as second:
        record = PaymentLinks(second, "https://x.test").get(ref)
        assert record is not None and record.amount is not None


# ---- server ------------------------------------------------------------------


def call(app, path, query="", method="GET", body=None, token=None):
    out = {}

    def start(status, headers):
        out["status"], out["headers"] = status, dict(headers)

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
    data = b"".join(app(env, start))
    return out["status"], out["headers"], data


@pytest.fixture
def served():
    clock = Clock()
    app = create_app(store=MemoryStore(), admin_token=TOKEN, base_url="https://pay.example.com", clock=clock)
    return app, clock


def api_create(app, **kw):
    body = {"upi_id": "shop@okhdfcbank", "payee_name": "My Shop", "amount": 250, "note": "Order 9"}
    body.update(kw)
    status, _, data = call(app, "/api/payments", method="POST", body=body, token=TOKEN)
    return status, json.loads(data)


def test_public_page_flow(served):
    app, _ = served
    status, out = api_create(app, expires_in=300)
    assert status.startswith("201") and out["url"] == f"https://pay.example.com/p/{out['reference']}"
    ref = out["reference"]
    s, h, body = call(app, f"/p/{ref}")
    assert s.startswith("200") and b"My Shop" in body and b"250.00" in body and f"tr={ref}".encode() in body
    assert h["Cache-Control"] == "no-store"
    assert call(app, f"/p/{ref}/qr.png")[2].startswith(b"\x89PNG")
    assert b"<svg" in call(app, f"/p/{ref}/qr.svg")[2]
    st = json.loads(call(app, f"/p/{ref}/status")[2])
    assert st == {"reference": ref, "status": "pending", "expires_at": out["expires_at"]}
    assert call(app, "/api/payments/" + ref, token=TOKEN)[2].count(b'"views": 1') == 1


def test_expiry_cancel_paid_pages(served):
    app, clock = served
    ref = api_create(app, expires_in=60)[1]["reference"]
    clock.t += 61
    assert call(app, f"/p/{ref}")[0].startswith("410")
    assert call(app, f"/p/{ref}/qr.png")[0].startswith("410")
    assert json.loads(call(app, f"/p/{ref}/status")[2])["status"] == "expired"
    ref2 = api_create(app)[1]["reference"]
    assert call(app, f"/api/payments/{ref2}/cancel", method="POST", token=TOKEN)[0].startswith("200")
    assert call(app, f"/p/{ref2}")[0].startswith("410")
    ref3 = api_create(app)[1]["reference"]
    s, _, b = call(app, f"/api/payments/{ref3}/paid", method="POST", body={"note": "UTR9"}, token=TOKEN)
    assert s.startswith("200") and json.loads(b)["paid_note"] == "UTR9"
    s, _, b = call(app, f"/p/{ref3}")
    assert s.startswith("200") and b"Payment received" in b and b"250.00" not in b
    assert call(app, f"/api/payments/{ref3}/cancel", method="POST", token=TOKEN)[0].startswith("409")


def test_public_routes_hide_data_and_reject_junk(served):
    app, _ = served
    ref = api_create(app)[1]["reference"]
    assert b"shop@" not in call(app, f"/p/{ref}/status")[2]
    assert call(app, "/p/BPNOTEXIST0000000")[0].startswith("404")
    assert call(app, "/p/bad!ref")[0].startswith("404")
    assert call(app, f"/p/{ref}/other")[0].startswith("404")
    assert call(app, f"/p/{ref}", method="POST")[0].startswith("405")


def test_admin_auth_and_errors(served):
    app, _ = served
    assert call(app, "/api/payments")[0].startswith("401")
    assert call(app, "/api/payments", token="wrong-token-wrong-token")[0].startswith("401")
    assert api_create(app, amount=-1)[0].startswith("400")
    assert api_create(app, upi_id="nope")[0].startswith("400")
    s, _, _ = call(app, "/api/payments", method="POST", token=TOKEN)
    assert s.startswith("400")
    assert call(app, "/api/payments/BPNOTEXIST0000000", token=TOKEN)[0].startswith("404")
    s, _, b = call(app, "/api/payments", token=TOKEN, query="status=pending&limit=5")
    assert s.startswith("200") and json.loads(b)["payments"] == []


def test_admin_history_and_disabled_without_token():
    app = create_app(store=MemoryStore(), base_url="https://p.test")
    assert call(app, "/api/payments", token=TOKEN)[0].startswith("404")
    app2 = create_app(store=MemoryStore(), admin_token=TOKEN)
    ref = api_create(app2)[1]
    assert ref["url"].startswith("https://pay.test/p/")  # derived from Host header
    rows = json.loads(call(app2, "/api/payments", token=TOKEN)[2])["payments"]
    assert rows[0]["reference"] == ref["reference"]


def test_short_admin_token_rejected():
    with pytest.raises(ValueError):
        create_app(store=MemoryStore(), admin_token="short")


# ---- cli -----------------------------------------------------------------------


def test_cli_short_link_flow(tmp_path, capsys):
    db = str(tmp_path / "p.db")
    assert (
        main(
            [
                "create-link",
                "--db",
                db,
                "--base-url",
                "https://pay.example.com",
                "--upi-id",
                "shop@okhdfcbank",
                "--name",
                "My Shop",
                "--amount",
                "75",
                "-o",
                str(tmp_path / "l.png"),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    ref = next(ln.split()[1] for ln in out.splitlines() if ln.startswith("reference:"))
    assert f"https://pay.example.com/p/{ref}" in out and (tmp_path / "l.png").exists()
    assert main(["history", "--db", db]) == 0 and ref in capsys.readouterr().out
    assert main(["mark-paid", ref, "--db", db, "--note", "UTR1"]) == 0
    assert main(["show", ref, "--db", db]) == 0 and "paid" in capsys.readouterr().out
    assert main(["history", "--db", db, "--status", "paid"]) == 0 and ref in capsys.readouterr().out
    assert main(["cancel", ref, "--db", db]) == 2  # paid cannot be cancelled
    assert main(["show", "BPNOPE", "--db", db]) == 2
    assert main(["history"]) == 2  # no --db
