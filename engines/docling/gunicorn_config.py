# engines/docling/gunicorn_config.py

bind = "0.0.0.0:8080"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
keepalive = 120
timeout = 120
