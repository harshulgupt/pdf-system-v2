"""
Storage service — handles all interaction with Backblaze B2 / S3-compatible storage.

Chunks are uploaded via our API server (proxy approach) to avoid browser CORS
restrictions on direct B2 uploads. The server receives the bytes from the browser
and forwards them to B2 using boto3.

For downloading chunks server-side during text extraction, we also use boto3.

Trade-off:
  Proxy approach: simpler, works everywhere, no CORS config needed on B2.
  Direct presigned URL: faster for large files (bypasses server), but requires
  correct CORS config on the bucket which varies by provider.
  We use proxy here as the bare-minimum working solution.
"""
import io
import re

import boto3
from botocore.config import Config

from app.config import get_settings


def _get_boto3_client():
    settings = get_settings()
    endpoint = settings.r2_public_url.rstrip("/")
    host     = endpoint.replace("https://", "").replace("http://", "")

    if "backblazeb2.com" in host:
        match  = re.match(r"s3\.([^.]+)\.backblazeb2\.com", host)
        region = match.group(1) if match else "us-west-004"
    else:
        region = "auto"

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
        region_name=region,
    )


def upload_bytes(r2_key: str, data: bytes) -> None:
    """
    Uploads raw bytes to B2 server-side.
    Called by the proxy endpoint — browser sends chunk to us, we forward to B2.
    """
    client   = _get_boto3_client()
    settings = get_settings()
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=r2_key,
        Body=data,
    )


def download_chunk_bytes(r2_key: str) -> bytes:
    """Downloads a chunk from storage for server-side text extraction."""
    client   = _get_boto3_client()
    settings = get_settings()
    buf = io.BytesIO()
    client.download_fileobj(settings.r2_bucket_name, r2_key, buf)
    buf.seek(0)
    return buf.read()


def delete_chunk(r2_key: str) -> None:
    client   = _get_boto3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.r2_bucket_name, Key=r2_key)
