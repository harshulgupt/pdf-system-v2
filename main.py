import logging
import traceback
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.api.routes import upload, search
from app.db.database import init_db, SessionLocal
from app.models.models import PDFUpload, UploadStatus
from app.repositories.sql_repo import SQLUploadRepository, SQLSearchRepository
from app.services.upload_service import UploadService


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def resume_interrupted_tasks():
    logger.info("Checking for interrupted upload tasks...")
    db = SessionLocal()
    try:
        # Find uploads that were stuck in 'processing' state when the server crashed/restarted
        interrupted = db.query(PDFUpload).filter(PDFUpload.status == UploadStatus.processing).all()
        if not interrupted:
            logger.info("No interrupted tasks found.")
            return

        logger.info(f"Found {len(interrupted)} interrupted tasks. Resuming...")
        upload_repo = SQLUploadRepository(db)
        search_repo = SQLSearchRepository(db)
        service = UploadService(upload_repo, search_repo)

        for upload in interrupted:
            logger.info(f"Resuming task for upload: {upload.id}")
            # Run in a background thread to not block the asyncio event loop startup
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, service._process_upload_async, upload.id)
            
    except Exception as e:
        logger.error(f"Error resuming tasks: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Robust Queue Recovery: Survive container restarts
    resume_interrupted_tasks()
    yield



app = FastAPI(title="PDF Processing System", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
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
