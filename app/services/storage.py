import io
import re
import boto3
from botocore.config import Config
from app.config import get_settings

def _get_boto3_client():
    settings = get_settings()
    endpoint = settings.b2_endpoint_url.strip()
    host = endpoint.replace("https://", "").replace("http://", "")
    match = re.match(r"s3\.([^.]+)\.backblazeb2\.com", host)
    region = match.group(1) if match else "us-west-004"

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.b2_access_key_id.strip(),
        aws_secret_access_key=settings.b2_secret_access_key.strip(),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name=region,
    )

def generate_presigned_upload_url(r2_key: str) -> str:
    """Generates a temporary URL the browser can use to upload directly to B2."""
    client = _get_boto3_client()
    settings = get_settings()
    return client.generate_presigned_url(
        ClientMethod='put_object',
        Params={'Bucket': settings.b2_bucket_name, 'Key': r2_key},
        ExpiresIn=3600 # URL valid for 1 hour
    )

def download_chunk_bytes(r2_key: str) -> bytes:
    client = _get_boto3_client()
    settings = get_settings()
    buf = io.BytesIO()
    client.download_fileobj(settings.b2_bucket_name, r2_key, buf)
    buf.seek(0)
    return buf.read()

def delete_chunk(r2_key: str) -> None:
    client = _get_boto3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.b2_bucket_name, Key=r2_key)