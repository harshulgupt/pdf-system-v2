import logging
import os
import sys
import time

# Ensure absolute imports work when running as `python -m app.worker`
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.cache import get_redis_client
from app.db.database import SessionLocal
from app.models.models import PDFUpload, UploadStatus
from app.repositories.sql_repo import SQLUploadRepository, SQLSearchRepository
from app.services.upload_service import UploadService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - WORKER - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _reset_stale_jobs() -> None:
    """
    On startup, flip any upload stuck in 'processing' back to 'failed'.
    This happens when the worker process was OOM-killed mid-extraction and
    never got a chance to write the final status.
    """
    db = SessionLocal()
    try:
        stale = (
            db.query(PDFUpload)
            .filter(PDFUpload.status == UploadStatus.processing)
            .all()
        )
        if stale:
            logger.warning(
                "Found %d stale 'processing' upload(s) — marking as failed.", len(stale)
            )
            for upload in stale:
                upload.status = UploadStatus.failed
            db.commit()
    except Exception as e:
        logger.error("Failed to reset stale jobs: %s", e)
    finally:
        db.close()


def process_queue() -> None:
    redis_client = get_redis_client()
    if not redis_client:
        logger.error("Redis is unavailable. Worker cannot start.")
        # Keep retrying so Railway restart policy can recover
        while True:
            time.sleep(10)
            redis_client = get_redis_client()
            if redis_client:
                break

    _reset_stale_jobs()

    logger.info("Worker ready. Listening on 'pdf_processing_queue'...")

    while True:
        try:
            # BRPOP blocks with zero CPU until a job arrives
            result = redis_client.brpop("pdf_processing_queue", timeout=0)
            if not result:
                continue

            _, item = result
            upload_id = item.decode("utf-8") if isinstance(item, bytes) else item
            logger.info("Received job upload_id=%s", upload_id)

            # Fresh DB session per job — avoids stale connection issues
            db = SessionLocal()
            try:
                upload_repo = SQLUploadRepository(db)
                search_repo = SQLSearchRepository(db)
                service = UploadService(upload_repo, search_repo)
                service._process_upload_async(upload_id)
            except Exception as e:
                logger.error("Job failed for upload_id=%s: %s", upload_id, e, exc_info=True)
            finally:
                db.close()

        except Exception as e:
            logger.error("Worker loop error (Redis reboot?): %s", e)
            time.sleep(2)


if __name__ == "__main__":
    process_queue()
