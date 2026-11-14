"""gunicorn settings for Bitsopay: gunicorn -c deploy/gunicorn.conf.py "bitsopay.server:create_app()"."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 30
graceful_timeout = 30
keepalive = 5
max_requests = 5000          # recycle workers periodically
max_requests_jitter = 500
limit_request_line = 4094
accesslog = None             # bitsopay.server logs each request itself (set BITSOPAY_LOG_LEVEL=INFO)
errorlog = "-"
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
