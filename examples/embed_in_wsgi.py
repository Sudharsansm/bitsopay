"""Run the Bitsopay WSGI app (development server; use gunicorn in production)."""

import os

from bitsopay import SQLiteStore
from bitsopay.server import serve

with SQLiteStore(os.environ.get("BITSOPAY_DB", "payments.db")) as store:
    serve(
        store=store,
        admin_token=os.environ.get("BITSOPAY_ADMIN_TOKEN", "dev-token-change-me-please"),
        base_url="http://127.0.0.1:8080",
    )
