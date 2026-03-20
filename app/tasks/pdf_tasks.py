"""
Celery tasks — runs in the worker process, completely separate from the web server.

THE PARALLEL PAGE PROCESSING APPROACH:
  Instead of reading all PDF pages one by one sequentially, we split pages
  into batches and process each batch in a separate thread using
  ThreadPoolExecutor. For a 500-page PDF with 4 workers:
    Sequential:  page1 → page2 → page3 … page500  (one pipeline)
    Parallel:    [p1-p125] [p126-p250] [p251-p375] [p376-p500]  (4 pipelines)

  Why threads and not processes?
    pypdf's PdfReader holds the file in memory — sharing it across processes
    requires serialization (slow). Threads share memory directly and are
    fine here because the bottleneck is I/O (reading page data), not CPU.
    For true CPU-bound parsing, multiprocessing would be better but adds
    complexity. This is the honest trade-off to explain to the interviewer.
"""
import io
import os
import pypdf
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.celery_app import celery
from app.db.database import SessionLocal
from app.db.models import PDFChunk
from app.repositories.chunk_repository import SQLChunkRepository
from app.storage.storage import get_storage

TEXT_CHUNK_CHARS = 2000
OVERLAP_CHARS    = 200
MAX_WORKERS      = 4  # parallel page processing workers


def _extract_pages_range(pdf_bytes: bytes, start: int, end: int) -> str:
    """Extract text from a range of pages. Runs in a thread."""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(
        reader.pages[i].extract_text() or ""
        for i in range(start, min(end, len(reader.pages)))
    )


def _extract_text_parallel(pdf_bytes: bytes) -> str:
    """
    Split pages into batches and extract text in parallel threads.
    Falls back to sequential if parallel fails.
    """
    try:
        reader     = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)

        if total_pages == 0:
            return ""

        # Split pages evenly across workers
        batch_size = max(1, total_pages // MAX_WORKERS)
        batches    = [
            (i, min(i + batch_size, total_pages))
            for i in range(0, total_pages, batch_size)
        ]

        results = {}
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_extract_pages_range, pdf_bytes, start, end): start
                for start, end in batches
            }
            for future in as_completed(futures):
                start_page = futures[future]
                results[start_page] = future.result()

        # Reassemble in page order
        return "\n".join(results[start] for start, _ in sorted(batches))

    except Exception:
        # Fallback: sequential extraction
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception:
            return ""


def _split_text(text: str, size: int, overlap: int):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


@celery.task(bind=True, name="process_pdf")
def process_pdf(self, upload_id: str):
    """
    Celery task — runs in the worker process after all chunks are uploaded.

    bind=True gives us access to `self` so we can retry on failure.
    name="process_pdf" gives it a human-readable name in monitoring tools.

    Steps:
      1. assembling — concatenate binary chunks into complete PDF
      2. indexing   — extract text in parallel, bulk insert passages to DB
    """
    db      = SessionLocal()
    storage = get_storage()

    try:
        repo    = SQLChunkRepository(db)
        session = repo.get_session(upload_id)
        if not session:
            return {"error": f"Unknown upload_id: {upload_id}"}

        # Step 1: assemble binary chunks → complete PDF
        repo.set_status(upload_id, "assembling")
        assembled_path = storage.assemble(upload_id, session.total_chunks)

        # Step 2: extract text in parallel across page batches
        repo.set_status(upload_id, "indexing")
        pdf_bytes = storage.read_file(assembled_path)
        full_text = _extract_text_parallel(pdf_bytes)

        passages = (
            _split_text(full_text, TEXT_CHUNK_CHARS, OVERLAP_CHARS)
            if full_text
            else ["[no extractable text — scanned or image-only PDF]"]
        )

        # Step 3: bulk insert all passages in one transaction
        repo.bulk_save_text_chunks([
            PDFChunk(
                upload_id     = upload_id,
                filename      = session.filename,
                passage_index = i,
                content       = text,
            )
            for i, text in enumerate(passages)
        ])

        repo.set_status(upload_id, "indexed")
        return {"status": "indexed", "passages": len(passages)}

    except Exception as exc:
        db.query(__import__('app.db.models', fromlist=['UploadSession']).UploadSession)\
          .filter_by(upload_id=upload_id)\
          .update({"status": "failed"})
        db.commit()
        # Retry up to 3 times for transient failures
        raise self.retry(exc=exc, countdown=60)

    finally:
        db.close()
