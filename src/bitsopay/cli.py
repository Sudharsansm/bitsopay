"""Command line interface.

``bitsopay qr|uri|link|session-qr|page``   stateless helpers
``bitsopay create-link|history|show|mark-paid|cancel``   short links + history (SQLite)
``bitsopay serve``   run the payment server
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import List, Optional

from . import __version__
from .exceptions import BitsoPayError
from .link import create_payment_link
from .models import UPIPayment
from .page import render_payment_page
from .qr import save_qr
from .session import create_session_qr
from .shortlink import PaymentLinks
from .stateless import StatelessLinks
from .store import SQLiteStore


def _add_payment_args(p: argparse.ArgumentParser, ref: bool = True) -> None:
    p.add_argument("--upi-id", required=True, help="Merchant UPI ID, e.g. shop@okhdfcbank")
    p.add_argument("--name", required=True, help="Payee / merchant name")
    p.add_argument("--amount", help="Amount in INR (omit for open amount)")
    p.add_argument("--note", help="Transaction note (max 80 chars)")
    if ref:
        p.add_argument("--ref", help="Transaction reference / order id")
    p.add_argument("--mcc", help="4-digit merchant category code")


def _payment(a: argparse.Namespace) -> UPIPayment:
    return UPIPayment(
        upi_id=a.upi_id,
        payee_name=a.name,
        amount=a.amount,
        note=a.note,
        reference=getattr(a, "ref", None),
        merchant_code=a.mcc,
    )


def _secret(a: argparse.Namespace) -> str:
    secret = a.secret or os.environ.get("BITSOPAY_SECRET")
    if not secret:
        raise BitsoPayError("Provide --secret or set BITSOPAY_SECRET")
    return secret


def _db_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", help="SQLite file (or $BITSOPAY_DB)")


def _links(a: argparse.Namespace, opened: List[SQLiteStore]) -> PaymentLinks:
    path = a.db or os.environ.get("BITSOPAY_DB")
    if not path:
        raise BitsoPayError("Provide --db or set BITSOPAY_DB")
    store = SQLiteStore(path)
    opened.append(store)  # closed by main() when the command finishes
    return PaymentLinks(store, getattr(a, "base_url", None) or os.environ.get("BITSOPAY_BASE_URL"))


def _fmt_time(ts: Optional[int]) -> str:
    return "-" if ts is None else datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bitsopay", description="UPI QR codes and payment links")
    parser.add_argument("--version", action="version", version=f"bitsopay {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    qr = sub.add_parser("qr", help="Write a QR code image (.png or .svg)")
    _add_payment_args(qr)
    qr.add_argument("-o", "--output", required=True)

    uri = sub.add_parser("uri", help="Print the upi:// deep link")
    _add_payment_args(uri)

    link = sub.add_parser("link", help="Create a signed https payment link (data in URL)")
    _add_payment_args(link)
    link.add_argument("--base-url", required=True, help="e.g. https://pay.example.com/pay")
    link.add_argument("--secret", help="Signing secret (or $BITSOPAY_SECRET)")
    link.add_argument("--expires-in", type=int, default=86400, help="Seconds until expiry (0 = never)")

    sess = sub.add_parser("session-qr", help="Write an expiring QR using a signed link")
    _add_payment_args(sess)
    sess.add_argument("--base-url", required=True, help="e.g. https://pay.example.com/pay")
    sess.add_argument("--secret", help="Signing secret (or $BITSOPAY_SECRET)")
    sess.add_argument("--expires-in", type=int, default=300, help="Session length in seconds (default 300)")
    sess.add_argument("-o", "--output", required=True)

    page = sub.add_parser("page", help="Write a standalone HTML payment page")
    _add_payment_args(page)
    page.add_argument("-o", "--output", required=True)

    # -- secure short links ------------------------------------------------
    cl = sub.add_parser("create-link", help="Create a secure short link (reference code only in URL)")
    _add_payment_args(cl, ref=False)
    _db_arg(cl)
    cl.add_argument("--base-url", help="Public server root, e.g. https://pay.example.com (or $BITSOPAY_BASE_URL)")
    cl.add_argument("--expires-in", type=int, default=86400, help="Seconds until expiry (0 = never)")
    cl.add_argument("-o", "--output", help="Also write a QR of the short link (.png / .svg)")

    ql = sub.add_parser("quick-link", help="Create a database-free short link (no storage needed)")
    ql.add_argument("--upi-id", required=True)
    ql.add_argument("--name", required=True)
    ql.add_argument("--amount", help="Amount in INR (omit for open amount)")
    ql.add_argument("--base-url", required=True, help="Public server root, e.g. https://pay.example.com")
    ql.add_argument("--secret", help="Signing secret (or $BITSOPAY_SECRET)")
    ql.add_argument("--expires-in", type=int, default=86400, help="Seconds until expiry (0 = never)")
    ql.add_argument("-o", "--output", help="Also write a QR of the link (.png / .svg)")

    hist = sub.add_parser("history", help="List payment history")
    _db_arg(hist)
    hist.add_argument("--status", choices=["pending", "paid", "cancelled", "expired"])
    hist.add_argument("--limit", type=int, default=20)

    show = sub.add_parser("show", help="Show one payment")
    _db_arg(show)
    show.add_argument("reference")

    paid = sub.add_parser("mark-paid", help="Mark a payment as paid after verifying it manually")
    _db_arg(paid)
    paid.add_argument("reference")
    paid.add_argument("--note", help="e.g. the UPI transaction id from your bank statement")

    cancel = sub.add_parser("cancel", help="Cancel a pending payment link")
    _db_arg(cancel)
    cancel.add_argument("reference")

    serve = sub.add_parser("serve", help="Run a dev server for payment links")
    serve.add_argument("--secret", help="Signing secret for legacy signed links (or $BITSOPAY_SECRET)")
    _db_arg(serve)
    serve.add_argument("--upi-id", help="Merchant UPI ID for database-free links (or $BITSOPAY_UPI_ID)")
    serve.add_argument("--name", help="Merchant name for database-free links (or $BITSOPAY_PAYEE_NAME)")
    serve.add_argument("--admin-token", help="Merchant API token (or $BITSOPAY_ADMIN_TOKEN)")
    serve.add_argument("--base-url", help="Public root URL (or $BITSOPAY_BASE_URL)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    opened: List[SQLiteStore] = []
    try:
        if args.cmd == "qr":
            print(save_qr(_payment(args), args.output))
        elif args.cmd == "uri":
            print(_payment(args).uri)
        elif args.cmd == "link":
            exp = args.expires_in or None
            print(create_payment_link(args.base_url, _payment(args), _secret(args), expires_in=exp))
        elif args.cmd == "session-qr":
            sq = create_session_qr(args.base_url, _payment(args), _secret(args), expires_in=args.expires_in)
            sq.save(args.output)
            print(f"{args.output}  (valid for {args.expires_in}s)\n{sq.url}")
        elif args.cmd == "page":
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(render_payment_page(_payment(args)))
            print(args.output)
        elif args.cmd == "create-link":
            links = _links(args, opened)
            new = links.create(
                args.upi_id,
                args.name,
                args.amount,
                note=args.note,
                merchant_code=args.mcc,
                expires_in=args.expires_in or None,
            )
            print(f"reference: {new.reference}\nurl:       {new.url}\nexpires:   {_fmt_time(new.expires_at)}")
            if args.output:
                print(f"qr:        {new.save(args.output)}")
        elif args.cmd == "quick-link":
            sl = StatelessLinks(args.upi_id, args.name, _secret(args), args.base_url).create(
                args.amount, expires_in=args.expires_in or None
            )
            print(f"reference: {sl.reference}\nurl:       {sl.url}\nexpires:   {_fmt_time(sl.expires_at)}")
            if args.output:
                print(f"qr:        {sl.save(args.output)}")
        elif args.cmd == "history":
            links = _links(args, opened)
            rows = links.history(args.status, args.limit)
            if not rows:
                print("No payments found.")
            now = links.clock()
            for r in rows:
                amt = "open" if r.amount is None else f"{r.amount:.2f}"
                print(
                    f"{r.reference}  {r.effective_status(now):<9}  {amt:>10}  {r.payee_name}  "
                    f"created {_fmt_time(r.created_at)}  views {r.views}"
                )
        elif args.cmd == "show":
            links = _links(args, opened)
            rec = links.get(args.reference)
            if rec is None:
                raise BitsoPayError(f"No payment with reference {args.reference}")
            for k, v in rec.to_dict(links.clock()).items():
                print(f"{k:<14} {v}")
        elif args.cmd == "mark-paid":
            rec = _links(args, opened).mark_paid(args.reference, args.note)
            print(f"{rec.reference} marked paid at {_fmt_time(rec.paid_at)}")
        elif args.cmd == "cancel":
            rec = _links(args, opened).cancel(args.reference)
            print(f"{rec.reference} cancelled")
        elif args.cmd == "serve":
            from .server import serve

            path = args.db or os.environ.get("BITSOPAY_DB")
            secret = args.secret or os.environ.get("BITSOPAY_SECRET")
            upi = args.upi_id or os.environ.get("BITSOPAY_UPI_ID")
            pname = args.name or os.environ.get("BITSOPAY_PAYEE_NAME")
            if not path and not secret:
                raise BitsoPayError("Provide --db (short links) and/or --secret (signed / database-free links)")
            stateless = StatelessLinks(upi, pname, secret) if (upi and pname and secret) else None
            store = SQLiteStore(path) if path else None
            if store is not None:
                opened.append(store)  # closed when the server stops
            serve(
                secret,
                args.host,
                args.port,
                store=store,
                admin_token=args.admin_token or os.environ.get("BITSOPAY_ADMIN_TOKEN"),
                base_url=args.base_url or os.environ.get("BITSOPAY_BASE_URL"),
                stateless=stateless,
            )
    except BitsoPayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        for opened_store in opened:
            opened_store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
