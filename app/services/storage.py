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

def initiate_multipart_upload(r2_key: str) -> str:
    """Starts a multipart upload and returns the UploadId."""
    client = _get_boto3_client()
    settings = get_settings()
    res = client.create_multipart_upload(Bucket=settings.b2_bucket_name, Key=r2_key)
    return res['UploadId']

def generate_presigned_part_url(r2_key: str, upload_id: str, part_number: int) -> str:
    """Generates a temporary URL for uploading a specific part."""
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
    """Fetches all uploaded parts and tells B2 to merge them."""
    client = _get_boto3_client()
    settings = get_settings()
    
    # 1. Fetch all parts that were uploaded to get their ETags
    parts_info = client.list_parts(Bucket=settings.b2_bucket_name, Key=r2_key, UploadId=upload_id)
    if 'Parts' not in parts_info or not parts_info['Parts']:
        raise RuntimeError(f"No parts found for upload {upload_id}")
        
    parts_formatted = [
        {'PartNumber': p['PartNumber'], 'ETag': p['ETag']} 
        for p in parts_info['Parts']
    ]
    
    # 2. Complete the upload
    client.complete_multipart_upload(
        Bucket=settings.b2_bucket_name,
        Key=r2_key,
        UploadId=upload_id,
        MultipartUpload={'Parts': parts_formatted}
    )

def download_file_to_disk(r2_key: str, dest_path: str, max_retries: int = 4) -> None:
    """Downloads the completely merged file from B2 directly to disk via get_object.
       By avoiding boto3's s3.transfer manager, we bypass 'HeadObject' authorization 
       quirks on Backblaze B2, while streaming directly to disk to minimize memory usage.
    """
    import time
    from botocore.exceptions import ClientError
    
    client = _get_boto3_client()
    settings = get_settings()
    
    for attempt in range(1, max_retries + 1):
        try:
            response = client.get_object(Bucket=settings.b2_bucket_name, Key=r2_key)
            with open(dest_path, 'wb') as f:
                for chunk in response['Body'].iter_chunks(chunk_size=8192):
                    f.write(chunk)
            return  # Success
        except ClientError as e:
            # 403 or 404 can occur briefly if Backblaze B2 is eventually consistent.
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['403', '404', 'NoSuchKey', 'Forbidden']:
                if attempt < max_retries:
                    time.sleep(1.5 * attempt)  # 1.5s, 3.0s, 4.5s
                    continue
            raise  # Out of retries or a different error


def delete_file(r2_key: str) -> None:
    client = _get_boto3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.b2_bucket_name, Key=r2_key)