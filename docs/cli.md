# Command line

`bitsopay <command> [options]` (or `python -m bitsopay`). Exit code `0` on success, `2` on a user/validation error
(message on stderr).

| Command | What it does |
|---|---|
| `uri` | Print the `upi://pay` deep link |
| `qr -o FILE` | Write a QR (`.png` or `.svg`) |
| `page -o FILE.html` | Standalone HTML payment page |
| `link` | Signed HTTPS link (needs `--secret`/`BITSOPAY_SECRET`) |
| `session-qr -o FILE` | Expiring QR from a signed link |
| `quick-link` | Database-free short link |
| `create-link` | Short link stored in SQLite (`--db`) |
| `history`, `show REF` | Inspect payments |
| `mark-paid REF`, `cancel REF` | Change status |
| `serve` | Development server (use gunicorn in production) |

Common payment options: `--upi-id`, `--name`, `--amount`, `--note`, `--ref`, `--mcc`.
Run `bitsopay <command> --help` for the full list. `--version` prints the version.
