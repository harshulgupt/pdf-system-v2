"""
Celery app — the task queue that runs PDF processing in a separate process.

Why Celery instead of FastAPI BackgroundTasks?
  BackgroundTasks runs inside the web server process. For CPU-heavy work
  like parsing a 20GB PDF, it starves the server — incoming HTTP requests
  queue up waiting for CPU. Celery workers are completely separate processes
  that can be scaled horizontally without touching the web server.

  Web server  →  drops task in Redis queue  →  Celery worker picks it up
  Web server stays free to handle new requests immediately.

Broker:  Redis (message queue — web server puts tasks here)
Backend: Redis (result store — workers write status here)
"""
import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery = Celery(
    "pdf_processor",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Retry failed tasks up to 3 times with 60s delay
    task_max_retries=3,
    task_default_retry_delay=60,
)

# Import tasks so Celery discovers them on worker startup
from app.tasks import pdf_tasks  # noqa: F401, E402
