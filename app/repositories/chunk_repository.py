"""
Repository Pattern — service layer calls only these methods, never SQLAlchemy directly.
To swap DB: write a new class implementing AbstractChunkRepository.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.models import PDFChunk, UploadSession


# ── Abstract interface ────────────────────────────────────────────────────────

class AbstractChunkRepository(ABC):

    # --- Upload session tracking ---
    @abstractmethod
    def create_session(self, upload_id: str, filename: str, total_chunks: int) -> UploadSession: ...

    @abstractmethod
    def get_session(self, upload_id: str) -> Optional[UploadSession]: ...

    @abstractmethod
    def increment_received(self, upload_id: str) -> UploadSession: ...

    @abstractmethod
    def set_status(self, upload_id: str, status: str) -> None: ...

    # --- Text chunks (searchable index) ---
    @abstractmethod
    def save_text_chunk(self, chunk: PDFChunk) -> PDFChunk: ...

    @abstractmethod
    def bulk_save_text_chunks(self, chunks: List[PDFChunk]) -> None: ...

    @abstractmethod
    def search(self, query: str, limit: int) -> List[PDFChunk]: ...

    @abstractmethod
    def delete_by_upload_id(self, upload_id: str) -> int: ...

    @abstractmethod
    def delete_all(self) -> int: ...


# ── SQLite / PostgreSQL implementation ───────────────────────────────────────

class SQLChunkRepository(AbstractChunkRepository):
    def __init__(self, db: Session):
        self.db = db

    # --- Session tracking ---

    def create_session(self, upload_id: str, filename: str, total_chunks: int) -> UploadSession:
        session = UploadSession(
            upload_id=upload_id,
            filename=filename,
            total_chunks=total_chunks,
            received=0,
            status="uploading",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_session(self, upload_id: str) -> Optional[UploadSession]:
        return self.db.query(UploadSession).filter(
            UploadSession.upload_id == upload_id
        ).first()

    def increment_received(self, upload_id: str) -> UploadSession:
        session = self.get_session(upload_id)
        session.received += 1
        self.db.commit()
        self.db.refresh(session)
        return session

    def set_status(self, upload_id: str, status: str) -> None:
        session = self.get_session(upload_id)
        session.status = status
        self.db.commit()

    # --- Text chunks ---

    def save_text_chunk(self, chunk: PDFChunk) -> PDFChunk:
        self.db.add(chunk)
        self.db.commit()
        self.db.refresh(chunk)
        return chunk

    def bulk_save_text_chunks(self, chunks: List[PDFChunk]) -> None:
        """
        Insert all passages in a single transaction.
        500 passages = 1 commit instead of 500 — dramatically faster.
        """
        self.db.bulk_save_objects(chunks)
        self.db.commit()

    def search(self, query: str, limit: int = 20) -> List[PDFChunk]:
        """
        Case-insensitive search via func.lower().
        Postgres upgrade: replace body with tsvector @@ tsquery.
        Elasticsearch upgrade: replace body with ES client call.
        """
        q = query.lower()
        return (
            self.db.query(PDFChunk)
            .filter(func.lower(PDFChunk.content).contains(q))
            .limit(limit)
            .all()
        )

    def delete_by_upload_id(self, upload_id: str) -> int:
        deleted = self.db.query(PDFChunk).filter(
            PDFChunk.upload_id == upload_id
        ).delete(synchronize_session=False)
        self.db.commit()
        return deleted

    def delete_all(self) -> int:
        self.db.query(UploadSession).delete(synchronize_session=False)
        deleted = self.db.query(PDFChunk).delete(synchronize_session=False)
        self.db.commit()
        return deleted
