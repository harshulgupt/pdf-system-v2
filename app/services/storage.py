"""
Storage service — wraps boto3 to talk to any S3-compatible store.

Works with both Backblaze B2 and Cloudflare R2 (and AWS S3).
The endpoint is driven entirely by R2_PUBLIC_URL in the environment:
  - Backblaze B2:   https://s3.us-west-004.backblazeb2.com
  - Cloudflare R2:  https://<account_id>.r2.cloudflarestorage.com

Presigned URLs let the browser PUT chunks directly to storage without
routing the 20 GB through our API server.

Security model:
  - Short-lived presigned PUT URL (15 min TTL) per chunk.
  - Browser calls storage directly — our server never sees the binary data.
  - Bucket CORS must allow PUT from your frontend origin.

Trade-off:
  Pro: Our server stays lightweight regardless of file size.
  Con: No server-side virus scan before storage.
       Mitigation: run a post-upload worker on storage events.
"""
import io

import boto3
from botocore.config import Config

from app.config import get_settings


def _get_s3_client():
    settings = get_settings()

    # R2_PUBLIC_URL drives the endpoint — swap providers by changing this one var.
    # Backblaze:  https://s3.us-west-004.backblazeb2.com
    # Cloudflare: https://<account_id>.r2.cloudflarestorage.com
    endpoint = settings.r2_public_url.rstrip("/")

    # Derive region from hostname for Backblaze (needs real region string).
    # Cloudflare R2 and AWS use "auto" / default.
    host = endpoint.replace("https://", "").replace("http://", "")
    parts = host.split(".")
    if "backblazeb2" in host and len(parts) >= 2:
        region = parts[1]   # e.g. "us-west-004"
    else:
        region = "auto"     # Cloudflare R2

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name=region,
    )


def generate_presigned_put_url(r2_key: str, content_type: str = "application/octet-stream") -> str:
    """
    Returns a URL the browser can use to PUT one chunk directly to storage.
    Expires in 15 minutes — enough for a slow upload of one chunk.
    """
    client = _get_s3_client()
    settings = get_settings()
    return client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.r2_bucket_name,
            "Key": r2_key,
            "ContentType": content_type,
        },
        ExpiresIn=900,  # 15 min
    )


def download_chunk_bytes(r2_key: str) -> bytes:
    """
    Downloads a chunk from storage for server-side text extraction.
    Called during the processing phase after all chunks are confirmed.
    """
    client = _get_s3_client()
    settings = get_settings()
    buf = io.BytesIO()
    client.download_fileobj(settings.r2_bucket_name, r2_key, buf)
    buf.seek(0)
    return buf.read()


def delete_chunk(r2_key: str) -> None:
    """Optional cleanup after extraction."""
    client = _get_s3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.r2_bucket_name, Key=r2_key)
