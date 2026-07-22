"""
Gunicorn configuration for OCR Engine Service
"""

import os

# Server socket
bind = "0.0.0.0:8080"

# Worker configuration
# OCR model is memory-intensive, use limited workers
workers = int(os.getenv("GUNICORN_WORKERS", "1"))
worker_class = "uvicorn.workers.UvicornWorker"

# Timeout settings - OCR processing may take time
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")

# Process naming
proc_name = "ocr-engine"

# Max requests before restart (helps with memory leaks)
max_requests = 1000
max_requests_jitter = 50
