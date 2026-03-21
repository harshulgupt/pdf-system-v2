import re
import time
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


def initiate_multipart_upload(r2_key: str) -> str:
    client = _get_boto3_client()
    settings = get_settings()
    res = client.create_multipart_upload(Bucket=settings.b2_bucket_name, Key=r2_key)
    return res['UploadId']


def generate_presigned_part_url(r2_key: str, upload_id: str, part_number: int) -> str:
    client = _get_boto3_client()
    settings = get_settings()
    return client.generate_presigned_url(
        ClientMethod='upload_part',
        Params={
            'Bucket': settings.b2_bucket_name,
            'Key': r2_key,
            'UploadId': upload_id,
            'PartNumber': part_number
        },
        ExpiresIn=3600
    )


def complete_multipart_upload(r2_key: str, upload_id: str) -> None:
    client = _get_boto3_client()
    settings = get_settings()

    parts_info = client.list_parts(Bucket=settings.b2_bucket_name, Key=r2_key, UploadId=upload_id)
    if 'Parts' not in parts_info or not parts_info['Parts']:
        raise RuntimeError(f"No parts found for upload {upload_id}")

    parts_formatted = [
        {'PartNumber': p['PartNumber'], 'ETag': p['ETag']}
        for p in parts_info['Parts']
    ]

    client.complete_multipart_upload(
        Bucket=settings.b2_bucket_name,
        Key=r2_key,
        UploadId=upload_id,
        MultipartUpload={'Parts': parts_formatted}
    )

    # Give B2 time to propagate the assembled object before reading it
    time.sleep(2)


def download_file_to_disk(r2_key: str, dest_path: str) -> None:
    """Downloads file using get_object — avoids HeadObject which can 403 on B2."""
    client = _get_boto3_client()
    settings = get_settings()

    response = client.get_object(Bucket=settings.b2_bucket_name, Key=r2_key)
    with open(dest_path, "wb") as f:
        for chunk in response["Body"].iter_chunks(chunk_size=8 * 1024 * 1024):
            f.write(chunk)


def delete_file(r2_key: str) -> None:
    client = _get_boto3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.b2_bucket_name, Key=r2_key)