"""
Storage layer — manages binary upload chunks on disk.

Temp chunks:   ./uploads/{upload_id}/chunk_{index:06d}.bin
Assembled PDF: ./uploads/{upload_id}/assembled.pdf

After text extraction, the assembled PDF is kept for audit/retrieval.
To swap to S3: implement S3Storage with the same interface.
"""
import os
from abc import ABC, abstractmethod

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


class AbstractStorage(ABC):
    @abstractmethod
    def save_binary_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> str: ...

    @abstractmethod
    def assemble(self, upload_id: str, total_chunks: int) -> str: ...

    @abstractmethod
    def read_file(self, path: str) -> bytes: ...


class LocalStorage(AbstractStorage):

    def _dir(self, upload_id: str) -> str:
        path = os.path.join(UPLOAD_DIR, upload_id)
        os.makedirs(path, exist_ok=True)
        return path

    def save_binary_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> str:
        """
        Save one raw binary chunk to disk.
        Path: ./uploads/{upload_id}/chunk_000000.bin
        Returns the path so we can verify it exists later.
        """
        path = os.path.join(self._dir(upload_id), f"chunk_{chunk_index:06d}.bin")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def assemble(self, upload_id: str, total_chunks: int) -> str:
        """
        Concatenate all chunk files in order into one complete PDF.
        This is the reassembly step — produces a valid PDF the parser can read.
        Returns path to the assembled file.
        """
        out_path = os.path.join(self._dir(upload_id), "assembled.pdf")
        with open(out_path, "wb") as out:
            for i in range(total_chunks):
                chunk_path = os.path.join(self._dir(upload_id), f"chunk_{i:06d}.bin")
                with open(chunk_path, "rb") as f:
                    out.write(f.read())
        return out_path

    def read_file(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()


def get_storage() -> AbstractStorage:
    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "local":
        return LocalStorage()
    raise ValueError(f"Unknown storage backend: {backend}")
