"""Create a UPI QR code from a UPI ID and amount."""

from bitsopay import UPIPayment, new_reference, save_qr

pay = UPIPayment(
    upi_id="shop@okhdfcbank",
    payee_name="My Shop",
    amount=499,
    note="Order 1042",
    reference=new_reference(),
)
print(pay.uri)
print("saved", save_qr(pay, "order-1042.png"))
