from typing import Optional
from app.repositories.base import AbstractSearchRepository


class SearchService:

    def __init__(self, search_repo: AbstractSearchRepository):
        self.search_repo = search_repo

    def search(self, query: str, upload_id: Optional[str] = None, limit: int = 10) -> dict:
        if not query or len(query.strip()) < 2:
            raise ValueError("Query must be at least 2 characters")
        if limit > 50:
            limit = 50

        data = self.search_repo.search(query.strip(), upload_id, limit)
        return {
            "query": query,
            "total_occurrences": data["total_occurrences"],
            "total_chunks_matched": len(data["results"]),
            "results": data["results"],
        }