"""
Repository interfaces.

The controller and service layers depend ONLY on these abstract classes.
To swap the database, write a new concrete class that implements this interface
and change one line in the dependency injection (app/dependencies.py).
"""
from abc import ABC, abstractmethod
from typing import Optional
from app.models.models import PDFUpload, PDFChunk, UploadStatus


class AbstractUploadRepository(ABC):

    @abstractmethod
    def create_upload(self, filename: str, total_chunks: int) -> PDFUpload:
        ...

    @abstractmethod
    def get_upload(self, upload_id: str) -> Optional[PDFUpload]:
        ...

    @abstractmethod
    def increment_received_chunks(self, upload_id: str) -> PDFUpload:
        ...

    @abstractmethod
    def set_status(self, upload_id: str, status: UploadStatus) -> PDFUpload:
        ...

    @abstractmethod
    def save_chunk_record(self, upload_id: str, chunk_index: int, r2_key: str) -> PDFChunk:
        ...


class AbstractSearchRepository(ABC):

    @abstractmethod
    def save_extracted_text(self, chunk_id: str, text: str) -> None:
        ...

    @abstractmethod
    def search(self, query: str, upload_id: Optional[str], limit: int) -> list[dict]:
        """
        Returns list of dicts with keys:
          upload_id, chunk_index, snippet, filename
        """
        ...
