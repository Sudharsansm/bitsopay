"""
Bitsopay - Single File QR Payment Demo (Upgraded)
--------------------------------------------------
Run:
    pip install bitsopay
    python bitsopay_demo.py

Open:
    http://127.0.0.1:8000

This demo uses the Bitsopay Python package to:
  1. Generate a UPI payment QR code (branded with the Bitsopay logo in a
     circular badge, like the logo overlay you see in real UPI apps).
  2. Create a SHORT, SECURE payment link for that same payment, backed by
     bitsopay.PaymentLinks + bitsopay.SQLiteStore. The link only ever
     contains an unguessable reference code (e.g. /p/BP684BF1555E4B49),
     never the UPI ID, amount or merchant name -- those stay server-side
     in a local SQLite file. The link also expires automatically.

This demo does NOT verify whether a payment was completed -- that is by
design (Bitsopay is not a payment gateway). You confirm the payment in
your own bank / UPI app and would call ``links.mark_paid(...)`` yourself.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
import json
import html
import re

try:
    from bitsopay import (
        UPIPayment,
        qr_data_uri,
        new_reference,
        PaymentLinks,
        SQLiteStore,
        NotFoundError,
    )
except ImportError:
    raise SystemExit(
        "Bitsopay is not installed.\n"
        "Install it with: pip install bitsopay\n"
        "If testing your local source code, run: pip install -e path\\to\\bitsopay"
    )

HOST = "127.0.0.1"
PORT = 8000
BASE_URL = f"http://{HOST}:{PORT}"
DB_PATH = "bitsopay_demo.db"          # local SQLite file -- holds payment records only
LINK_EXPIRES_IN = 30 * 60             # default share-link expiry if the form doesn't say otherwise
QR_SESSION_EXPIRES_IN = 5 * 60        # default on-screen QR session expiry if the form doesn't say otherwise
MIN_SESSION_EXPIRES_IN = 60           # 1 minute floor -- keeps a client from asking for a 0s / negative session
MAX_SESSION_EXPIRES_IN = 60 * 60      # 1 hour ceiling -- keeps a client from asking for a never-expiring session

# The Bitsopay mark, shown as a small circular badge on the QR and in the header.
# Embedded as base64 so this stays a single, runnable file.
BITSOPAY_ICON_B64 = (
    "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"
)

# One shared store + link factory for the whole demo process.
STORE = SQLiteStore(DB_PATH)
LINKS = PaymentLinks(STORE, BASE_URL, prefix="BP")

REF_RE = re.compile(r"^[A-Za-z0-9]{6,40}$")

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bitsopay | QR Payment Demo</title>
<style>
:root {
  --bg:#f4f6fb; --card:#fff; --ink:#172033; --muted:#788197;
  --primary:#635bff; --line:#e8eaf1; --green:#159b69;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}
.app{width:100%;max-width:430px;background:var(--card);border:1px solid var(--line);border-radius:25px;box-shadow:0 18px 60px #202b4b12;overflow:hidden}
.top{padding:25px 26px 18px;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:11px;font-weight:800;font-size:20px;letter-spacing:-.5px}
.logo{width:38px;height:38px;border-radius:50%;background:#fff;border:1px solid var(--line);display:grid;place-items:center;overflow:hidden;padding:4px}
.logo img{width:100%;height:100%;object-fit:contain}
.tag{margin-top:5px;color:var(--muted);font-size:12px}
.content{padding:23px 26px 26px}
.label{font-size:12px;font-weight:700;color:#606a80;margin:0 0 8px}
.field{width:100%;height:46px;border:1px solid var(--line);border-radius:11px;padding:0 13px;font-size:14px;outline:none;background:#fff;color:var(--ink)}
.field:focus{border-color:var(--primary);box-shadow:0 0 0 3px #635bff18}
.group{margin-bottom:17px}
.amountbox{margin:21px 0 16px;padding:18px;border:1px solid var(--line);border-radius:16px;text-align:center;background:#fafaff}
.amount-caption{font-size:12px;color:var(--muted);font-weight:600}
.amount{font-size:42px;line-height:1.3;font-weight:800;letter-spacing:-1.5px;margin-top:3px;display:flex;justify-content:center;align-items:center;gap:5px}
.amount span{font-size:27px;color:#858ba0}
.keys{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:14px 0 18px}
.key{height:51px;border:1px solid var(--line);border-radius:12px;background:white;font-size:19px;font-weight:650;color:var(--ink);cursor:pointer}
.key:active{background:#efefff;border-color:#c8c5ff}
.key.action{font-size:15px;color:#656d80}
.pay{width:100%;height:51px;border:0;border-radius:13px;background:var(--primary);color:white;font-size:15px;font-weight:750;cursor:pointer;box-shadow:0 7px 18px #635bff35}
.pay:disabled{opacity:.6;cursor:wait}
.note{text-align:center;font-size:11px;color:var(--muted);line-height:1.6;margin:13px 5px 0}
.result{display:none;margin-top:20px;border:1px solid var(--line);border-radius:16px;padding:18px;text-align:center;background:#fcfcff}
.result.show{display:block}
.result h3{font-size:16px;margin:0 0 5px}
.result p{font-size:12px;color:var(--muted);margin:0 0 13px}
.qr-wrap{position:relative;width:220px;height:220px;margin:0 auto}
.qr{width:220px;height:220px;object-fit:contain;background:white;padding:8px;border:1px solid var(--line);border-radius:12px}
.qr-badge{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:46px;height:46px;border-radius:50%;background:#fff;border:3px solid #fff;box-shadow:0 2px 10px #0003;display:grid;place-items:center;overflow:hidden;padding:5px}
.qr-badge img{width:100%;height:100%;object-fit:contain}
.qr-expired-overlay{display:none;position:absolute;inset:0;border-radius:12px;background:#ffffffee;backdrop-filter:blur(1px);align-items:center;justify-content:center;font-size:13px;font-weight:750;color:#b42318}
.qr-expired-overlay.show{display:flex}
.qr-wrap.expired .qr{filter:blur(2px) grayscale(.6);opacity:.5}
.qr-wrap.expired .qr-badge{opacity:.35}
.qr-timer{margin-top:10px;font-size:12px;color:var(--muted);font-weight:600}
.qr-timer.warn strong{color:#b42318}
.qr-timer.expired{color:#b42318;font-weight:750}
.payapp{display:block;text-decoration:none;margin-top:13px;background:#edfdf5;color:#08784e;padding:13px;border-radius:11px;font-weight:750;font-size:14px}
.payapp.disabled{pointer-events:none;background:#f1f1f4;color:#9aa1b2}
.regen{display:block;width:100%;margin-top:12px;height:44px;border:0;border-radius:11px;background:var(--primary);color:#fff;font-weight:750;font-size:14px;cursor:pointer}
.sharebox{margin-top:14px;border:1px dashed #cfd4e4;border-radius:12px;padding:12px;text-align:left;background:#fff}
.sharebox .label{margin:0 0 7px}
.sharerow{display:flex;gap:7px}
.sharerow input{flex:1;height:40px;border:1px solid var(--line);border-radius:9px;padding:0 10px;font-size:12px;background:#f8f9fc;color:var(--ink)}
.copybtn{flex-shrink:0;height:40px;padding:0 14px;border:0;border-radius:9px;background:var(--ink);color:#fff;font-size:12px;font-weight:700;cursor:pointer}
.copybtn.copied{background:var(--green)}
.sharemeta{margin-top:8px;font-size:11px;color:var(--muted);display:flex;justify-content:space-between}
.lock{color:var(--green);font-weight:700}
.ref{font-size:10px;color:var(--muted);margin-top:12px;overflow-wrap:anywhere}
.error{display:none;margin-top:12px;color:#b42318;background:#fff1f0;border-radius:10px;padding:10px;font-size:12px}
.error.show{display:block}
.footer{text-align:center;padding:0 20px 20px;font-size:10px;color:#9aa1b2}
@media(max-width:420px){.wrap{padding:10px}.app{border-radius:19px}.content{padding:20px}.top{padding:21px 20px 16px}}
</style>
</head>
<body>
<div class="wrap">
 <main class="app">
  <header class="top">
   <div class="brand"><div class="logo"><img src="data:image/png;base64,__ICON__" alt="Bitsopay"></div><div>Bitsopay</div></div>
   <div class="tag">UPI QR Payment &middot; Framework Test Application</div>
  </header>
  <section class="content">
   <div class="group">
    <div class="label">MERCHANT NAME</div>
    <input id="merchant" class="field" value="My Demo Store" maxlength="80">
   </div>
   <div class="group">
    <div class="label">MERCHANT UPI ID</div>
    <input id="upi" class="field" value="yourname@upi" maxlength="120" autocomplete="off">
   </div>

   <div class="group">
    <div class="label">SESSION EXPIRES</div>
    <select id="sessionExpiry" class="field">
     <option value="120">2 minutes (demo -- quick test)</option>
     <option value="300" selected>5 minutes (default)</option>
     <option value="600">10 minutes</option>
     <option value="900">15 minutes</option>
     <option value="1800">30 minutes</option>
    </select>
   </div>

   <div class="amountbox">
    <div class="amount-caption">ENTER PAYMENT AMOUNT</div>
    <div class="amount"><span>&#8377;</span><strong id="amount">0</strong></div>
   </div>

   <div class="keys">
    <button class="key" data-key="1">1</button><button class="key" data-key="2">2</button><button class="key" data-key="3">3</button>
    <button class="key" data-key="4">4</button><button class="key" data-key="5">5</button><button class="key" data-key="6">6</button>
    <button class="key" data-key="7">7</button><button class="key" data-key="8">8</button><button class="key" data-key="9">9</button>
    <button class="key action" data-key="clear">Clear</button><button class="key" data-key="0">0</button><button class="key action" data-key="back">&#9003;</button>
   </div>

   <button class="pay" id="payBtn">Generate Payment QR</button>
   <div class="error" id="error"></div>

   <div class="result" id="result">
    <h3>Scan to pay</h3>
    <p>Open any UPI app and scan this QR code</p>
    <div class="qr-wrap">
     <img id="qr" class="qr" alt="Generated UPI payment QR code">
     <div class="qr-badge"><img src="data:image/png;base64,__ICON__" alt=""></div>
     <div class="qr-expired-overlay" id="qrExpiredOverlay">
      <span>&#8987; QR expired</span>
     </div>
    </div>
    <div class="qr-timer" id="qrTimer">QR session expires in <strong id="qrTimerClock">05:00</strong></div>
    <a id="openUpi" class="payapp" href="#">Open UPI Payment App</a>

    <div class="sharebox">
     <div class="label">SHARE PAYMENT LINK</div>
     <div class="sharerow">
      <input id="shareUrl" readonly>
      <button class="copybtn" id="copyBtn">Copy</button>
     </div>
     <div class="sharemeta">
      <span class="lock">&#128274; secure &middot; reference-only link</span>
      <span id="expiresIn"></span>
     </div>
    </div>

    <div class="ref" id="reference"></div>
    <button class="regen" id="regenBtn" style="display:none">Generate a new QR</button>
   </div>
   <div class="note">Enter a valid merchant UPI ID. The QR and the share link are generated dynamically using the Bitsopay Python package. The amount and UPI ID are never stored in the link itself.</div>
  </section>
  <div class="footer">BITSOPAY DEMO &middot; Payment completion must be verified separately</div>
 </main>
</div>
<script>
let value = "";
const amountEl = document.getElementById("amount");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
let qrTimerHandle = null;
let qrDeadline = null;
function renderAmount(){ amountEl.textContent = value ? Number(value).toLocaleString("en-IN") : "0"; }

function stopQrTimer(){
  if(qrTimerHandle){ clearInterval(qrTimerHandle); qrTimerHandle = null; }
}

function expireQrSession(){
  stopQrTimer();
  document.getElementById("qrTimer").textContent = "QR session expired";
  document.getElementById("qrTimer").classList.remove("warn");
  document.getElementById("qrTimer").classList.add("expired");
  document.querySelector(".qr-wrap").classList.add("expired");
  document.getElementById("qrExpiredOverlay").classList.add("show");
  document.getElementById("openUpi").classList.add("disabled");
  document.getElementById("regenBtn").style.display = "block";
}

function startQrTimer(seconds){
  stopQrTimer();
  qrDeadline = Date.now() + seconds * 1000;
  document.querySelector(".qr-wrap").classList.remove("expired");
  document.getElementById("qrExpiredOverlay").classList.remove("show");
  document.getElementById("openUpi").classList.remove("disabled");
  document.getElementById("regenBtn").style.display = "none";
  const timerEl = document.getElementById("qrTimer");
  const clockEl = document.getElementById("qrTimerClock");
  timerEl.classList.remove("expired");

  function tick(){
    const remainingMs = qrDeadline - Date.now();
    if(remainingMs <= 0){ expireQrSession(); return; }
    const remaining = Math.ceil(remainingMs / 1000);
    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    clockEl.textContent = m + ":" + s;
    timerEl.classList.toggle("warn", remaining <= 30);
  }
  tick();
  qrTimerHandle = setInterval(tick, 1000);
}
document.querySelectorAll("[data-key]").forEach(btn => {
  btn.addEventListener("click", () => {
    const k = btn.dataset.key;
    if(k === "clear") value = "";
    else if(k === "back") value = value.slice(0,-1);
    else if(value.length < 8) value += k;
    renderAmount();
  });
});
document.getElementById("payBtn").addEventListener("click", async () => {
  errorEl.classList.remove("show");
  resultEl.classList.remove("show");
  const amount = Number(value);
  if(!amount || amount <= 0){ showError("Please enter an amount greater than zero."); return; }
  const upi = document.getElementById("upi").value.trim();
  const merchant = document.getElementById("merchant").value.trim();
  if(!upi || !merchant){ showError("Please enter the merchant name and UPI ID."); return; }
  const sessionExpiresIn = Number(document.getElementById("sessionExpiry").value);

  const btn = document.getElementById("payBtn");
  btn.disabled = true; btn.textContent = "Generating QR...";
  try {
    const response = await fetch("/generate", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({amount, upi_id:upi, payee_name:merchant, session_expires_in:sessionExpiresIn})
    });
    const data = await response.json();
    if(!response.ok) throw new Error(data.error || "Unable to generate QR.");
    document.getElementById("qr").src = data.qr;
    document.getElementById("openUpi").href = data.upi_uri;
    document.getElementById("reference").textContent = "Reference: " + data.reference;
    document.getElementById("shareUrl").value = data.share_url;
    document.getElementById("expiresIn").textContent = "link expires in " + Math.round(data.expires_in/60) + " min";
    const copyBtn = document.getElementById("copyBtn");
    copyBtn.textContent = "Copy"; copyBtn.classList.remove("copied");
    resultEl.classList.add("show");
    startQrTimer(data.qr_expires_in);
    resultEl.scrollIntoView({behavior:"smooth",block:"nearest"});
  } catch(e) { showError(e.message); }
  finally { btn.disabled = false; btn.textContent = "Generate Payment QR"; }
});
document.getElementById("copyBtn").addEventListener("click", async () => {
  const input = document.getElementById("shareUrl");
  const btn = document.getElementById("copyBtn");
  try {
    await navigator.clipboard.writeText(input.value);
  } catch(e) {
    input.select(); document.execCommand("copy");
  }
  btn.textContent = "Copied!"; btn.classList.add("copied");
  setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 1600);
});
function showError(msg){ errorEl.textContent = msg; errorEl.classList.add("show"); }
document.getElementById("regenBtn").addEventListener("click", () => {
  document.getElementById("payBtn").click();
});
</script>
</body>
</html>"""

