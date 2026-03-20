"""
Upload routes.

POST   /api/upload/start          → register upload session
POST   /api/upload/chunk          → receive one binary chunk, return IMMEDIATELY
GET    /api/upload/status/{id}    → poll: uploading → assembling → indexing → indexed
DELETE /api/clear                 → wipe everything

When the last chunk arrives, we dispatch a Celery task to a separate worker
process instead of running in-process. The web server never touches the PDF
processing — it stays free to handle new requests.
"""
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.repositories.chunk_repository import SQLChunkRepository
from app.services.pdf_service import PDFService
from app.storage.storage import get_storage
from app.tasks.pdf_tasks import process_pdf

router = APIRouter()

MAX_CHUNK_BYTES = 10 * 1024 * 1024


def _service(db: Session) -> PDFService:
    return PDFService(SQLChunkRepository(db), get_storage())


@router.post("/upload/start")
def start_upload(
    upload_id:    str = Form(...),
    filename:     str = Form(...),
    total_chunks: int = Form(...),
    db: Session = Depends(get_db),
):
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted.")
    if total_chunks < 1:
        raise HTTPException(400, "total_chunks must be >= 1.")

    session = _service(db).start_upload(upload_id, filename, total_chunks)
    return {
        "upload_id":    session.upload_id,
        "filename":     session.filename,
        "total_chunks": session.total_chunks,
        "status":       session.status,
    }


@router.post("/upload/chunk")
async def upload_chunk(
    upload_id:     str        = Form(...),
    passage_index: int        = Form(...),
    file:          UploadFile = File(...),
    db:            Session    = Depends(get_db),
):
    """
    Saves binary chunk to disk and returns immediately.
    When last chunk arrives, dispatches Celery task — web server is done,
    worker process takes over. Zero blocking of the HTTP server.
    """
    if passage_index < 0:
        raise HTTPException(400, "passage_index must be >= 0.")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "Empty chunk.")
    if len(data) > MAX_CHUNK_BYTES:
        raise HTTPException(413, f"Chunk too large (max {MAX_CHUNK_BYTES // 1024 // 1024} MB).")

    try:
        svc    = _service(db)
        result = svc.receive_chunk(upload_id, passage_index, data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Last chunk received → dispatch to Celery worker, not BackgroundTasks
    if result["all_received"]:
        process_pdf.delay(upload_id)  # .delay() puts task in Redis queue

    return result


@router.get("/upload/status/{upload_id}")
def upload_status(upload_id: str, db: Session = Depends(get_db)):
    try:
        return _service(db).get_status(upload_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/clear")
def clear_index(db: Session = Depends(get_db)):
    deleted = _service(db).clear_all()
    return {"status": "ok", "chunks_deleted": deleted}
