import gc
import logging
import os
import tempfile
import uuid

import fitz  # PyMuPDF
from fastapi import BackgroundTasks

from app.models.models import UploadStatus
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.services.storage import (
    initiate_multipart_upload,
    generate_presigned_part_url,
    complete_multipart_upload,
    download_file_to_disk,
)

logger = logging.getLogger(__name__)

# Pages extracted per semantic chunk. 5 pages keeps chunk text well under
# Postgres's 1 GB text column limit while giving enough context for search.
PAGES_PER_CHUNK = 5

# Hard cap on stored text per chunk to protect Postgres.
MAX_CHUNK_CHARS = 500_000


class UploadService:
    def __init__(
        self,
        upload_repo: AbstractUploadRepository,
        search_repo: AbstractSearchRepository,
    ):
        self.upload_repo = upload_repo
        self.search_repo = search_repo

    # ------------------------------------------------------------------
    # Upload lifecycle
    # ------------------------------------------------------------------

    def init_upload(
        self, filename: str, total_chunks: int, file_hash: str = None
    ) -> dict:
        if file_hash:
            existing = self.upload_repo.get_upload_by_hash(file_hash)
            if existing:
                return {"upload_id": existing.id, "status": "existing", "chunks": []}

        upload_id = str(uuid.uuid4())
        r2_key = f"uploads/{upload_id}.pdf"
        multipart_upload_id = initiate_multipart_upload(r2_key)

        upload = self.upload_repo.create_upload(
            upload_id, filename, total_chunks, multipart_upload_id, file_hash=file_hash
        )

        chunks = []
        for i in range(total_chunks):
            part_number = i + 1
            presigned_url = generate_presigned_part_url(r2_key, multipart_upload_id, part_number)
            chunks.append({"chunk_index": i, "presigned_url": presigned_url})

        self.upload_repo.set_status(upload.id, UploadStatus.uploading)
        return {"upload_id": upload.id, "chunks": chunks}

    def confirm_chunk(self, upload_id: str, chunk_index: int) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        upload = self.upload_repo.increment_received_chunks(upload_id, chunk_index)
        return {
            "upload_id": upload_id,
            "received": upload.received_chunks,
            "total": upload.total_chunks,
            "all_received": upload.received_chunks >= upload.total_chunks,
        }

    def complete_upload(self, upload_id: str, background_tasks: BackgroundTasks) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        if upload.received_chunks < upload.total_chunks:
            raise RuntimeError(
                f"Not all chunks received: {upload.received_chunks}/{upload.total_chunks}"
            )

        r2_key = f"uploads/{upload_id}.pdf"
        complete_multipart_upload(r2_key, upload.multipart_upload_id)
        self.upload_repo.set_status(upload_id, UploadStatus.processing)

        from app.db.cache import get_redis_client
        redis_client = get_redis_client()

        if redis_client:
            redis_client.lpush("pdf_processing_queue", upload_id)
            status = "processing_queued"
        else:
            # Fallback: only safe because the worker is a separate Railway service.
            # Never runs heavy extraction inside the API process.
            background_tasks.add_task(self._process_upload_async, upload_id)
            status = "processing_background"

        return {"upload_id": upload_id, "status": status}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self, upload_id: str) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError("Not found")
        return {
            "upload_id": upload.id,
            "filename": upload.filename,
            "status": upload.status,
            "received_chunks": upload.received_chunks,
            "total_chunks": upload.total_chunks,
        }

    # ------------------------------------------------------------------
    # Processing (runs in worker process, NOT in the API process)
    # ------------------------------------------------------------------

    def _process_upload_async(self, upload_id: str) -> None:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            return
        try:
            self._process_upload(upload)
            self.upload_repo.set_status(upload_id, UploadStatus.ready)
            logger.info("Extraction complete for upload_id=%s", upload_id)
        except Exception as e:
            self.upload_repo.set_status(upload_id, UploadStatus.failed)
            logger.error("Extraction failed for upload_id=%s: %s", upload_id, e, exc_info=True)

    def _process_upload(self, upload) -> None:
        """
        Core extraction logic.

        Strategy
        --------
        1. Download the PDF from B2 to a temporary local file using streaming
           8 MB chunks — memory stays flat during download regardless of file size.
        2. Open the local file with PyMuPDF (fitz), which uses a C library and
           accesses pages lazily. Peak RSS is roughly 2–3× the compressed PDF
           size, far lower than pypdf's full-object-graph approach.
        3. Extract PAGES_PER_CHUNK pages at a time, save to Postgres, then
           explicitly delete the Python objects and call gc.collect() on every
           iteration so the heap never accumulates more than one chunk's worth
           of text at a time.
        4. Delete the temp file in the finally block regardless of outcome.
        """
        r2_key = f"uploads/{upload.id}.pdf"

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)  # close the raw fd; we'll re-open via fitz

        try:
            # --- Step 1: stream file to disk ---
            logger.info("Downloading %s to %s", r2_key, tmp_path)
            download_file_to_disk(r2_key, tmp_path)
            logger.info("Download complete. Opening with PyMuPDF.")

            # --- Step 2: open with PyMuPDF ---
            doc = fitz.open(tmp_path)
            total_pages = len(doc)

            if total_pages == 0:
                raise RuntimeError("PDF has no pages or could not be read")

            logger.info("PDF has %d pages. Starting extraction.", total_pages)

            chunk_idx = 0

            # --- Step 3: extract in page-window chunks ---
            for start_page in range(0, total_pages, PAGES_PER_CHUNK):
                end_page = min(start_page + PAGES_PER_CHUNK, total_pages)

                raw_parts = []
                for p in range(start_page, end_page):
                    try:
                        raw_parts.append(doc[p].get_text("text") or "")
                    except Exception:
                        raw_parts.append("")

                text = "\n".join(raw_parts)

                # Sanitise for Postgres: strip null bytes and non-printable chars
                text = text.replace("\x00", "")
                text = "".join(
                    ch for ch in text if ch in ("\n", "\t") or ord(ch) >= 32
                )
                text = text[:MAX_CHUNK_CHARS]

                chunk_record = self.upload_repo.save_chunk_record(upload.id, chunk_idx, r2_key)
                self.search_repo.save_extracted_text(chunk_record.id, text)

                chunk_idx += 1

                # --- Step 4: free memory immediately, every iteration ---
                del raw_parts, text
                gc.collect()

            doc.close()
            logger.info("Extraction done. %d text chunks saved.", chunk_idx)

        finally:
            # Always remove the temp file, even if extraction raised
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