PAGE = PAGE.replace("__ICON__", BITSOPAY_ICON_B64)


def _link_payment_page(record, links_obj, now):
    """A minimal page rendered when someone opens a short /p/<ref> share link."""
    status = record.effective_status(now())
    amount_html = (
        f"&#8377;{record.amount:.2f}" if record.amount is not None else "Customer enters amount"
    )
    payment = record.to_payment()
    qr_src = qr_data_uri(payment) if status == "pending" else ""
    seconds_left = None
    if status == "pending" and record.expires_at is not None:
        seconds_left = max(0, int(record.expires_at - now()))
    banner = {
        "pending": ("#edfdf5", "#08784e", "Ready to pay"),
        "paid": ("#edfdf5", "#08784e", "Payment already marked as received"),
        "cancelled": ("#fff1f0", "#b42318", "This payment link was cancelled"),
        "expired": ("#fff1f0", "#b42318", "This payment link has expired"),
    }[status]
    timer_html = (
        f'<div class="timer" id="timer">Session expires in <strong id="clock">--:--</strong></div>'
        if seconds_left is not None else ""
    )
    timer_script = (
        f"""<script>
(function(){{
  var remaining = {seconds_left};
  var clockEl = document.getElementById("clock");
  var timerEl = document.getElementById("timer");
  function tick(){{
    if(remaining <= 0){{
      timerEl.textContent = "Session expired -- ask for a new link";
      timerEl.classList.add("expired");
      var openBtn = document.querySelector(".openupi");
      if(openBtn) openBtn.classList.add("disabled");
      var qrImg = document.querySelector(".qr");
      if(qrImg) qrImg.classList.add("faded");
      return;
    }}
    var m = String(Math.floor(remaining / 60)).padStart(2, "0");
    var s = String(remaining % 60).padStart(2, "0");
    clockEl.textContent = m + ":" + s;
    timerEl.classList.toggle("warn", remaining <= 60);
    remaining -= 1;
    setTimeout(tick, 1000);
  }}
  tick();
}})();
</script>"""
        if seconds_left is not None else ""
    )
    body = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pay {html.escape(record.payee_name)} &middot; Bitsopay</title>
