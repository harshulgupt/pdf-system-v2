"""
Storage service — wraps boto3 to talk to any S3-compatible store.

Works with Backblaze B2 and Cloudflare R2.
Set R2_PUBLIC_URL to your storage endpoint:
  - Backblaze B2:   https://s3.us-west-004.backblazeb2.com
  - Cloudflare R2:  https://<account_id>.r2.cloudflarestorage.com

Presigned URLs let the browser PUT chunks directly to storage without
routing the 20 GB through our API server.
"""
import io
import re

import boto3
from botocore.config import Config

from app.config import get_settings


def _get_s3_client():
    settings = get_settings()
    endpoint = settings.r2_public_url.rstrip("/")

    # boto3 requires the endpoint to NOT end in a path segment.
    # Backblaze endpoints look like: https://s3.us-west-004.backblazeb2.com
    # We must also pass the correct region string, not "auto".
    # Extract region from B2 hostname: s3.{region}.backblazeb2.com
    host = endpoint.replace("https://", "").replace("http://", "")

    if "backblazeb2.com" in host:
        # e.g. s3.us-west-004.backblazeb2.com → region = us-west-004
        match = re.match(r"s3\.([^.]+)\.backblazeb2\.com", host)
        region = match.group(1) if match else "us-west-004"
    else:
        region = "auto"   # Cloudflare R2

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(
            signature_version="s3v4",
            # Backblaze requires path-style addressing, not virtual-hosted
            s3={"addressing_style": "path"},
        ),
        region_name=region,
    )


def generate_presigned_put_url(r2_key: str, content_type: str = "application/octet-stream") -> str:
    """
    Returns a URL the browser can use to PUT one chunk directly to storage.
    Expires in 15 minutes.
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
        ExpiresIn=900,
    )


def download_chunk_bytes(r2_key: str) -> bytes:
    """Downloads a chunk from storage for server-side text extraction."""
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
