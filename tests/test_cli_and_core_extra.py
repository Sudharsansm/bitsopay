import subprocess
import sys
import time

import pytest

import bitsopay
from bitsopay import (
    MemoryStore,
    PaymentLinks,
    SQLiteStore,
    StatelessLinks,
    UPIPayment,
    ValidationError,
    create_payment_link,
    create_session_qr,
    verify_payment_link,
)
from bitsopay.cli import main
from bitsopay.qr import save_text_qr
from bitsopay.validators import validate_reference, validate_text, validate_vpa
from conftest import SECRET

BASE = ["--upi-id", "shop@okhdfcbank", "--name", "My Shop", "--amount", "10"]


def test_module_entry_point_and_version():
    out = subprocess.run([sys.executable, "-m", "bitsopay", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == f"bitsopay {bitsopay.__version__}"


def test_cli_stateless_commands(tmp_path, capsys):
    assert main(["uri", *BASE]) == 0
    assert capsys.readouterr().out.startswith("upi://pay?pa=shop@okhdfcbank")
    assert main(["qr", *BASE, "-o", str(tmp_path / "a.svg")]) == 0
    assert main(["page", *BASE, "-o", str(tmp_path / "a.html")]) == 0
    assert "My Shop" in (tmp_path / "a.html").read_text()
    args = ["--base-url", "https://pay.example.com/pay", "--secret", SECRET]
    assert main(["link", *BASE, *args, "--expires-in", "0"]) == 0
    assert "sig=" in capsys.readouterr().out
    assert main(["session-qr", *BASE, *args, "-o", str(tmp_path / "s.png")]) == 0
    assert main(["quick-link", *BASE[:4], "--base-url", "https://pay.example.com", "--secret", SECRET]) == 0


def test_cli_errors_return_exit_code_2(capsys, monkeypatch):
    monkeypatch.delenv("BITSOPAY_SECRET", raising=False)
    assert main(["link", *BASE, "--base-url", "https://x.test/pay"]) == 2
    assert "BITSOPAY_SECRET" in capsys.readouterr().err
    assert main(["uri", "--upi-id", "bad", "--name", "N"]) == 2


def test_cli_history_empty_and_open_amount(tmp_path, capsys):
    db = str(tmp_path / "h.db")
    assert main(["history", "--db", db]) == 0
    assert "No payments" in capsys.readouterr().out
    main(["create-link", "--db", db, "--base-url", "https://p.test", "--upi-id", "ab@okbank", "--name", "N"])
    capsys.readouterr()
    assert main(["history", "--db", db]) == 0
    assert "open" in capsys.readouterr().out


def test_cli_serve_wires_up_the_server(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr("bitsopay.server.serve", lambda *a, **k: captured.update(args=a, kwargs=k))
    db = str(tmp_path / "s.db")
    assert main(["serve", "--db", db, "--secret", SECRET, "--upi-id", "ab@okbank", "--name", "N", "--port", "9"]) == 0
    assert captured["args"][2] == 9 and captured["kwargs"]["stateless"] is not None
    assert main(["serve"]) == 2  # nothing configured


def test_store_edges():
    store = MemoryStore()
    assert store.list(status="pending", now=time.time()) == []
    with SQLiteStore() as sq:
        assert sq.list(status="bogus") == []
        sq.record_view("missing")  # no-op
    links = PaymentLinks(MemoryStore(), "https://p.test")
    with pytest.raises(ValidationError):
        links.history(status="bogus")
    assert links.create("ab@okbank", "N", 5, expires_in=None).seconds_left is None
    with pytest.raises(ValidationError):
        PaymentLinks(MemoryStore()).url_for("BPX")  # no base_url


def test_validators_reject_bad_types():
    with pytest.raises(ValidationError):
        validate_vpa(123)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        validate_text(5, "note", 10)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        validate_reference("bad ref!")
    assert validate_text("   ", "note", 10) is None


def test_payment_model_edges():
    with pytest.raises(ValidationError):
        UPIPayment(upi_id="ab@okbank", payee_name="   ", amount=1)
    with pytest.raises(ValidationError):
        UPIPayment(upi_id="ab@okbank", payee_name="N", currency="USD")
    assert UPIPayment(upi_id="ab@okbank", payee_name="N", merchant_code="5411").uri.endswith("mc=5411")


def test_signed_link_rejects_bad_expiry_and_url():
    pay = UPIPayment(upi_id="ab@okbank", payee_name="N", amount=1)
    with pytest.raises(ValidationError):
        create_payment_link("ftp://x", pay, SECRET)
    url = create_payment_link("https://x.test/pay?lang=en", pay, SECRET, expires_in=None)
    assert verify_payment_link(url, SECRET)[1] is None


def test_session_qr_properties():
    pay = UPIPayment(upi_id="ab@okbank", payee_name="N", amount=1)
    sq = create_session_qr("https://x.test/pay", pay, SECRET, expires_in=60)
    assert 0 < sq.seconds_left <= 60 and not sq.expired
    assert sq.svg().startswith("<svg") and sq.png().startswith(b"\x89PNG")
    with pytest.raises(ValueError, match="positive"):
        create_session_qr("https://x.test/pay", pay, SECRET, expires_in=0)


def test_qr_helpers_validate_arguments(tmp_path):
    with pytest.raises(ValueError, match=r"\.png or \.svg"):
        save_text_qr("hello", tmp_path / "x.gif")
    pay = UPIPayment(upi_id="ab@okbank", payee_name="N")
    with pytest.raises(ValueError, match="error must be"):
        bitsopay.qr_png(pay, error="Z")
    assert bitsopay.qr_data_uri(pay).startswith("data:image/png;base64,")
    with pytest.raises(ValueError, match="Unknown app"):
        bitsopay.build_app_uri(pay, "nope")


def test_stateless_edges(clock):
    links = StatelessLinks("shop@okhdfcbank", "My Shop", SECRET, "https://p.test", clock=clock, prefix="AB")
    link = links.create(None, expires_in=None)
    assert link.reference.startswith("AB") and link.seconds_left is None
    payment, exp = links.decode(link.reference.lower())
    assert payment.amount is None and exp is None
    with pytest.raises(ValidationError):
        StatelessLinks("shop@okhdfcbank", "My Shop", SECRET, prefix="toolong1")
    with pytest.raises(ValidationError):
        links.create(5, expires_in=2**40)
