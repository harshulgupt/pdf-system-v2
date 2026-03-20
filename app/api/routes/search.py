from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import PDFChunk
from app.repositories.chunk_repository import SQLChunkRepository
from app.services.pdf_service import PDFService
from app.storage.storage import get_storage

router = APIRouter()

SNIPPET_WINDOW = 200  # characters before and after the match


def extract_snippet(content: str, query: str, window: int = SNIPPET_WINDOW) -> str:
    """
    Instead of always returning the first 400 chars, find where the search
    term actually appears and return `window` chars around that position.
    This guarantees the matched term is visible in the snippet.

    If the term isn't found (shouldn't happen but defensive), fall back
    to the beginning of the passage.
    """
    pos = content.lower().find(query.lower())
    if pos == -1:
        # Fallback — term not found, show start of passage
        return content[:window * 2] + ("…" if len(content) > window * 2 else "")

    start = max(0, pos - window)
    end   = min(len(content), pos + len(query) + window)
    snippet = content[start:end]

    # Add ellipsis to show the user this is a mid-passage extract
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet = snippet + "…"

    return snippet


@router.get("/search")
def search(
    q:     str = Query(..., min_length=1, max_length=500),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    results = PDFService(SQLChunkRepository(db), get_storage()).search(q.strip(), limit)
    return {
        "query":   q,
        "total":   len(results),
        "results": [
            {
                "chunk_id":      r.id,
                "upload_id":     r.upload_id,
                "filename":      r.filename,
                "passage_index": r.passage_index,
                "snippet":       extract_snippet(r.content, q.strip()),
            }
            for r in results
        ],
    }


@router.get("/debug")
def debug(db: Session = Depends(get_db)):
    rows = db.query(PDFChunk).all()
    return {
        "total_text_chunks": len(rows),
        "chunks": [
            {
                "filename":       r.filename,
                "passage_index":  r.passage_index,
                "content_length": len(r.content),
                "preview":        r.content[:150],
            }
            for r in rows
        ],
    }
