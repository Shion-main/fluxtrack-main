"""Gunicorn defaults for the single-EC2 FluxTrack deployment."""
import os

bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")
workers = int(os.getenv("GUNICORN_WORKERS", "3"))
worker_class = "sync"
threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = 60
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
preload_app = False
accesslog = "-"
errorlog = "-"
capture_output = True
