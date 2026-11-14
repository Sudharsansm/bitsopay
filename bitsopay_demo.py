"""
Bitsopay - Single File QR Payment Demo
--------------------------------------
Run:
    pip install bitsopay
    python bitsopay_demo.py

Open:
    http://127.0.0.1:8000

This demo uses the Bitsopay Python package to generate the QR image.
It does NOT verify whether a payment was completed.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
import json
import html
import traceback

try:
    from bitsopay import UPIPayment, qr_data_uri, new_reference
except ImportError:
    raise SystemExit(
        "Bitsopay is not installed.\n"
        "Install it with: pip install bitsopay\n"
        "If testing your local source code, run: pip install -e path\\to\\bitsopay"
    )

HOST = "127.0.0.1"
PORT = 8000

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
.logo{width:38px;height:38px;border-radius:12px;background:#635bff;color:white;display:grid;place-items:center;font-size:19px}
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
.qr{width:220px;height:220px;object-fit:contain;background:white;padding:8px;border:1px solid var(--line);border-radius:12px}
.payapp{display:block;text-decoration:none;margin-top:13px;background:#edfdf5;color:#08784e;padding:13px;border-radius:11px;font-weight:750;font-size:14px}
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
   <div class="brand"><div class="logo">₹</div><div>Bitsopay</div></div>
   <div class="tag">UPI QR Payment · Framework Test Application</div>
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

   <div class="amountbox">
    <div class="amount-caption">ENTER PAYMENT AMOUNT</div>
    <div class="amount"><span>₹</span><strong id="amount">0</strong></div>
   </div>

   <div class="keys">
    <button class="key" data-key="1">1</button><button class="key" data-key="2">2</button><button class="key" data-key="3">3</button>
    <button class="key" data-key="4">4</button><button class="key" data-key="5">5</button><button class="key" data-key="6">6</button>
    <button class="key" data-key="7">7</button><button class="key" data-key="8">8</button><button class="key" data-key="9">9</button>
    <button class="key action" data-key="clear">Clear</button><button class="key" data-key="0">0</button><button class="key action" data-key="back">⌫</button>
   </div>

   <button class="pay" id="payBtn">Generate Payment QR</button>
   <div class="error" id="error"></div>

   <div class="result" id="result">
    <h3>Scan to pay</h3>
    <p>Open any UPI app and scan this QR code</p>
    <img id="qr" class="qr" alt="Generated UPI payment QR code">
    <a id="openUpi" class="payapp" href="#">Open UPI Payment App</a>
    <div class="ref" id="reference"></div>
   </div>
   <div class="note">Enter a valid merchant UPI ID. The QR is generated dynamically using the Bitsopay Python package. No QR image is saved to disk.</div>
  </section>
  <div class="footer">BITSOPAY DEMO · Payment completion must be verified separately</div>
 </main>
</div>
<script>
let value = "";
const amountEl = document.getElementById("amount");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
function renderAmount(){ amountEl.textContent = value ? Number(value).toLocaleString("en-IN") : "0"; }
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

  const btn = document.getElementById("payBtn");
  btn.disabled = true; btn.textContent = "Generating QR...";
  try {
    const response = await fetch("/generate", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({amount, upi_id:upi, payee_name:merchant})
    });
    const data = await response.json();
    if(!response.ok) throw new Error(data.error || "Unable to generate QR.");
    document.getElementById("qr").src = data.qr;
    document.getElementById("openUpi").href = data.upi_uri;
    document.getElementById("reference").textContent = "Reference: " + data.reference;
    resultEl.classList.add("show");
    resultEl.scrollIntoView({behavior:"smooth",block:"nearest"});
  } catch(e) { showError(e.message); }
  finally { btn.disabled = false; btn.textContent = "Generate Payment QR"; }
});
function showError(msg){ errorEl.textContent = msg; errorEl.classList.add("show"); }
</script>
</body>
</html>"""


class BitsopayDemoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path != "/":
            self.send_error(404)
            return
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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

            # Generate QR through the actual Bitsopay package.
            payment = UPIPayment(
                upi_id=upi_id,
                payee_name=payee_name,
                amount=amount,
                note="Bitsopay demo payment",
                reference=new_reference(),
            )
            image_data = qr_data_uri(payment)
            self.send_json(200, {
                "qr": image_data,
                "upi_uri": payment.uri,
                "reference": payment.reference,
                "amount": str(payment.amount),
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
    print(f"\nBitsopay demo running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.\n")
    HTTPServer((HOST, PORT), BitsopayDemoHandler).serve_forever()
