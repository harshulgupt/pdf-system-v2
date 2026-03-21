import io
import os
import uuid
from fastapi import BackgroundTasks
import pypdf
from app.models.models import UploadStatus
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.services.storage import initiate_multipart_upload, generate_presigned_part_url, complete_multipart_upload, get_s3_file



class UploadService:
    def __init__(self, upload_repo: AbstractUploadRepository, search_repo: AbstractSearchRepository):
        self.upload_repo = upload_repo
        self.search_repo = search_repo

    def init_upload(self, filename: str, total_chunks: int) -> dict:
        upload_id = str(uuid.uuid4())
        r2_key = f"uploads/{upload_id}.pdf"
        multipart_upload_id = initiate_multipart_upload(r2_key)
        
        upload = self.upload_repo.create_upload(upload_id, filename, total_chunks, multipart_upload_id)
        
        chunks = []
        for i in range(total_chunks):
            part_number = i + 1
            chunk_key = r2_key
            presigned_url = generate_presigned_part_url(r2_key, multipart_upload_id, part_number)
            chunk_record = self.upload_repo.save_chunk_record(upload.id, i, chunk_key)
            chunks.append({
                "chunk_index": i,
                "chunk_key": chunk_key,
                "presigned_url": presigned_url,
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

    def complete_upload(self, upload_id: str, background_tasks: BackgroundTasks) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        if upload.received_chunks < upload.total_chunks:
            raise RuntimeError(
                f"Not all chunks received: {upload.received_chunks}/{upload.total_chunks}"
            )
            
        r2_key = f"uploads/{upload_id}.pdf"
        complete_multipart_upload(r2_key, upload.multipart_upload_id)
        
        self.upload_repo.set_status(upload_id, UploadStatus.processing)
        background_tasks.add_task(self._process_upload_async, upload_id)
        
        return {"upload_id": upload_id, "status": "processing_queued"}

    def _process_upload_async(self, upload_id: str) -> None:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            return
        try:
            self._process_upload(upload)
            self.upload_repo.set_status(upload_id, UploadStatus.ready)
        except Exception as e:
            self.upload_repo.set_status(upload_id, UploadStatus.failed)
            print(f"Processing failed for {upload_id}: {e}")

    def _process_upload(self, upload) -> None:
        chunks = sorted(upload.chunks, key=lambda c: c.chunk_index)
        
        r2_key = f"uploads/{upload.id}.pdf"
        
        try:
            # Stream directly from S3/B2 using our file-like wrapper to avoid OOM
            s3_file = get_s3_file(r2_key)
            reader = pypdf.PdfReader(s3_file)
            total_pages = len(reader.pages)
        except Exception as e:
            raise RuntimeError(f"Could not read PDF stream from S3: {e}")

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

            # Clean text for Postgres
            text = text.replace("\x00", "")
            text = "".join(
                ch for ch in text
                if ch == "\n" or ch == "\t" or ord(ch) >= 32
            )
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