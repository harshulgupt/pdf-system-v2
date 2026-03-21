import io
import pypdf
from app.models.models import UploadStatus
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.services.storage import download_chunk_bytes, generate_presigned_upload_url

class UploadService:
    def __init__(self, upload_repo: AbstractUploadRepository, search_repo: AbstractSearchRepository):
        self.upload_repo = upload_repo
        self.search_repo = search_repo

    def init_upload(self, filename: str, total_chunks: int) -> dict:
        upload = self.upload_repo.create_upload(filename, total_chunks)
        chunks = []
        for i in range(total_chunks):
            chunk_key = f"uploads/{upload.id}/chunk_{i:06d}"
            chunk_record = self.upload_repo.save_chunk_record(upload.id, i, chunk_key)
            chunks.append({
                "chunk_index": i,
                "chunk_key": chunk_key,
                "presigned_url": generate_presigned_upload_url(chunk_key),
                "chunk_record_id": chunk_record.id,
            })
        self.upload_repo.set_status(upload.id, UploadStatus.uploading)
        return {"upload_id": upload.id, "chunks": chunks}

    def confirm_chunk(self, upload_id: str, chunk_index: int) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        upload = self.upload_repo.increment_received_chunks(upload_id)
        return {
            "upload_id": upload_id,
            "received": upload.received_chunks,
            "total": upload.total_chunks,
            "all_received": upload.received_chunks >= upload.total_chunks,
        }

    def complete_upload(self, upload_id: str) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        if upload.received_chunks < upload.total_chunks:
            raise RuntimeError(
                f"Not all chunks received: {upload.received_chunks}/{upload.total_chunks}"
            )
        self.upload_repo.set_status(upload_id, UploadStatus.processing)
        try:
            self._process_upload(upload)
            self.upload_repo.set_status(upload_id, UploadStatus.ready)
            return {"upload_id": upload_id, "status": "ready"}
        except Exception as e:
            self.upload_repo.set_status(upload_id, UploadStatus.failed)
            raise RuntimeError(f"Processing failed: {e}") from e

    def _process_upload(self, upload) -> None:
        chunks = sorted(upload.chunks, key=lambda c: c.chunk_index)
        pdf_bytes = b"".join(download_chunk_bytes(c.r2_key) for c in chunks)

        if not pdf_bytes:
            raise RuntimeError("Downloaded PDF is empty")

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        total_pages = len(reader.pages)

        if total_pages == 0:
            raise RuntimeError("PDF has no pages or could not be read")

        pages_per_chunk = max(1, total_pages // max(len(chunks), 1))

        for chunk_record in chunks:
            start_page = chunk_record.chunk_index * pages_per_chunk
            end_page = min(start_page + pages_per_chunk, total_pages)

            if start_page >= total_pages:
                text = ""
            else:
                raw_parts = []
                for p in range(start_page, end_page):
                    try:
                        raw_parts.append(reader.pages[p].extract_text() or "")
                    except Exception:
                        raw_parts.append("")
                text = "\n".join(raw_parts)

            text = text.replace("\x00", "")
            text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
            text = text[:500_000]

            self.search_repo.save_extracted_text(chunk_record.id, text)

    def get_status(self, upload_id: str) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError("Not found")
        return {
            "upload_id": upload.id,
            "filename": upload.filename,
            "status": upload.status,
            "received_chunks": upload.received_chunks,
            "total_chunks": upload.total_chunks,
        }