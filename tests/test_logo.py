"""The Bitsopay logo in the centre of every QR code."""

import base64
import io
import json
import re

import pytest
from PIL import Image, ImageChops

import bitsopay
from bitsopay import PaymentLinks, StatelessLinks, StaticSession, UPIPayment, ValidationError, create_dynamic_qr
from bitsopay import logo as logo_mod
from bitsopay.cli import main
from bitsopay.qr import qr_data_uri, qr_png, qr_svg, save_qr, text_qr_png, text_qr_svg
from bitsopay.server import create_app
from conftest import SECRET, TOKEN, FakeClock, make_caller

zxingcpp = pytest.importorskip("zxingcpp")

T0 = 1_800_000_000
BASE = "https://pay.example.com"
PAY = UPIPayment(upi_id="shop@okhdfcbank", payee_name="My Shop", amount="499.00", reference="INV-1")


@pytest.fixture(autouse=True)
def _no_env_logo(monkeypatch):
    monkeypatch.delenv("BITSOPAY_LOGO", raising=False)


def scan(png: bytes) -> str:
    codes = zxingcpp.read_barcodes(Image.open(io.BytesIO(png)), formats=zxingcpp.BarcodeFormat.QRCode)
    assert len(codes) == 1, "QR code did not decode"
    return codes[0].text


