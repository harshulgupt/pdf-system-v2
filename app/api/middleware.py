import asyncio
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_payload_size: int = 524288): # 512KB limit to prevent Memory DoS
        super().__init__(app)
        self.max_payload_size = max_payload_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_payload_size:
            return JSONResponse(
                status_code=413,
                content={"detail": "Payload Too Large"}
            )
        return await call_next(request)

class TimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, timeout: float = 15.0):
        super().__init__(app)
        self.timeout = timeout

    async def dispatch(self, request: Request, call_next):
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={"detail": "Request Timeout Server Error"}
            )
