import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.api.routes import upload, search
from app.db.database import init_db
from app.api.middleware import SecurityHeadersMiddleware, PayloadSizeLimitMiddleware, TimeoutMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PDF Processing System", version="2.0.0", lifespan=lifespan)

# Add custom security middlewares
app.add_middleware(TimeoutMiddleware, timeout=15.0)
app.add_middleware(PayloadSizeLimitMiddleware, max_payload_size=524288) # 512KB limits Memory DoS
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Kept wildcard since frontend serves from same origin or external, 
    # but tightened allowed methods to only those that exist.
    allow_origins=["*"], 
    allow_methods=["GET", "POST", "OPTIONS"], 
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api")
app.include_router(search.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error("Unhandled exception:\n%s", tb)
    # Traceback logged to Railway, NOT returned to client (security)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred."},
    )
