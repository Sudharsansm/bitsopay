"""Dynamic QR Code: a fresh, fixed-amount QR for every single payment."""

import os

from bitsopay import UPIPayment, create_dynamic_qr

# export BITSOPAY_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# Use the same secret on your server, or the printed QR codes will be rejected.
SECRET = os.environ["BITSOPAY_SECRET"]
BASE_URL = "https://pay.example.com/pay"

# Each payment is its own UPIPayment with its own fixed amount.
order_1 = UPIPayment(upi_id="shop@okhdfcbank", payee_name="My Shop", amount=499, note="Order #1042")
qr_1 = create_dynamic_qr(BASE_URL, order_1, SECRET, expires_in=300)  # valid for 5 minutes
print(qr_1.reference, qr_1.url, "expires in", qr_1.seconds_left, "s")
qr_1.save("order-1042.png")

# The next payment needs its own, brand-new QR - calling create_dynamic_qr() again never
# reuses the previous one, even with identical inputs (a fresh reference is generated,
# just like the bundled demo's "Generate" button does).
order_2 = UPIPayment(upi_id="shop@okhdfcbank", payee_name="My Shop", amount=499, note="Order #1043")
qr_2 = create_dynamic_qr(BASE_URL, order_2, SECRET, expires_in=300)
print(qr_2.reference, qr_2.url)
assert qr_1.url != qr_2.url

# Serve the link with bitsopay.server (it's an ordinary signed payment link, so the
# existing /pay route verifies it), or check it yourself:
from bitsopay import verify_payment_link  # noqa: E402

payment, expires_at = verify_payment_link(qr_1.url, SECRET)
print("verified:", payment.amount, "expires at", expires_at)
