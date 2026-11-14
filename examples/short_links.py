"""Short payment links with history, stored in SQLite."""

from bitsopay import PaymentLinks, SQLiteStore

with SQLiteStore("payments.db") as store:
    links = PaymentLinks(store, "https://pay.example.com")
    link = links.create("shop@okhdfcbank", "My Shop", 499, note="Order 1042", expires_in=3600)
    print("send this to the customer:", link.url)
    link.save("link-qr.png")

    # ... after you confirmed the money arrived in your bank / UPI app:
    links.mark_paid(link.reference, note="UTR 123456789012")
    for record in links.history(status="paid"):
        print(record.reference, record.amount, record.status)
