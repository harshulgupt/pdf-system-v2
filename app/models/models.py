import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum

from app.db.database import Base


class UploadStatus(str, enum.Enum):
    initiated = "initiated"      # client called /upload/init
    uploading = "uploading"      # chunks being sent to R2
    processing = "processing"   # backend extracting text
    ready = "ready"              # indexed and searchable
    failed = "failed"


class PDFUpload(Base):
    """One row per PDF the user wants to upload."""
    __tablename__ = "pdf_uploads"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    received_chunks = Column(Integer, default=0)
    status = Column(Enum(UploadStatus), default=UploadStatus.initiated)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    chunks = relationship("PDFChunk", back_populates="upload", cascade="all, delete-orphan")


class PDFChunk(Base):
    """
    One row per text chunk extracted from a PDF.
    This is what gets searched. chunk_index is the order inside the PDF.
    r2_key is where the raw binary chunk lives in R2.
    """
    __tablename__ = "pdf_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    upload_id = Column(String, ForeignKey("pdf_uploads.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)   # 0-based order in file
    r2_key = Column(String, nullable=False)          # key in R2 bucket
    extracted_text = Column(Text, default="")        # text pulled out by pypdf
    created_at = Column(DateTime, default=datetime.utcnow)

    upload = relationship("PDFUpload", back_populates="chunks")
