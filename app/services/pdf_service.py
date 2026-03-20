"""
Service Layer — all business logic for upload session management and search.
Assembly and indexing has moved to app/tasks/pdf_tasks.py (Celery worker).

Routes call services. Services call repositories + storage.
No SQLAlchemy imports in routes. No HTTP logic here.
"""
import io
import pypdf
from typing import List

from app.db.models import PDFChunk, UploadSession
from app.repositories.chunk_repository import AbstractChunkRepository
from app.storage.storage import AbstractStorage

TEXT_CHUNK_CHARS = 2000
OVERLAP_CHARS    = 200


class PDFService:
    def __init__(self, repo: AbstractChunkRepository, storage: AbstractStorage):
        self.repo    = repo
        self.storage = storage

    def start_upload(self, upload_id: str, filename: str, total_chunks: int) -> UploadSession:
        """Register intent to upload. Client must call this first."""
        return self.repo.create_session(upload_id, filename, total_chunks)

    def receive_chunk(self, upload_id: str, passage_index: int, data: bytes) -> dict:
        """
        Save one binary chunk to disk and update counter.
        Does NOT trigger assembly — the route dispatches a Celery task
        after calling this, keeping concerns cleanly separated.
        """
        session = self.repo.get_session(upload_id)
        if not session:
            raise ValueError(f"Unknown upload_id: {upload_id}")
        if session.status != "uploading":
            raise ValueError(f"Session status is '{session.status}', cannot accept more chunks.")

        self.storage.save_binary_chunk(upload_id, passage_index, data)
        session = self.repo.increment_received(upload_id)

        return {
            "received":     session.received,
            "total":        session.total_chunks,
            "status":       session.status,
            "all_received": session.received == session.total_chunks,
        }

    def get_status(self, upload_id: str) -> dict:
        session = self.repo.get_session(upload_id)
        if not session:
            raise ValueError(f"Unknown upload_id: {upload_id}")
        return {
            "upload_id": upload_id,
            "filename":  session.filename,
            "received":  session.received,
            "total":     session.total_chunks,
            "status":    session.status,
            "done":      session.status == "indexed",
        }

    def search(self, query: str, limit: int = 20) -> List[PDFChunk]:
        return self.repo.search(query, limit)

    def clear_all(self) -> int:
        return self.repo.delete_all()
