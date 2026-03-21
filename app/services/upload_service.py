"""
Upload service — orchestrates the write path.
Controllers call this; this calls repositories and storage service.
"""
import uuid
import logging
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.db_models import UploadStatus
from app.repositories.upload_repository import UploadRepository
from app.services.storage_service import generate_presigned_upload_url

logger = logging.getLogger(__name__)


class UploadService:
    def __init__(self, db: Session):
        self.repo = UploadRepository(db)

    def init_upload(self, filename: str, total_chunks: int) -> dict:
        """
        Step 1 of the write path.
        Creates the upload record and returns one presigned S3 URL per chunk.
        The frontend will PUT each chunk directly to its URL — our server is never
        in the data path for the actual bytes.
        """
        if total_chunks < 1:
            raise HTTPException(status_code=400, detail="total_chunks must be >= 1")
        if total_chunks > 5000:
            raise HTTPException(status_code=400, detail="total_chunks exceeds maximum (5000)")

        upload_id = str(uuid.uuid4())

        # Pre-create all chunk DB records so we track every slot
        presigned_urls = []
        for idx in range(total_chunks):
            s3_key = f"uploads/{upload_id}/chunk_{idx:05d}"
            self.repo.create_chunk_record(upload_id, idx, s3_key)
            url = generate_presigned_upload_url(s3_key)
            presigned_urls.append({"chunk_index": idx, "url": url, "s3_key": s3_key})

        self.repo.create_upload(upload_id, filename, total_chunks)

        return {
            "upload_id":    upload_id,
            "total_chunks": total_chunks,
            "presigned_urls": presigned_urls,
        }

    def confirm_complete(self, upload_id: str) -> dict:
        """
        Step 2: frontend calls this after all chunks are in S3.
        We validate and trigger the extraction background task.
        """
        upload = self.repo.get_upload(upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        if upload.status != UploadStatus.pending:
            raise HTTPException(
                status_code=409,
                detail=f"Upload is already in status '{upload.status}'"
            )

        return {"upload_id": upload_id, "status": "processing_queued"}

    def get_status(self, upload_id: str) -> dict:
        upload = self.repo.get_upload(upload_id)
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")
        return {
            "upload_id":       upload.id,
            "filename":        upload.filename,
            "status":          upload.status,
            "total_chunks":    upload.total_chunks,
            "uploaded_chunks": upload.uploaded_chunks,
        }
