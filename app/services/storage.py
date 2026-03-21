import io
import re

import boto3
from botocore.config import Config

from app.config import get_settings


def _get_s3_client():
    settings = get_settings()
    endpoint = settings.r2_public_url.rstrip("/")
    host = endpoint.replace("https://", "").replace("http://", "")

    if "backblazeb2.com" in host:
        match = re.match(r"s3\.([^.]+)\.backblazeb2\.com", host)
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


def generate_presigned_put_url(r2_key: str, content_type: str = "application/octet-stream") -> str:
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
    client = _get_s3_client()
    settings = get_settings()
    buf = io.BytesIO()
    client.download_fileobj(settings.r2_bucket_name, r2_key, buf)
    buf.seek(0)
    return buf.read()


def delete_chunk(r2_key: str) -> None:
    client = _get_s3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.r2_bucket_name, Key=r2_key)