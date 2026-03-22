import io
import os
import uuid
from fastapi import BackgroundTasks
import pypdf
from app.models.models import UploadStatus
from app.repositories.base import AbstractUploadRepository, AbstractSearchRepository
from app.services.storage import initiate_multipart_upload, generate_presigned_part_url, complete_multipart_upload, download_file_to_disk



class UploadService:
    def __init__(self, upload_repo: AbstractUploadRepository, search_repo: AbstractSearchRepository):
        self.upload_repo = upload_repo
        self.search_repo = search_repo

    def init_upload(self, filename: str, total_chunks: int, file_hash: str = None) -> dict:
        if file_hash:
            existing = self.upload_repo.get_upload_by_hash(file_hash)
            if existing:
                return {
                    "upload_id": existing.id,
                    "status": "existing",
                    "chunks": []
                }
                
        upload_id = str(uuid.uuid4())
        r2_key = f"uploads/{upload_id}.pdf"
        multipart_upload_id = initiate_multipart_upload(r2_key)
        
        upload = self.upload_repo.create_upload(upload_id, filename, total_chunks, multipart_upload_id, file_hash=file_hash)
        
        chunks = []
        for i in range(total_chunks):
            part_number = i + 1
            presigned_url = generate_presigned_part_url(r2_key, multipart_upload_id, part_number)
            # We explicitly DO NOT create dummy database PDFChunks here anymore.
            # Semantic text chunks will be created during _process_upload async task.
            chunks.append({
                "chunk_index": i,
                "presigned_url": presigned_url,
            })
        self.upload_repo.set_status(upload.id, UploadStatus.uploading)
        return {"upload_id": upload.id, "chunks": chunks}


    def confirm_chunk(self, upload_id: str, chunk_index: int) -> dict:
        upload = self.upload_repo.get_upload(upload_id)
        if not upload:
            raise ValueError(f"Upload {upload_id} not found")
        upload = self.upload_repo.increment_received_chunks(upload_id, chunk_index)
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
        
        # Bypassing the circular import problem since storage functions are imported top-level
        complete_multipart_upload(r2_key, upload.multipart_upload_id)
        
        self.upload_repo.set_status(upload_id, UploadStatus.processing)
        
        from app.db.cache import get_redis_client
        redis_client = get_redis_client()
        
        if redis_client:
            # Shift processing workload out of FastAPI server memory into Redis queue
            redis_client.lpush("pdf_processing_queue", upload_id)
            status = "processing_queued"
        else:
            # Resilient fallback explicitly designed for minimal interruption
            background_tasks.add_task(self._process_upload_async, upload_id)
            status = "processing_background"
        
        return {"upload_id": upload_id, "status": status}

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
        r2_key = f"uploads/{upload.id}.pdf"
        
        from app.services.storage import download_file_to_disk
        import os
        
        local_path = f"/tmp/{upload.id}.pdf"
        
        try:
            # Download file to disk first.
            # This is much faster for large files than S3 byte-range streaming 
            # because `pypdf` makes many random reads/seeks.
            download_file_to_disk(r2_key, local_path)
            
            reader = pypdf.PdfReader(local_path)
            total_pages = len(reader.pages)

            if total_pages == 0:
                raise RuntimeError("PDF has no pages or could not be read")

            # Semantic text chunking (5 pages per semantic chunk to maintain context boundaries)
            pages_per_chunk = 5
            chunk_idx = 0

            for start_page in range(0, total_pages, pages_per_chunk):
                end_page = min(start_page + pages_per_chunk, total_pages)
                
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

                # Create the semantic chunk record mapped to this block of text
                chunk_record = self.upload_repo.save_chunk_record(upload.id, chunk_idx, r2_key)
                self.search_repo.save_extracted_text(chunk_record.id, text)
                chunk_idx += 1
                
        finally:
            # Always clean up the local file to preserve ephemeral disk space
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass

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