# Demo upgrade notes

`bitsopay_demo.py` was upgraded on top of the existing `bitsopay` package
(no changes were needed inside `src/bitsopay/` — the features used here,
`PaymentLinks` and `SQLiteStore`, already shipped in the library; the old
demo simply wasn't using them).

## What's new

1. **Circular brand badge on the QR.** The Bitsopay logo is embedded as a
   base64 PNG and rendered as a small circular badge centered on the
   generated UPI QR code (the same visual pattern real UPI apps use), plus
   a round logo in the header.

2. **Short, secure share link.** Generating a QR now also creates a
   payment link via `PaymentLinks(SQLiteStore("bitsopay_demo.db"), BASE_URL)`.
   The link looks like:

   ```
   http://127.0.0.1:8000/p/BPB7ACF846F03D46D4
   ```

   - It carries **only an unguessable reference** — the UPI ID, merchant
     name and amount are never in the URL; they live in
     `bitsopay_demo.db` on the server.
   - It **self-expires** after 30 minutes (`LINK_EXPIRES_IN`).
   - A "Copy" button and a live "expires in N min" label sit under the QR.

3. **The link actually resolves.** A new `GET /p/<ref>` route looks the
   reference up in the store and renders a minimal payment page (amount,
   merchant, QR, "Open UPI app"), or a clear expired/cancelled/not-found
   state.

## Running it

```
pip install -e .          # from the project root, installs the local bitsopay package
python bitsopay_demo.py
```

Open http://127.0.0.1:8000. Each run creates/reuses `bitsopay_demo.db`
next to the script; delete that file to reset the demo's history.
