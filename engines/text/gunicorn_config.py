# SPDX-License-Identifier: GPL-3.0-only
# engines/text/gunicorn_config.py

bind = "0.0.0.0:8080"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
keepalive = 120
timeout = 60