def solid_png(color=(200, 0, 0, 255), size=(40, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


def centre_pixel(png: bytes):
    img = Image.open(io.BytesIO(png)).convert("RGB")
    return img.getpixel((img.width // 2, img.height // 2))


# ---- the logo is drawn, and the QR still scans -----------------------------------


def test_default_qr_has_the_logo_and_still_scans():
    with_logo, plain = qr_png(PAY), qr_png(PAY, logo=False)
    assert with_logo != plain and with_logo.startswith(b"\x89PNG")
    assert scan(with_logo) == PAY.uri == scan(plain)
    r, g, b = centre_pixel(with_logo)  # the bundled logo is blue/orange, never plain black or white
    assert max(r, g, b) - min(r, g, b) > 40


@pytest.mark.parametrize("error", ["L", "M", "Q", "H", "m"])
def test_logo_qr_scans_at_any_requested_error_level(error):
    assert scan(qr_png(PAY, error=error)) == PAY.uri


@pytest.mark.parametrize("scale", [4, 6, 10, 20])
def test_logo_qr_scans_at_any_size(scale):
    assert scan(qr_png(PAY, scale=scale)) == PAY.uri


def test_long_payload_with_logo_scans():
    text = BASE + "/s/" + "HALL-A-1000.1800000000.1800007200." + "f" * 16 + "?" + "x" * 200
    assert scan(text_qr_png(text)) == text


def test_logo_forces_error_level_h():
    # with a logo the QR is drawn at level H whatever "error" says, so L and M give the same image
    assert qr_png(PAY, error="L") == qr_png(PAY, error="M") == qr_png(PAY, error="H")
    assert qr_png(PAY, error="L", logo=False) != qr_png(PAY, error="H", logo=False)


def test_logo_covers_only_a_small_central_area():
    plain = Image.open(io.BytesIO(qr_png(PAY, logo=False, error="H"))).convert("RGB")
    logoed = Image.open(io.BytesIO(qr_png(PAY))).convert("RGB")
    assert plain.size == logoed.size
    changed = sum(ImageChops.difference(plain, logoed).convert("L").histogram()[1:])
    share = changed / (plain.width * plain.height)
    assert 0 < share < 0.15  # level H tolerates about 30% damage; the badge stays well below half of that


def test_output_is_deterministic():
    assert qr_png(PAY) == qr_png(PAY)
    assert qr_svg(PAY) == qr_svg(PAY)


# ---- SVG -------------------------------------------------------------------------


def test_svg_embeds_a_centred_logo():
    svg = qr_svg(PAY)
    assert svg.rstrip().endswith("</svg>") and svg.count("<svg") == 1
    m = re.search(r'<image x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg)
    assert m, "no logo element in the SVG"
    x, y, w, h = map(float, m.groups())
    total = float(re.search(r'<svg[^>]* width="(\d+)"', svg).group(1))
    assert abs((x + w / 2) - total / 2) < 0.1 and abs((y + h / 2) - total / 2) < 0.1
    assert max(w, h) < total * 0.3
    href = re.search(r'href="data:image/png;base64,([^"]+)"', svg).group(1)
    assert base64.b64decode(href).startswith(b"\x89PNG")
    assert "<image" not in qr_svg(PAY, logo=False)
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in svg  # valid inside a standalone .svg file


def test_svg_without_logo_keeps_the_requested_error_level():
    assert qr_svg(PAY, error="L", logo=False) != qr_svg(PAY, error="H", logo=False)


# ---- choosing the logo ------------------------------------------------------------


def test_custom_logo_from_bytes_and_path(tmp_path):
    red = solid_png()
    path = tmp_path / "mine.png"
    path.write_bytes(red)
    by_bytes, by_path = qr_png(PAY, logo=red), qr_png(PAY, logo=path)
    assert by_bytes == by_path != qr_png(PAY)
    assert str(path) and qr_png(PAY, logo=str(path)) == by_path
    r, g, b = centre_pixel(by_bytes)
    assert r > 150 and g < 80 and b < 80
    assert scan(by_bytes) == PAY.uri


def test_logo_off_values():
    plain = qr_png(PAY, logo=False)
    assert qr_png(PAY, logo=None) == plain


def test_jpeg_logo_is_accepted():
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), (0, 120, 0)).save(buf, format="JPEG")
    assert scan(qr_png(PAY, logo=buf.getvalue())) == PAY.uri


def test_environment_variable_controls_the_default(monkeypatch, tmp_path):
    default = qr_png(PAY)
    monkeypatch.setenv("BITSOPAY_LOGO", "none")
    assert qr_png(PAY) == qr_png(PAY, logo=False) != default
    path = tmp_path / "env.png"
    path.write_bytes(solid_png((0, 0, 200, 255)))
    monkeypatch.setenv("BITSOPAY_LOGO", str(path))
    r, _, b = centre_pixel(qr_png(PAY))
    assert b > 150 and r < 80
    assert qr_png(PAY, logo=True) == qr_png(PAY)
    assert qr_png(PAY, logo=False) == qr_png(PAY, logo=False)  # an explicit False always wins
    monkeypatch.setenv("BITSOPAY_LOGO", str(tmp_path / "missing.png"))
    with pytest.raises(ValidationError, match="not found"):
        qr_png(PAY)


@pytest.mark.parametrize(
    "bad",
    [b"not an image", b"", b"\x89PNG\r\n\x1a\n" + b"\0" * 20, 5, 1.5, ["x"], "/no/such/logo.png"],
)
def test_bad_logo_is_rejected(bad):
    with pytest.raises(ValidationError):
        qr_png(PAY, logo=bad)


def test_empty_and_oversized_logos_are_rejected(tmp_path):
    with pytest.raises(ValidationError, match="empty"):
        qr_png(PAY, logo=solid_png((0, 0, 0, 0)))
    with pytest.raises(ValidationError, match="too large"):
        qr_png(PAY, logo=b"0" * (5 * 1024 * 1024 + 1))
    big = tmp_path / "big.png"
    big.write_bytes(b"0" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ValidationError, match="too large"):
        qr_png(PAY, logo=big)


def test_bad_error_level_is_still_rejected():
    with pytest.raises(ValueError, match="error"):
        qr_png(PAY, error="Z")
    with pytest.raises(ValueError, match="error"):
        qr_svg(PAY, error="Z", logo=False)


def test_bundled_logo_is_inside_the_package():
    raw = logo_mod.resolve(True)
    assert raw and raw.startswith(b"\x89PNG") and len(raw) < 100_000
    assert logo_mod.resolve(False) is None and logo_mod.resolve(None) is None


# ---- every QR type carries it -------------------------------------------------------


def test_data_uri_and_save_qr(tmp_path):
    uri = qr_data_uri(PAY)
    assert scan(base64.b64decode(uri.split(",", 1)[1])) == PAY.uri
    png, svg = save_qr(PAY, tmp_path / "a.png"), save_qr(PAY, tmp_path / "a.svg")
    assert scan(png.read_bytes()) == PAY.uri and "<image" in svg.read_text()
    assert "<image" not in save_qr(PAY, tmp_path / "b.svg", logo=False).read_text()
    assert save_qr(PAY, tmp_path / "c.png", logo=False).read_bytes() == qr_png(PAY, logo=False)


def test_text_qr_helpers():
    assert scan(text_qr_png("https://pay.example.com/x")) == "https://pay.example.com/x"
    assert "<image" in text_qr_svg("hello") and "<image" not in text_qr_svg("hello", logo=False)


def test_all_link_and_session_classes_draw_the_logo(tmp_path):
    clock = FakeClock(T0)
    pay = UPIPayment(upi_id="shop@okhdfcbank", payee_name="My Shop")
    sq = create_dynamic_qr(BASE, PAY, SECRET)
    stateless = StatelessLinks("shop@okhdfcbank", "My Shop", SECRET, BASE, clock=clock).create(10)
    short = PaymentLinks(bitsopay.MemoryStore(), BASE).create("shop@okhdfcbank", "My Shop", 10)
    static = StaticSession("shop@okhdfcbank", "My Shop", SECRET, BASE, clock=clock).create()
    for obj, expect in ((sq, sq.url), (stateless, stateless.url), (short, short.url), (static, static.url)):
        assert scan(obj.png()) == expect
        assert "<image" in obj.svg() and "<image" not in obj.svg(logo=False)
        assert obj.png() != obj.png(logo=False)
        assert obj.save(tmp_path / "q.png", logo=False).read_bytes() == obj.png(logo=False)
    assert pay.uri  # open-amount payments render too
    assert scan(qr_png(pay)) == pay.uri


# ---- server ---------------------------------------------------------------------------


def test_server_images_carry_the_logo_and_a_svg_safe_csp():
    clock = FakeClock(T0)
    sessions = StaticSession("shop@okhdfcbank", "My Shop", SECRET, BASE, clock=clock)
    stateless = StatelessLinks("shop@okhdfcbank", "My Shop", SECRET, BASE, clock=clock)
    call = make_caller(create_app(stateless=stateless, sessions=sessions, admin_token=TOKEN, clock=clock))
    ref = json.loads(call("/api/payments", method="POST", token=TOKEN, body={"amount": 5})[2])["reference"]
    out = json.loads(call("/api/sessions", method="POST", token=TOKEN, body={})[2])

    status, headers, png = call("/s/qr.png")
    assert status.startswith("200") and scan(png) == out["url"]
    status, headers, svg = call("/s/qr.svg")
    assert status.startswith("200") and b"<image" in svg
    assert "img-src data:" in headers["Content-Security-Policy"]
    assert (
        "script-src" not in headers["Content-Security-Policy"]
        and "default-src 'none'" in headers["Content-Security-Policy"]
    )

    page = call(f"/p/{ref}")[2]
    embedded = re.search(rb"data:image/png;base64,([A-Za-z0-9+/=]+)", page).group(1)
    assert scan(base64.b64decode(embedded)).startswith("upi://pay?")
    assert call(f"/p/{ref}/qr.png")[0].startswith("200")
    assert "img-src" not in call(f"/p/{ref}/qr.png")[1]["Content-Security-Policy"]


# ---- command line ----------------------------------------------------------------------


def test_cli_logo_flags(tmp_path, capsys):
    base = ["qr", "--upi-id", "shop@okhdfcbank", "--name", "My Shop", "--amount", "10"]
    default, plain, custom = tmp_path / "d.png", tmp_path / "p.png", tmp_path / "c.png"
    mine = tmp_path / "mine.png"
    mine.write_bytes(solid_png())
    assert main([*base, "-o", str(default)]) == 0
    assert main([*base, "-o", str(plain), "--no-logo"]) == 0
    assert main([*base, "-o", str(custom), "--logo", str(mine)]) == 0
    capsys.readouterr()
    assert len({default.read_bytes(), plain.read_bytes(), custom.read_bytes()}) == 3
    assert all(scan(f.read_bytes()).startswith("upi://pay?") for f in (default, plain, custom))
    assert main([*base, "-o", str(tmp_path / "x.png"), "--logo", str(tmp_path / "nope.png")]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_static_qr_and_session_qr_draw_the_logo(tmp_path, capsys):
    out = tmp_path / "s.png"
    args = ["static-qr", "--upi-id", "shop@okhdfcbank", "--name", "My Shop", "--session-id", "S1"]
    args += ["--duration", "3600", "--base-url", BASE, "--secret", SECRET, "-o", str(out)]
    assert main(args) == 0
    with_logo = out.read_bytes()
    assert main([*args, "--no-logo"]) == 0
    assert out.read_bytes() != with_logo
    capsys.readouterr()
    sq = tmp_path / "sq.png"
    assert main(["session-qr", "--upi-id", "shop@okhdfcbank", "--name", "My Shop", "--amount", "5",
                 "--base-url", BASE, "--secret", SECRET, "-o", str(sq)]) == 0  # fmt: skip
    assert scan(sq.read_bytes()).startswith(BASE + "/p/") or scan(sq.read_bytes()).startswith(BASE)
