# Gunicorn configuration for Layout Detection engine

bind = "0.0.0.0:8080"
workers = 1  # Single worker for model memory efficiency
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 300  # 5 minutes timeout for large documents
keepalive = 120
preload_app = False  # Don't preload to avoid model loading issues

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
