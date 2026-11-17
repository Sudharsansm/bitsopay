"""Static QR Code: one reusable QR for your UPI id, printed once and reused for many payments."""

import os

from bitsopay import StaticSession

# export BITSOPAY_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
SECRET = os.environ["BITSOPAY_SECRET"]

merchant = StaticSession("shop@okhdfcbank", "My Shop", SECRET, "https://pay.example.com/pay", window=300)

qr = merchant.create()
print(qr.upi_id, qr.reference, qr.url, "expires in", qr.seconds_left, "s")
qr.save("counter-qr.png")  # print this once and leave it on the counter

# Calling create() again, while it's still valid, returns the identical QR - that's
# what lets you print it once instead of regenerating it for every payment.
same = merchant.create()
assert same.url == qr.url

# Switch the merchant's UPI id (e.g. you moved banks) and you get a brand-new QR
# immediately - the old one can never be reused for the new UPI id.
rotated = merchant.create(upi_id="newshop@okaxis")
assert rotated.url != qr.url
print("rotated:", rotated.upi_id, rotated.url)

# After the window (5 minutes here) lapses, the next create() call mints a fresh QR
# automatically - no need to track expiry yourself.
