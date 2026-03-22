import time
from fastapi import Request, HTTPException
from app.db.cache import get_redis_client

class RateLimiter:
    """
    Fixed-window rate limiter using Redis.
    Designed to fail open (bypass) if Redis is unavailable, ensuring the API stays up.
    """
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def __call__(self, request: Request):
        redis = get_redis_client()
        if not redis:
            return True

        # Forwarded-For header gives actual IP when behind a reverse proxy like Railway
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown_ip"

        path = request.url.path
        
        # Simple fixed window based on current Unix timestamp
        current_window = int(time.time() // self.window_seconds)
        key = f"rate_limit:{ip}:{path}:{current_window}"
        
        try:
            current = redis.incr(key)
            if current == 1:
                redis.expire(key, self.window_seconds + 5)
            
            if current > self.max_requests:
                # Need to explicitly raise the 429
                raise HTTPException(status_code=429, detail="Too Many Requests")
        except HTTPException:
            raise
        except Exception:
            # If Redis network fails during incr, fail open to avoid service disruption
            pass
            
        return True
