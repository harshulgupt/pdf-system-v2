from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from app.dependencies import get_upload_repo, get_search_repo
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.services.upload_service import UploadService
from app.api.security import RateLimiter

router = APIRouter(prefix="/upload", tags=["upload"])

class InitUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255, pattern=r"^[\w\-. ]+$")
    total_chunks: int = Field(..., gt=0, le=10000)
    file_hash: str = Field(None, description="SHA-256 hash or unique identifier of the file")

class ConfirmChunkRequest(BaseModel):
    upload_id: str
    chunk_index: int

def _get_service(
    upload_repo: AbstractUploadRepository = Depends(get_upload_repo),
    search_repo: AbstractSearchRepository = Depends(get_search_repo),
) -> UploadService:
    return UploadService(upload_repo, search_repo)

@router.post("/init", status_code=status.HTTP_201_CREATED)
def init_upload(
    body: InitUploadRequest, 
    service: UploadService = Depends(_get_service),
    _rate_limit: bool = Depends(RateLimiter(max_requests=20, window_seconds=60))
):
    if not body.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    return service.init_upload(body.filename, body.total_chunks, file_hash=body.file_hash)

@router.post("/chunk/confirm")
def confirm_chunk(
    body: ConfirmChunkRequest, 
    service: UploadService = Depends(_get_service),
    _rate_limit: bool = Depends(RateLimiter(max_requests=600, window_seconds=60))
):
    """Called by browser after successfully putting a chunk to B2."""
    try:
        return service.confirm_chunk(body.upload_id, body.chunk_index)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{upload_id}/complete")
def complete_upload(
    upload_id: str, 
    background_tasks: BackgroundTasks, 
    service: UploadService = Depends(_get_service),
    _rate_limit: bool = Depends(RateLimiter(max_requests=20, window_seconds=60))
):
    try:
        return service.complete_upload(upload_id, background_tasks)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))