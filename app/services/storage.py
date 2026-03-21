"""
Storage service — wraps boto3 to talk to Cloudflare R2.

R2 is S3-compatible, so we use boto3 with a custom endpoint_url.
Presigned URLs let the browser upload directly to R2 without routing
the 20 GB through our API server. This is the key to handling large files.

Security model:
  - The API issues a short-lived presigned PUT URL (15 min TTL) per chunk.
  - The browser calls R2 directly with that URL. No auth header needed
    because the signature is embedded in the URL.
  - R2 bucket CORS must allow PUT from your frontend origin (configured below).
  - Our server never sees the binary data — only metadata.

Trade-off:
  Pro: Our server stays lightweight regardless of file size.
  Con: We lose the ability to virus-scan bytes before they hit storage.
       Mitigation: run a post-upload Lambda / Worker on R2 events.
"""
import io
from typing import Optional

import boto3
from botocore.config import Config

from app.config import get_settings


def _get_s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def generate_presigned_put_url(r2_key: str, content_type: str = "application/octet-stream") -> str:
    """
    Returns a URL the browser can use to PUT one chunk directly to R2.
    Expires in 15 minutes — enough for a slow upload of one chunk.
    """
    client = _get_s3_client()
    settings = get_settings()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": r2_key,
            "ContentType": content_type,
        },
        ExpiresIn=900,  # 15 min
    )
    return url


def download_chunk_bytes(r2_key: str) -> bytes:
    """
    Downloads a chunk from R2 for text extraction.
    Called server-side during the processing phase.
    """
    client = _get_s3_client()
    settings = get_settings()
    buf = io.BytesIO()
    client.download_fileobj(settings.r2_bucket_name, r2_key, buf)
    buf.seek(0)
    return buf.read()


def delete_chunk(r2_key: str) -> None:
    """Optional cleanup — call if you want to remove raw chunks after extraction."""
    client = _get_s3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.r2_bucket_name, Key=r2_key)
