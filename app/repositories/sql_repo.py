from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.models import PDFUpload, PDFChunk, UploadStatus, ReceivedChunk
from sqlalchemy.exc import IntegrityError
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "were", "been", "has", "have", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "this", "that", "these",
    "those", "i", "you", "he", "she", "we", "they", "not", "no", "so",
    "if", "up", "out", "about", "into", "than", "then", "its", "my",
    "your", "his", "her", "our", "their",
}

CONTEXT_CHARS = 60  # characters on each side of a match in a snippet


def _extract_all_snippets(full_text: str, query: str) -> list[str]:
    """Return a context snippet for every occurrence of query in full_text."""
    snippets = []
    text_lower = full_text.lower()
    query_lower = query.lower()
    query_len = len(query)
    start = 0

    while True:
        pos = text_lower.find(query_lower, start)
        if pos == -1:
            break
        snippet_start = max(0, pos - CONTEXT_CHARS)
        snippet_end = min(len(full_text), pos + query_len + CONTEXT_CHARS)
        snippet = (
            ("..." if snippet_start > 0 else "")
            + full_text[snippet_start:snippet_end]
            + ("..." if snippet_end < len(full_text) else "")
        )
        snippets.append(snippet)
        start = pos + query_len

    return snippets


def _count_occurrences(text: str, query: str) -> int:
    if not text or not query:
        return 0
    return text.lower().count(query.lower())


# ---------------------------------------------------------------------------
# Upload repository
# ---------------------------------------------------------------------------

class SQLUploadRepository(AbstractUploadRepository):

    def __init__(self, db: Session):
        self.db = db

    def create_upload(
        self,
        upload_id: str,
        filename: str,
        total_chunks: int,
        multipart_upload_id: str,
        file_hash: Optional[str] = None,
    ) -> PDFUpload:
        upload = PDFUpload(
            id=upload_id,
            filename=filename,
            file_hash=file_hash,
            total_chunks=total_chunks,
            multipart_upload_id=multipart_upload_id,
        )
        self.db.add(upload)
        self.db.commit()
        self.db.refresh(upload)
        return upload

    def get_upload_by_hash(self, file_hash: str) -> Optional[PDFUpload]:
        return (
            self.db.query(PDFUpload)
            .filter(PDFUpload.file_hash == file_hash, PDFUpload.status == UploadStatus.ready)
            .first()
        )

    def get_upload(self, upload_id: str) -> Optional[PDFUpload]:
        return self.db.query(PDFUpload).filter(PDFUpload.id == upload_id).first()

    def increment_received_chunks(self, upload_id: str, chunk_index: int) -> PDFUpload:
        upload = self.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")

        chunk_record = ReceivedChunk(upload_id=upload_id, chunk_index=chunk_index)
        self.db.add(chunk_record)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()  # duplicate chunk — ignore

        count = (
            self.db.query(ReceivedChunk)
            .filter(ReceivedChunk.upload_id == upload_id)
            .count()
        )
        upload.received_chunks = count
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


# ---------------------------------------------------------------------------
# Search repository
# ---------------------------------------------------------------------------

