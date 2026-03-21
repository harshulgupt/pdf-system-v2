"""
Search controller — thin layer.
No business logic. No direct DB calls.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_search_repo
from app.repositories.base import AbstractSearchRepository
from app.services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


def _get_service(
    search_repo: AbstractSearchRepository = Depends(get_search_repo),
) -> SearchService:
    return SearchService(search_repo)


@router.get("/")
def search(
    q: str = Query(..., min_length=2, description="Search query"),
    upload_id: Optional[str] = Query(None, description="Limit search to one PDF"),
    limit: int = Query(10, ge=1, le=50),
    service: SearchService = Depends(_get_service),
):
    """
    Read path — search extracted text across all (or one) uploaded PDF.
    Returns ranked chunks with surrounding context snippet.
    """
    try:
        return service.search(q, upload_id, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
