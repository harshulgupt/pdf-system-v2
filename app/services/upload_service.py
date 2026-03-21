"""
Upload service — owns the write path business logic.

Flow:
  1. init_upload()    → client calls first; gets back presigned URLs for all chunks
  2. confirm_chunk()  → client calls after each successful PUT to R2
  3. complete_upload()→ client calls when all chunks uploaded; triggers extraction

Trade-off on synchronous processing:
  We process the PDF synchronously inside complete_upload.
  For a true 20 GB file this should be moved to a background queue (SQS / Railway
  cron / RQ). Kept sync here per "bare minimum" requirement.
"""
import io

import pypdf

from app.models.models import UploadStatus
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.services.storage import generate_presigned_put_url, download_chunk_bytes


class UploadService:

    def __init__(
        self,
        upload_repo: AbstractUploadRepository,
        search_repo: AbstractSearchRepository,
    ):
        self.upload_repo = upload_repo
        self.search_repo = search_repo

    def init_upload(self, filename: str, total_chunks: int) -> dict:
        """
        Creates the upload record and returns one presigned PUT URL per chunk.
        The browser PUTs each chunk directly to R2 — bytes never pass through
        our API server.
        """
        upload = self.upload_repo.create_upload(filename, total_chunks)
        presigned_urls = []

        for i in range(total_chunks):
            r2_key = f"uploads/{upload.id}/chunk_{i:06d}"
            url = generate_presigned_put_url(r2_key)
            chunk_record = self.upload_repo.save_chunk_record(upload.id, i, r2_key)
            presigned_urls.append({
                "chunk_index": i,
                "r2_key": r2_key,
                "chunk_record_id": chunk_record.id,
                "upload_url": url,
            })

        self.upload_repo.set_status(upload.id, UploadStatus.uploading)
        return {"upload_id": upload.id, "chunks": presigned_urls}

    def confirm_chunk(self, upload_id: str, chunk_index: int) -> dict:
        """
        Client calls this after a successful PUT to R2.
        Increments the received counter so we know when all chunks are in.
        """
        upload = self.upload_repo.increment_received_chunks(upload_id)
        return {
            "upload_id": upload_id,
            "received": upload.received_chunks,
            "total": upload.total_chunks,
            "all_received": upload.received_chunks >= upload.total_chunks,
        }

    def complete_upload(self, upload_id: str) -> dict:
        """
        Client calls this when all chunks are confirmed.
        Pulls each chunk from R2, extracts text, stores it for search.
        """
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")

        self.upload_repo.set_status(upload_id, UploadStatus.processing)

        try:
            self._process_upload(upload)
            self.upload_repo.set_status(upload_id, UploadStatus.ready)
            return {"upload_id": upload_id, "status": "ready"}
        except Exception as e:
            self.upload_repo.set_status(upload_id, UploadStatus.failed)
            raise RuntimeError(f"Processing failed: {e}") from e

    def _process_upload(self, upload) -> None:
        """
        Downloads each raw chunk from R2 in order, reassembles into a full PDF,
        extracts text per page group, saves to DB for search.

        Memory note: assembles the full PDF in memory. Fine up to a few GB on a
        standard server. For true 20 GB: stream page ranges via a worker queue.
        """
        chunks = sorted(upload.chunks, key=lambda c: c.chunk_index)
        pdf_bytes = b"".join(download_chunk_bytes(c.r2_key) for c in chunks)

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)
        pages_per_chunk = max(1, total_pages // max(len(chunks), 1))

        for chunk_record in chunks:
            start_page = chunk_record.chunk_index * pages_per_chunk
            end_page = min(start_page + pages_per_chunk, total_pages)
            text = "\n".join(
                reader.pages[p].extract_text() or ""
                for p in range(start_page, end_page)
            )
            self.search_repo.save_extracted_text(chunk_record.id, text)

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