class SQLSearchRepository(AbstractSearchRepository):

    def __init__(self, db: Session):
        self.db = db

    def save_extracted_text(self, chunk_id: str, text: str) -> None:
        self.db.query(PDFChunk).filter(PDFChunk.id == chunk_id).update(
            {"extracted_text": text}
        )
        self.db.commit()

    # -----------------------------------------------------------------------
    # ILIKE fallback (SQLite or Postgres when FTS tokens are empty)
    # -----------------------------------------------------------------------

    def _ilike_search(self, db, query: str, upload_id: Optional[str], limit: int) -> dict:
        count_sql = """
            SELECT COALESCE(SUM(
                (LENGTH(c.extracted_text) - LENGTH(REPLACE(LOWER(c.extracted_text), LOWER(:query), '')))
                / NULLIF(LENGTH(:query), 0)
            ), 0) AS total_occurrences
            FROM pdf_chunks c
            WHERE c.extracted_text ILIKE :pattern
        """
        params_count = {"query": query, "pattern": f"%{query}%"}
        if upload_id:
            count_sql += " AND c.upload_id = :upload_id"
            params_count["upload_id"] = upload_id

        total_occurrences = int(db.execute(text(count_sql), params_count).scalar() or 0)

        base_sql = """
            SELECT c.id AS chunk_id, c.upload_id, c.chunk_index, u.filename, c.extracted_text AS full_text
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
            # Always extract snippets using the full query string
            snippets = _extract_all_snippets(full_text, query)
            results.append({
                "chunk_id": row.chunk_id,
                "upload_id": row.upload_id,
                "chunk_index": row.chunk_index,
                "filename": row.filename,
                "snippets": snippets,
                "occurrences_in_chunk": len(snippets),
            })

        return {"total_occurrences": total_occurrences, "results": results}

    # -----------------------------------------------------------------------
    # Postgres full-text search (primary path)
    # -----------------------------------------------------------------------

    def search(self, query: str, upload_id: Optional[str], limit: int) -> dict:
        db = self.db
        is_postgres = "postgresql" in str(db.get_bind().url)

        if is_postgres:
            words = query.lower().split()
            fts_words = [w for w in words if w.isalpha() and w not in STOP_WORDS]

            # If no usable FTS tokens (all stop words / numbers / punctuation),
            # fall back to ILIKE which searches the literal query string.
            if not fts_words:
                return self._ilike_search(db, query, upload_id, limit)

            # Use plainto_tsquery — Postgres parses the phrase correctly and
            # handles stemming without us having to build tsquery strings manually.
            # This fixes single-word short queries and avoids tsquery syntax errors.
            tsquery_param = " ".join(fts_words)

            # --- occurrence count: use the full raw query for accuracy ---
            count_sql = """
                SELECT COALESCE(SUM(
                    (LENGTH(c.extracted_text) - LENGTH(REPLACE(LOWER(c.extracted_text), LOWER(:raw_query), '')))
                    / NULLIF(LENGTH(:raw_query), 0)
                ), 0) AS total_occurrences
                FROM pdf_chunks c,
                     plainto_tsquery('english', :tsquery) q
                WHERE c.search_vector @@ q
            """
            params_count = {"raw_query": query, "tsquery": tsquery_param}
            if upload_id:
                count_sql += " AND c.upload_id = :upload_id"
                params_count["upload_id"] = upload_id

            total_occurrences = int(db.execute(text(count_sql), params_count).scalar() or 0)

            # --- ranked chunk fetch ---
            base_sql = """
                SELECT
                    c.id AS chunk_id, c.upload_id, c.chunk_index,
                    u.filename, c.extracted_text AS full_text,
                    ts_rank(c.search_vector, q) AS rank
                FROM pdf_chunks c
                JOIN pdf_uploads u ON u.id = c.upload_id,
                     plainto_tsquery('english', :tsquery) q
                WHERE c.search_vector @@ q
            """
            params = {"tsquery": tsquery_param, "limit": limit}
            if upload_id:
                base_sql += " AND c.upload_id = :upload_id"
                params["upload_id"] = upload_id
            base_sql += " ORDER BY rank DESC LIMIT :limit"
            rows = db.execute(text(base_sql), params).fetchall()

            results = []
            for row in rows:
                full_text = row.full_text or ""
                # Always use the full query string for snippet extraction so
                # multi-word queries highlight correctly.
                snippets = _extract_all_snippets(full_text, query)
                # If the full phrase isn't present (stems matched but exact
                # phrase didn't), fall back to first FTS word for highlights.
                if not snippets:
                    snippets = _extract_all_snippets(full_text, fts_words[0])
                results.append({
                    "chunk_id": row.chunk_id,
                    "upload_id": row.upload_id,
                    "chunk_index": row.chunk_index,
                    "filename": row.filename,
                    "snippets": snippets,
                    "occurrences_in_chunk": len(snippets),
                })

            return {"total_occurrences": total_occurrences, "results": results}

        # --- SQLite fallback (local dev only) ---
        q = self.db.query(PDFChunk).join(PDFUpload)
        if upload_id:
            q = q.filter(PDFChunk.upload_id == upload_id)
        q = q.filter(PDFChunk.extracted_text.ilike(f"%{query}%")).limit(limit)
        rows_orm = q.all()

        total_occurrences = sum(_count_occurrences(r.extracted_text or "", query) for r in rows_orm)

        results = []
        for r in rows_orm:
            full_text = r.extracted_text or ""
            snippets = _extract_all_snippets(full_text, query)
            results.append({
                "chunk_id": r.id,
                "upload_id": r.upload_id,
                "chunk_index": r.chunk_index,
                "filename": r.upload.filename,
                "snippets": snippets,
                "occurrences_in_chunk": len(snippets),
            })

        return {"total_occurrences": total_occurrences, "results": results}
