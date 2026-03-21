from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.models import PDFUpload, PDFChunk, UploadStatus
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "were", "been", "has", "have", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "this", "that", "these",
    "those", "i", "you", "he", "she", "we", "they", "not", "no", "so",
    "if", "up", "out", "about", "into", "than", "then", "its", "my",
    "your", "his", "her", "our", "their"
}


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

    def _count_occurrences(self, text: str, query: str) -> int:
        """Count how many times query appears in text (case-insensitive)."""
        if not text or not query:
            return 0
        return text.lower().count(query.lower())

    def _extract_snippet(self, full_text: str, query: str) -> str:
        """Extract a snippet around the first occurrence of query."""
        pos = full_text.lower().find(query.lower())
        if pos == -1:
            return full_text[:400]
        start = max(0, pos - 150)
        end = min(len(full_text), pos + 400)
        return (
            ("..." if start > 0 else "")
            + full_text[start:end]
            + ("..." if end < len(full_text) else "")
        )

    def _ilike_search(self, db, query: str, upload_id: Optional[str], limit: int) -> dict:
        """ILIKE fallback for stop words and short queries."""
        # Count total occurrences across ALL chunks
        count_sql = """
            SELECT COALESCE(SUM(
                (LENGTH(c.extracted_text) - LENGTH(REPLACE(LOWER(c.extracted_text), LOWER(:query), '')))
                / LENGTH(:query)
            ), 0) AS total_occurrences
            FROM pdf_chunks c
            JOIN pdf_uploads u ON u.id = c.upload_id
            WHERE c.extracted_text ILIKE :pattern
        """
        params_count = {"query": query, "pattern": f"%{query}%"}
        if upload_id:
            count_sql += " AND c.upload_id = :upload_id"
            params_count["upload_id"] = upload_id

        total_occurrences = int(db.execute(text(count_sql), params_count).scalar() or 0)

        # Fetch top chunks
        base_sql = """
            SELECT
                c.id        AS chunk_id,
                c.upload_id,
                c.chunk_index,
                u.filename,
                c.extracted_text AS full_text
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

        results = []
        for row in rows:
            full_text = row.full_text or ""
            count_in_chunk = self._count_occurrences(full_text, query)
            snippet = self._extract_snippet(full_text, query)
            results.append({
                "chunk_id": row.chunk_id,
                "upload_id": row.upload_id,
                "chunk_index": row.chunk_index,
                "filename": row.filename,
                "snippet": snippet,
                "occurrences_in_chunk": count_in_chunk,
            })

        return {
            "total_occurrences": total_occurrences,
            "results": results,
        }

    def search(self, query: str, upload_id: Optional[str], limit: int) -> dict:
        db = self.db
        is_postgres = "postgresql" in str(db.get_bind().url)

        if is_postgres:
            words = query.lower().split()
            fts_words = [w for w in words if w.isalpha() and w not in STOP_WORDS]
            tsquery_str = " & ".join(fts_words)

            if not tsquery_str:
                return self._ilike_search(db, query, upload_id, limit)

            # Count total occurrences across ALL matching chunks
            count_sql = """
                SELECT COALESCE(SUM(
                    (LENGTH(c.extracted_text) - LENGTH(REPLACE(LOWER(c.extracted_text), LOWER(:query), '')))
                    / NULLIF(LENGTH(:query), 0)
                ), 0) AS total_occurrences
                FROM pdf_chunks c
                JOIN pdf_uploads u ON u.id = c.upload_id,
                     to_tsquery('english', :tsquery) q
                WHERE to_tsvector('english', c.extracted_text) @@ q
            """
            params_count = {"query": fts_words[0], "tsquery": tsquery_str}
            if upload_id:
                count_sql += " AND c.upload_id = :upload_id"
                params_count["upload_id"] = upload_id

            total_occurrences = int(db.execute(text(count_sql), params_count).scalar() or 0)

            # Fetch top 10 chunks by relevance
            base_sql = """
                SELECT
                    c.id            AS chunk_id,
                    c.upload_id,
                    c.chunk_index,
                    u.filename,
                    c.extracted_text AS full_text,
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

            results = []
            for row in rows:
                full_text = row.full_text or ""
                count_in_chunk = self._count_occurrences(full_text, fts_words[0])
                snippet = self._extract_snippet(full_text, fts_words[0])
                results.append({
                    "chunk_id": row.chunk_id,
                    "upload_id": row.upload_id,
                    "chunk_index": row.chunk_index,
                    "filename": row.filename,
                    "snippet": snippet,
                    "occurrences_in_chunk": count_in_chunk,
                })

            return {
                "total_occurrences": total_occurrences,
                "results": results,
            }

        # SQLite fallback
        q = self.db.query(PDFChunk).join(PDFUpload)
        if upload_id:
            q = q.filter(PDFChunk.upload_id == upload_id)
        q = q.filter(PDFChunk.extracted_text.ilike(f"%{query}%")).limit(limit)
        rows_orm = q.all()

        total_occurrences = sum(
            self._count_occurrences(r.extracted_text or "", query) for r in rows_orm
        )

        results = []
        for r in rows_orm:
            full_text = r.extracted_text or ""
            results.append({
                "chunk_id": r.id,
                "upload_id": r.upload_id,
                "chunk_index": r.chunk_index,
                "filename": r.upload.filename,
                "snippet": self._extract_snippet(full_text, query),
                "occurrences_in_chunk": self._count_occurrences(full_text, query),
            })

        return {
            "total_occurrences": total_occurrences,
            "results": results,
        }