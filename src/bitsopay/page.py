"""Self-contained HTML payment page (QR for desktop, app buttons for mobile)."""

from __future__ import annotations

from html import escape
from typing import Optional

from .models import UPIPayment
from .qr import qr_data_uri
from .upi import APP_SCHEMES, build_app_uri

_APP_LABELS = {"gpay": "Google Pay", "phonepe": "PhonePe", "paytm": "Paytm"}

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>Pay {payee}</title>
<style>
  :root {{ color-scheme: light dark; --fg:#111827; --muted:#6b7280; --bg:#f3f4f6; --card:#fff; --accent:#4f46e5; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --fg:#f9fafb; --muted:#9ca3af; --bg:#111827; --card:#1f2937; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:16px;
         font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background:var(--bg); color:var(--fg); }}
  .card {{ width:100%; max-width:380px; background:var(--card); border-radius:16px; padding:24px; text-align:center;
          box-shadow:0 8px 30px rgba(0,0,0,.12); }}
  .payee {{ font-size:14px; color:var(--muted); margin:0; }}
  .name {{ font-size:20px; font-weight:600; margin:2px 0 12px; word-break:break-word; }}
  .amount {{ font-size:36px; font-weight:700; margin:4px 0 2px; }}
  .note {{ color:var(--muted); font-size:14px; margin:0 0 16px; word-break:break-word; }}
  .qr {{ width:240px; max-width:100%; height:auto; border-radius:8px; background:#fff; padding:8px; }}
  .btn {{ display:block; margin:10px 0 0; padding:14px; border-radius:12px; text-decoration:none; font-weight:600;
         background:var(--accent); color:#fff; }}
  .btn.alt {{ background:transparent; color:var(--accent); border:1px solid var(--accent); }}
  .upi {{ font-size:13px; color:var(--muted); margin-top:16px; word-break:break-all; }}
  .hint {{ font-size:12px; color:var(--muted); margin-top:12px; }}
  .timer {{ font-size:13px; color:var(--muted); margin:0 0 12px; }}
  .expired .pay {{ display:none; }}
  .expired-msg {{ display:none; color:#dc2626; font-weight:600; margin:16px 0; }}
  .expired .expired-msg {{ display:block; }}
</style>
</head>
<body>
<main class="card" id="card">
  <p class="payee">Pay to</p>
  <h1 class="name">{payee}</h1>
  <div class="amount">{amount}</div>
  {note}
  {timer}
  <div class="pay">
  <img class="qr" src="{qr}" alt="UPI QR code for {payee}" width="240" height="240">
  <a class="btn" href="{uri}">Pay with any UPI app</a>
  {app_buttons}
  <div class="upi">UPI ID: {upi_id}</div>
  </div>
  <div class="expired-msg">This payment session has ended. Please request a new link.</div>
  {ref}
  <div class="hint">Scan the QR with any UPI app, or tap a button on your phone.</div>
</main>
{script}
</body>
</html>
"""


_SCRIPT = """<script>
(function(){{
  var end = {exp} * 1000, card = document.getElementById("card"), t = document.getElementById("timer");
  function tick(){{
    var left = Math.floor((end - Date.now()) / 1000);
    if (left <= 0) {{ card.className += " expired"; if (t) t.textContent = "Session ended"; return; }}
    if (t) t.textContent = "Session ends in " + Math.floor(left/60) + ":" + ("0"+(left%60)).slice(-2);
    setTimeout(tick, 1000);
  }}
  tick();
}})();
</script>"""


def render_payment_page(payment: UPIPayment, expires_at: Optional[int] = None) -> str:
    """Return a complete, escaped HTML page for ``payment``.

    If ``expires_at`` (unix seconds) is given, the page shows a countdown and hides the
    QR and pay buttons when the session ends.
    """
    amount = f"&#8377;{payment.amount:,.2f}" if payment.amount is not None else "Enter amount in app"
    apps = "\n  ".join(
        f'<a class="btn alt" href="{escape(build_app_uri(payment, app), quote=True)}">{escape(_APP_LABELS[app])}</a>'
        for app in APP_SCHEMES
    )
    return _TEMPLATE.format(
        payee=escape(payment.payee_name),
        amount=amount,
        note=f'<p class="note">{escape(payment.note)}</p>' if payment.note else "",
        qr=qr_data_uri(payment),
        uri=escape(payment.uri, quote=True),
        app_buttons=apps,
        upi_id=escape(payment.upi_id),
        timer='<p class="timer" id="timer"></p>' if expires_at is not None else "",
        script=_SCRIPT.format(exp=int(expires_at)) if expires_at is not None else "",
        ref=f'<div class="upi">Ref: {escape(payment.reference)}</div>' if payment.reference else "",
    )


_MESSAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:16px;
         font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background:#f3f4f6; color:#111827; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#111827; color:#f9fafb; }} .card {{ background:#1f2937 !important; }} }}
  .card {{ max-width:380px; width:100%; background:#fff; border-radius:16px; padding:28px; text-align:center;
          box-shadow:0 8px 30px rgba(0,0,0,.12); }}
  h1 {{ font-size:20px; margin:0 0 8px; }} p {{ margin:6px 0; color:#6b7280; }}
</style></head>
<body><main class="card"><h1>{title}</h1><p>{message}</p>{ref}</main></body></html>
"""


def render_message_page(title: str, message: str, reference: Optional[str] = None) -> str:
    """A small status page (paid / expired / cancelled / not found)."""
    return _MESSAGE.format(
        title=escape(title),
        message=escape(message),
        ref=f"<p>Ref: {escape(reference)}</p>" if reference else "",
    )
