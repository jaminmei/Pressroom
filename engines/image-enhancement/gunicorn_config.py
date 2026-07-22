# Gunicorn configuration for Image Enhancement engine

bind = "0.0.0.0:8080"
workers = 2  # Can use multiple workers for CPU-bound image processing
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 180  # 3 minutes for large images
keepalive = 120
preload_app = False

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
