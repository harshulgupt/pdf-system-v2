import time
from typing import Optional, Dict, Tuple
from app.repositories.base import AbstractSearchRepository


# Lightweight global TTL cache for search results (avoids heavy Redis dependency for Railway)
# Format: {(query, upload_id, limit): (timestamp, results_dict)}
_SEARCH_CACHE: Dict[Tuple[str, Optional[str], int], Tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


class SearchService:

    def __init__(self, search_repo: AbstractSearchRepository):
        self.search_repo = search_repo

    def search(self, query: str, upload_id: Optional[str] = None, limit: int = 10) -> dict:
        if not query or len(query.strip()) < 2:
            raise ValueError("Query must be at least 2 characters")
        if limit > 50:
            limit = 50

        query_cleaned = query.strip()
        cache_key = (query_cleaned.lower(), upload_id, limit)
        
        # Check cache
        now = time.time()
        if cache_key in _SEARCH_CACHE:
            timestamp, cached_data = _SEARCH_CACHE[cache_key]
            if now - timestamp < CACHE_TTL_SECONDS:
                return cached_data
            else:
                del _SEARCH_CACHE[cache_key]

        # Cache miss, hit DB
        data = self.search_repo.search(query_cleaned, upload_id, limit)
        result = {
            "query": query_cleaned,
            "total_occurrences": data["total_occurrences"],
            "total_chunks_matched": len(data["results"]),
            "results": data["results"],
        }
        
        # Save to cache ONLY if we actually found results
        # If we cache 0 results, the user gets locked out if they search while the background extraction is still running!
        if int(result["total_occurrences"]) > 0:
            _SEARCH_CACHE[cache_key] = (now, result)
            
            # Very naive cache cleanup to prevent memory leaks in long-running processes
            if len(_SEARCH_CACHE) > 1000:
                oldest_key = min(_SEARCH_CACHE.keys(), key=lambda k: _SEARCH_CACHE[k][0])
                del _SEARCH_CACHE[oldest_key]
            
        return result