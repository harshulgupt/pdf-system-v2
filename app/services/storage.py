import io
import re
import boto3
from botocore.config import Config
from app.config import get_settings

_boto3_client = None

def _get_boto3_client():
    global _boto3_client
    if _boto3_client is not None:
        return _boto3_client

    settings = get_settings()
    endpoint = settings.b2_endpoint_url.strip()
    host = endpoint.replace("https://", "").replace("http://", "")
    match = re.match(r"s3\.([^.]+)\.backblazeb2\.com", host)
    region = match.group(1) if match else "us-west-004"

    _boto3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.b2_access_key_id.strip(),
        aws_secret_access_key=settings.b2_secret_access_key.strip(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
        region_name=region,
    )
    return _boto3_client


def initiate_multipart_upload(r2_key: str) -> str:
    client = _get_boto3_client()
    settings = get_settings()
    res = client.create_multipart_upload(Bucket=settings.b2_bucket_name, Key=r2_key)
    return res["UploadId"]


def generate_presigned_part_url(r2_key: str, upload_id: str, part_number: int) -> str:
    client = _get_boto3_client()
    settings = get_settings()
    return client.generate_presigned_url(
        ClientMethod="upload_part",
        Params={
            "Bucket": settings.b2_bucket_name,
            "Key": r2_key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=3600,
    )


def complete_multipart_upload(r2_key: str, upload_id: str) -> None:
    client = _get_boto3_client()
    settings = get_settings()

    parts_formatted = []
    part_number_marker = 0

    while True:
        parts_info = client.list_parts(
            Bucket=settings.b2_bucket_name,
            Key=r2_key,
            UploadId=upload_id,
            PartNumberMarker=part_number_marker,
        )
        for p in parts_info.get("Parts", []):
            parts_formatted.append({"PartNumber": p["PartNumber"], "ETag": p["ETag"]})
        if parts_info.get("IsTruncated"):
            part_number_marker = parts_info.get("NextPartNumberMarker")
        else:
            break

    if not parts_formatted:
        raise RuntimeError(f"No parts found for upload {upload_id}")

    client.complete_multipart_upload(
        Bucket=settings.b2_bucket_name,
        Key=r2_key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts_formatted},
    )


def download_file_to_disk(r2_key: str, dest_path: str) -> None:
    """
    Downloads the file from B2 to a local path using streaming 8 MB chunks.
    Memory stays flat regardless of file size.
    """
    client = _get_boto3_client()
    settings = get_settings()
    response = client.get_object(Bucket=settings.b2_bucket_name, Key=r2_key)
    with open(dest_path, "wb") as f:
        for chunk in response["Body"].iter_chunks(chunk_size=8 * 1024 * 1024):
            if chunk:
                f.write(chunk)


def delete_file(r2_key: str) -> None:
    client = _get_boto3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.b2_bucket_name, Key=r2_key)
