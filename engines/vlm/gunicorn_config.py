# engines/vlm/gunicorn_config.py

bind = "0.0.0.0:8080"
workers = 1  # Single worker for stateless gateway calls
worker_class = "uvicorn.workers.UvicornWorker"
keepalive = 120
timeout = 180  # Allow long-running vision provider calls