<style>
body{{margin:0;background:#f4f6fb;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#172033}}
.wrap{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{width:100%;max-width:380px;background:#fff;border:1px solid #e8eaf1;border-radius:22px;padding:26px;text-align:center;box-shadow:0 18px 60px #202b4b12}}
.badge{{display:inline-block;padding:7px 14px;border-radius:999px;font-size:12px;font-weight:700;background:{banner[0]};color:{banner[1]};margin-bottom:14px}}
h1{{font-size:18px;margin:0 0 4px}}
.amt{{font-size:30px;font-weight:800;margin:10px 0}}
img.qr{{width:200px;height:200px;border:1px solid #e8eaf1;border-radius:12px;padding:8px;background:#fff;transition:filter .2s,opacity .2s}}
img.qr.faded{{filter:blur(2px) grayscale(.6);opacity:.5}}
.timer{{margin-top:12px;font-size:12px;color:#788197;font-weight:600}}
.timer.warn strong{{color:#b42318}}
.timer.expired{{color:#b42318;font-weight:750}}
.ref{{margin-top:14px;font-size:11px;color:#788197;overflow-wrap:anywhere}}
a.openupi{{display:block;margin-top:14px;text-decoration:none;background:#635bff;color:#fff;padding:12px;border-radius:11px;font-weight:700;font-size:14px}}
a.openupi.disabled{{pointer-events:none;background:#f1f1f4;color:#9aa1b2}}
</style></head><body><div class="wrap"><div class="card">
<div class="badge">{banner[2]}</div>
<h1>{html.escape(record.payee_name)}</h1>
<div class="amt">{amount_html}</div>
{'<img class="qr" src="' + qr_src + '" alt="UPI payment QR code">' if qr_src else ''}
{timer_html}
{'<a class="openupi" href="' + payment.uri + '">Open UPI Payment App</a>' if status == "pending" else ''}
<div class="ref">Reference: {html.escape(record.reference)} &middot; this link never exposes the UPI ID or amount in its URL</div>
</div></div>{timer_script}</body></html>"""
    return body.encode("utf-8")


class BitsopayDemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/p/"):
            ref = path[len("/p/"):]
            if not REF_RE.match(ref):
                self.send_error(404)
                return
            record = LINKS.get(ref)
            if record is None:
                self.send_error(404, "Unknown or expired payment link")
                return
            LINKS.record_view(ref)
            body = _link_payment_page(record, LINKS, LINKS.clock)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/generate":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 10000:
                return self.send_json(413, {"error": "Request too large."})
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            amount = payload.get("amount")
            upi_id = str(payload.get("upi_id", "")).strip()
            payee_name = str(payload.get("payee_name", "")).strip()

            # "SESSION EXPIRES" (under Merchant UPI ID on the form) -- how long this
            # payment session should stay valid for, in seconds. Clamped to a sane
            # range so a tampered/bad request can't ask for 0s or a never-expiring one.
            try:
                session_expires_in = int(payload.get("session_expires_in", QR_SESSION_EXPIRES_IN))
            except (TypeError, ValueError):
                session_expires_in = QR_SESSION_EXPIRES_IN
            session_expires_in = max(MIN_SESSION_EXPIRES_IN, min(MAX_SESSION_EXPIRES_IN, session_expires_in))

            # 1) The scannable UPI QR, generated through the Bitsopay package.
            payment = UPIPayment(
                upi_id=upi_id,
                payee_name=payee_name,
                amount=amount,
                note="Bitsopay demo payment",
                reference=new_reference(),
            )
            image_data = qr_data_uri(payment)

            # 2) A short, secure share link for the SAME payment. The URL only
            #    carries a fresh unguessable reference (LINKS.prefix + random
            #    hex) -- amount, UPI ID and merchant name stay in DB_PATH on
            #    this server, never in the link itself. It also self-expires.
            link = LINKS.create(
                upi_id=payment.upi_id,
                payee_name=payment.payee_name,
                amount=payment.amount,
                note="Bitsopay demo payment",
                expires_in=session_expires_in,
            )

            self.send_json(200, {
                "qr": image_data,
                "upi_uri": payment.uri,
                "reference": payment.reference,
                "amount": str(payment.amount),
                "share_url": link.url,
                "expires_in": session_expires_in,
                "qr_expires_in": session_expires_in,
            })
        except Exception as exc:
            self.send_json(400, {"error": str(exc) or "Invalid payment details."})

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[Bitsopay] " + fmt % args)


if __name__ == "__main__":
    print(f"\nBitsopay demo running at {BASE_URL}")
    print(f"Payment records stored in: {DB_PATH}")
    print("Press Ctrl+C to stop.\n")
    try:
        HTTPServer((HOST, PORT), BitsopayDemoHandler).serve_forever()
    finally:
        STORE.close()