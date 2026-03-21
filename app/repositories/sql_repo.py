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
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        upload.received_chunks += 1
        self.db.commit()
        self.db.refresh(upload)
        return upload

    def set_status(self, upload_id: str, status: UploadStatus) -> PDFUpload:
        upload = self.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
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
        self.db.query(PDFChunk).filter(PDFChunk.id == chunk_id).update(
            {"extracted_text": text}
        )
        self.db.commit()

    def search(self, query: str, upload_id: Optional[str], limit: int) -> list[dict]:
        db = self.db
        is_postgres = "postgresql" in str(db.get_bind().url)

        if is_postgres:
            # Filter out stop words and non-alpha tokens for tsquery
            words = [w for w in query.split() if w.isalpha()]
            tsquery_str = " & ".join(words)

            # If all words are stop words, fall back to ILIKE
            if not tsquery_str:
                base_sql = """
                    SELECT
                        c.id            AS chunk_id,
                        c.upload_id,
                        c.chunk_index,
                        u.filename,
                        substring(c.extracted_text, 1, 300) AS snippet
                    FROM pdf_chunks c
                    JOIN pdf_uploads u ON u.id = c.upload_id
                    WHERE c.extracted_text ILIKE :pattern
                """
                params = {"pattern": f"%{query}%", "limit": limit}
                if upload_id:
                    base_sql += " AND c.upload_id = :upload_id"
                    params["upload_id"] = upload_id
                base_sql += " LIMIT :limit"
                rows = db.execute(text(base_sql), params).fetchall()
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

            # Normal FTS path
            base_sql = """
                SELECT
                    c.id            AS chunk_id,
                    c.upload_id,
                    c.chunk_index,
                    u.filename,
                    ts_headline(
                        'english',
                        c.extracted_text,
                        q,
                        'MaxWords=60, MinWords=20, MaxFragments=3, FragmentDelimiter=" ... "'
                    ) AS snippet,
                    ts_rank(to_tsvector('english', c.extracted_text), q) AS rank
                FROM pdf_chunks c
                JOIN pdf_uploads u ON u.id = c.upload_id,
                     to_tsquery('english', :tsquery) q
                WHERE to_tsvector('english', c.extracted_text) @@ q
            """
            params = {"tsquery": tsquery_str, "limit": limit}
            if upload_id:
                base_sql += " AND c.upload_id = :upload_id"
                params["upload_id"] = upload_id
            base_sql += " ORDER BY rank DESC LIMIT :limit"
            rows = db.execute(text(base_sql), params).fetchall()

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

        # SQLite fallback
        q = self.db.query(PDFChunk).join(PDFUpload)
        if upload_id:
            q = q.filter(PDFChunk.upload_id == upload_id)
        q = q.filter(PDFChunk.extracted_text.ilike(f"%{query}%")).limit(limit)
        rows_orm = q.all()

        results = []
        for r in rows_orm:
            text_lower = r.extracted_text.lower()
            query_lower = query.lower()
            pos = text_lower.find(query_lower)
            if pos == -1:
                snippet = r.extracted_text[:300]
            else:
                start = max(0, pos - 100)
                end = min(len(r.extracted_text), pos + len(query) + 200)
                snippet = (
                    ("..." if start > 0 else "")
                    + r.extracted_text[start:end]
                    + ("..." if end < len(r.extracted_text) else "")
                )
            results.append({
                "chunk_id": r.id,
                "upload_id": r.upload_id,
                "chunk_index": r.chunk_index,
                "filename": r.upload.filename,
                "snippet": snippet,
            })

        return results