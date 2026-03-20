from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.db.database import Base


class UploadSession(Base):
    """
    Tracks an in-progress chunked upload.
    Created when the first chunk arrives, marked complete when all chunks land.
    
    upload_id    : UUID the client generates before starting — ties all chunks together
    filename     : original filename
    total_chunks : how many chunks the client says it will send
    received     : how many we have so far
    status       : 'uploading' | 'assembling' | 'indexed' | 'failed'
    """
    __tablename__ = "upload_sessions"

    id           = Column(Integer, primary_key=True, index=True)
    upload_id    = Column(String, unique=True, index=True, nullable=False)
    filename     = Column(String, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    received     = Column(Integer, default=0, nullable=False)
    status       = Column(String, default="uploading", nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class PDFChunk(Base):
    """
    One row per text chunk extracted from a fully assembled PDF.
    These are TEXT chunks for search — not the binary upload chunks.
    """
    __tablename__ = "pdf_chunks"

    id           = Column(Integer, primary_key=True, index=True)
    upload_id    = Column(String, index=True, nullable=False)
    filename     = Column(String, nullable=False)
    passage_index  = Column(Integer, nullable=False)
    content      = Column(Text, nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
