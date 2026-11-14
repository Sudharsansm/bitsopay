# syntax=docker/dockerfile:1
FROM python:3.15-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /wheels

FROM python:3.15-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    BITSOPAY_DB=/data/payments.db BITSOPAY_LOG_LEVEL=INFO PORT=8080
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin bitsopay \
    && mkdir /data && chown bitsopay /data
COPY --from=build /wheels /wheels
COPY deploy/gunicorn.conf.py /etc/bitsopay/gunicorn.conf.py
RUN pip install /wheels/*.whl "gunicorn>=22" && rm -rf /wheels
USER bitsopay
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/ready' % os.environ.get('PORT','8080'), timeout=3)"
CMD ["gunicorn", "-c", "/etc/bitsopay/gunicorn.conf.py", "bitsopay.server:create_app()"]
