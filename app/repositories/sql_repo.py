"""
SQL (Postgres / SQLite) implementation of the repository interfaces.

To swap to MongoDB or Pinecone:
  1. Create app/repositories/mongo_repo.py implementing the same ABCs.
  2. Change get_upload_repo() and get_search_repo() in app/dependencies.py.
  That's the only change needed outside this file.
"""
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.models import PDFUpload, PDFChunk, UploadStatus
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository


class SQLUploadRepository(AbstractUploadRepository):

    def __init__(self, db: Session):
        self.db = db

    def create_upload(self, filename: str, total_chunks: int) -> PDFUpload:
        upload = PDFUpload(filename=filename, total_chunks=total_chunks)
        self.db.add(upload)
        self.db.commit()
        self.db.refresh(upload)
        return upload

    def get_upload(self, upload_id: str) -> Optional[PDFUpload]:
        return self.db.query(PDFUpload).filter(PDFUpload.id == upload_id).first()

    def increment_received_chunks(self, upload_id: str) -> PDFUpload:
        upload = self.get_upload(upload_id)
        upload.received_chunks += 1
        self.db.commit()
        self.db.refresh(upload)
        return upload

    def set_status(self, upload_id: str, status: UploadStatus) -> PDFUpload:
        upload = self.get_upload(upload_id)
        upload.status = status
        self.db.commit()
        self.db.refresh(upload)
        return upload

    def save_chunk_record(self, upload_id: str, chunk_index: int, r2_key: str) -> PDFChunk:
        chunk = PDFChunk(upload_id=upload_id, chunk_index=chunk_index, r2_key=r2_key)
        self.db.add(chunk)
        self.db.commit()
        self.db.refresh(chunk)
        return chunk


class SQLSearchRepository(AbstractSearchRepository):

    def __init__(self, db: Session):
        self.db = db

    def save_extracted_text(self, chunk_id: str, text: str) -> None:
        chunk = self.db.query(PDFChunk).filter(PDFChunk.id == chunk_id).first()
        chunk.extracted_text = text
        self.db.commit()

    def search(self, query: str, upload_id: Optional[str], limit: int) -> list[dict]:
        """
        Postgres path: uses GIN full-text index (fast, scales to millions of chunks).
        SQLite fallback: LIKE (dev only — never use in prod on large data).

        Trade-off documented here:
          Postgres FTS — fast, ranked, handles 20 GB corpus well.
          Vector DB (Pinecone/pgvector) — needed for semantic/embedding search.
          This implementation is FTS; swap search_repo for vector search if needed.
        """
        db = self.db

        is_postgres = "postgresql" in str(db.bind.url) if hasattr(db, 'bind') and db.bind else False

        if is_postgres:
            base_sql = """
                SELECT
                    c.id            AS chunk_id,
                    c.upload_id,
                    c.chunk_index,
                    u.filename,
                    ts_headline('english', c.extracted_text, q, 'MaxWords=50, MinWords=20') AS snippet,
                    ts_rank(to_tsvector('english', c.extracted_text), q) AS rank
                FROM pdf_chunks c
                JOIN pdf_uploads u ON u.id = c.upload_id,
                     to_tsquery('english', :tsquery) q
                WHERE to_tsvector('english', c.extracted_text) @@ q
            """
            params = {"tsquery": " & ".join(query.split()), "limit": limit}
            if upload_id:
                base_sql += " AND c.upload_id = :upload_id"
                params["upload_id"] = upload_id
            base_sql += " ORDER BY rank DESC LIMIT :limit"
            rows = db.execute(text(base_sql), params).fetchall()
        else:
            # SQLite fallback — fine for dev, not for prod
            q = self.db.query(PDFChunk).join(PDFUpload)
            if upload_id:
                q = q.filter(PDFChunk.upload_id == upload_id)
            q = q.filter(PDFChunk.extracted_text.ilike(f"%{query}%")).limit(limit)
            rows_orm = q.all()
            return [
                {
                    "chunk_id": r.id,
                    "upload_id": r.upload_id,
                    "chunk_index": r.chunk_index,
                    "filename": r.upload.filename,
                    "snippet": r.extracted_text[:300],
                }
                for r in rows_orm
            ]

        return [
            {
                "chunk_id": row.chunk_id,
                "upload_id": row.upload_id,
                "chunk_index": row.chunk_index,
                "filename": row.filename,
                "snippet": row.snippet,
            }
            for row in rows
        ]
