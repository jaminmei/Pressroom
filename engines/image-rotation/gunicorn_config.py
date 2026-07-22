# Gunicorn configuration for Image Rotation engine

bind = "0.0.0.0:8080"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 60
preload_app = False

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
