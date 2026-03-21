import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum

from app.db.database import Base


class UploadStatus(str, enum.Enum):
    initiated  = "initiated"    # client called /upload/init
    uploading  = "uploading"    # chunks being sent to B2
    processing = "processing"  # backend extracting text
    ready      = "ready"       # indexed and searchable
    failed     = "failed"


def _now():
    return datetime.now(timezone.utc)


class PDFUpload(Base):
    """One row per PDF the user wants to upload."""
    __tablename__ = "pdf_uploads"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename        = Column(String, nullable=False)
    total_chunks    = Column(Integer, nullable=False)
    received_chunks = Column(Integer, default=0)
    status          = Column(Enum(UploadStatus), default=UploadStatus.initiated)
    created_at      = Column(DateTime(timezone=True), default=_now)
    updated_at      = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    chunks = relationship("PDFChunk", back_populates="upload", cascade="all, delete-orphan")


class PDFChunk(Base):
    """
    One row per chunk of a PDF.
    chunk_index is the order inside the PDF.
    r2_key is where the raw binary chunk lives in B2.
    """
    __tablename__ = "pdf_chunks"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    upload_id      = Column(String, ForeignKey("pdf_uploads.id"), nullable=False)
    chunk_index    = Column(Integer, nullable=False)
    r2_key         = Column(String, nullable=False)
    extracted_text = Column(Text, default="")
    created_at     = Column(DateTime(timezone=True), default=_now)

    upload = relationship("PDFUpload", back_populates="chunks")
