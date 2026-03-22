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

        from app.db.cache import get_redis_client
        import json

        query_cleaned = query.strip()
        cache_key = f"search:{query_cleaned}:{upload_id or 'all'}:{limit}"
        redis_client = get_redis_client()

        # Try to read from cache
        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                pass  # Ignore Redis errors on read

        # Cache miss, fetch from DB
        data = self.search_repo.search(query_cleaned, upload_id, limit)
        result = {
            "query": query,
            "total_occurrences": data["total_occurrences"],
            "total_chunks_matched": len(data["results"]),
            "results": data["results"],
        }

        # Save to cache
        if redis_client:
            try:
                # Cache results for 1 hour (3600 seconds)
                redis_client.setex(cache_key, 3600, json.dumps(result))
            except Exception as e:
                pass  # Ignore Redis errors on write

        return result