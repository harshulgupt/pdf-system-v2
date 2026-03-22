import os
import sys
import time
import logging

# Ensure absolute imports work when running autonomously
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.cache import get_redis_client
from app.services.upload_service import UploadService
from app.repositories.sql_repo import SQLUploadRepository, SQLSearchRepository
from app.db.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s - WORKER - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def process_queue():
    redis_client = get_redis_client()
    if not redis_client:
        logger.error("Redis is unavailable. Worker cannot connect.")
        time.sleep(5)
        return

    logger.info("Worker started securely. Bound to 'pdf_processing_queue' (BRPOP loop)...")
    
    while True:
        try:
            # BRPOP blocks entirely using zero CPU until an item is pushed, timeout=0 means indefinite
            result = redis_client.brpop("pdf_processing_queue", timeout=0)
            if not result:
                continue
                
            _, item = result
            upload_id = item.decode('utf-8') if isinstance(item, bytes) else item
            logger.info(f"Popped job from queue. Starting extraction for upload_id: {upload_id}")
            
            # Using independent Database Sessions per job guarantees connection health on 512MB RAM
            db = SessionLocal()
            try:
                upload_repo = SQLUploadRepository(db)
                search_repo = SQLSearchRepository(db)
                service = UploadService(upload_repo, search_repo)
                
                # Execute extraction synchronously in this isolated daemon
                service._process_upload_async(upload_id)
                logger.info(f"Successfully finished extraction for upload_id: {upload_id}")
            except Exception as e:
                logger.error(f"Extraction failed for {upload_id}: {e}")
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Worker encountered connection error (Redis reboot?): {e}")
            time.sleep(2)


if __name__ == "__main__":
    process_queue()
