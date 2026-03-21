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

def download_file_to_disk(r2_key: str, dest_path: str) -> None:
    """Downloads the completely merged file from B2 directly to disk."""
    client = _get_boto3_client()
    settings = get_settings()
    client.download_file(settings.b2_bucket_name, r2_key, dest_path)


def delete_file(r2_key: str) -> None:
    client = _get_boto3_client()
    settings = get_settings()
    client.delete_object(Bucket=settings.b2_bucket_name, Key=r2_key)


class S3File(io.RawIOBase):
    """File-like object that streams byte ranges directly from S3/B2, preventing OOMs for large files."""
    def __init__(self, bucket: str, key: str, client):
        self.bucket = bucket
        self.key = key
        self.client = client
        self.position = 0
        
        # Backblaze B2 often presents eventual consistency delays immediately after multipart upload
        import time
        response = None
        for attempt in range(5):
            try:
                response = self.client.head_object(Bucket=self.bucket, Key=self.key)
                break
            except Exception as e:
                if attempt == 4:
                    raise RuntimeError(f"HeadObject failed after 5 attempts: {e}")
                time.sleep(1.0 + attempt * 0.5)
                
        self.size = response['ContentLength']

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self.position = offset
        elif whence == io.SEEK_CUR:
            self.position += offset
        elif whence == io.SEEK_END:
            self.position = self.size + offset
        
        self.position = max(0, min(self.position, self.size))
        return self.position

    def tell(self):
        return self.position

    def read(self, size=-1):
        if self.position >= self.size:
            return b""
        
        if size == -1:
            end = self.size - 1
        else:
            end = min(self.position + size - 1, self.size - 1)
        
        if end < self.position:
            return b""
            
        range_header = f"bytes={self.position}-{end}"
        response = self.client.get_object(Bucket=self.bucket, Key=self.key, Range=range_header)
        data = response['Body'].read()
        self.position += len(data)
        return data

    def readable(self): return True
    def seekable(self): return True

def get_s3_file(r2_key: str):
    client = _get_boto3_client()
    settings = get_settings()
    return S3File(settings.b2_bucket_name, r2_key, client)