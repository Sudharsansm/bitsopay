"""Dynamic QR Code: a fresh, fixed-amount QR for every single payment."""

import pytest

from bitsopay import SignatureError, UPIPayment, ValidationError, create_dynamic_qr, verify_payment_link
from bitsopay.session import DynamicQR
from conftest import SECRET, FakeClock

BASE = "https://pay.example.com/pay"


def pay(**kw):
    kw.setdefault("upi_id", "shop@okhdfcbank")
    kw.setdefault("payee_name", "My Shop")
    kw.setdefault("amount", 499)
    return UPIPayment(**kw)


# ---- each call mints a brand-new QR, even for the "same" payment -----------------


def test_each_call_is_a_new_qr():
    a = create_dynamic_qr(BASE, pay(), SECRET, now=1000)
    b = create_dynamic_qr(BASE, pay(), SECRET, now=1000)
    assert a.url != b.url and a.reference != b.reference
    assert isinstance(a, DynamicQR)


def test_reference_is_generated_like_the_demo_unless_already_set():
    qr = create_dynamic_qr(BASE, pay(), SECRET)
    assert qr.reference and qr.reference.startswith("BP")
    fixed = create_dynamic_qr(BASE, pay(reference="ORDER-1042"), SECRET)
    assert fixed.reference == "ORDER-1042"


def test_default_expiry_is_five_minutes():
    qr = create_dynamic_qr(BASE, pay(), SECRET, now=1000)
    assert qr.issued_at == 1000 and qr.expires_at == 1300


def test_custom_expiry_and_seconds_left():
    far_future = 4_000_000_000  # year 2096: safely after "now" but still "not expired"
    qr = create_dynamic_qr(BASE, pay(), SECRET, expires_in=60, now=far_future)
    assert qr.expires_at == far_future + 60
    assert not qr.expired and qr.seconds_left > 0


def test_expires_in_must_be_positive():
    with pytest.raises(ValidationError):
        create_dynamic_qr(BASE, pay(), SECRET, expires_in=0)
    with pytest.raises(ValidationError):
        create_dynamic_qr(BASE, pay(), SECRET, expires_in=-5)


def test_amount_is_required():
    with pytest.raises(ValidationError):
        create_dynamic_qr(BASE, pay(amount=None), SECRET)


def test_qr_outputs(tmp_path):
    qr = create_dynamic_qr(BASE, pay(), SECRET)
    assert qr.png().startswith(b"\x89PNG") and "<svg" in qr.svg()
    saved = qr.save(tmp_path / "order.png")
    assert saved.exists() and saved.read_bytes() == qr.png()


def test_the_link_verifies_like_any_other_signed_link():
    qr = create_dynamic_qr(BASE, pay(note="Order #1"), SECRET, expires_in=300, now=1000)
    payment, expires_at = verify_payment_link(qr.url, SECRET, now=1200)
    assert payment.amount == 499 and payment.note == "Order #1" and expires_at == 1300
    with pytest.raises(SignatureError):
        verify_payment_link(qr.url, "another-secret-long-enough", now=1200)


def test_clock_can_be_overridden_for_tests():
    clock = FakeClock(5000)
    qr = create_dynamic_qr(BASE, pay(), SECRET, expires_in=10, now=clock())
    assert qr.expires_at == 5010
