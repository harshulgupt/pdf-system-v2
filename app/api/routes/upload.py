"""
Upload controller — thin layer. Validates input, calls service, returns response.
No business logic here. No direct DB calls.
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel, Field

from app.dependencies import get_upload_repo, get_search_repo
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.services.upload_service import UploadService

router = APIRouter(prefix="/upload", tags=["upload"])


class InitUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    total_chunks: int = Field(..., gt=0, le=10000)


def _get_service(
    upload_repo: AbstractUploadRepository = Depends(get_upload_repo),
    search_repo: AbstractSearchRepository = Depends(get_search_repo),
) -> UploadService:
    return UploadService(upload_repo, search_repo)


@router.post("/init", status_code=status.HTTP_201_CREATED)
def init_upload(
    body: InitUploadRequest,
    service: UploadService = Depends(_get_service),
):
    """
    Step 1 — client calls this before uploading anything.
    Returns upload_id and r2_key for each chunk.
    """
    if not body.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    return service.init_upload(body.filename, body.total_chunks)


@router.post("/chunk")
def upload_chunk_proxy(
    file: UploadFile = File(...),
    r2_key: str = Form(...),
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    service: UploadService = Depends(_get_service),
):
    """
    Step 2 — browser POSTs each chunk here as multipart form data.
    We forward the bytes to B2 and confirm receipt in the DB.
    This proxy approach avoids CORS issues with direct browser→B2 uploads.
    """
    try:
        data = file.file.read()
        service.upload_chunk(r2_key, data)
        return service.confirm_chunk(upload_id, chunk_index)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{upload_id}/complete")
def complete_upload(
    upload_id: str,
    service: UploadService = Depends(_get_service),
):
    """
    Step 3 — client calls after all chunks are uploaded.
    Triggers text extraction and indexing.
    """
    try:
        return service.complete_upload(upload_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{upload_id}/status")
def upload_status(
    upload_id: str,
    service: UploadService = Depends(_get_service),
):
    try:
        return service.get_status(upload_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
