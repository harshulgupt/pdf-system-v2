import hashlib
import hmac
import io
import re
import urllib.parse
from datetime import datetime, timezone

import boto3
from botocore.config import Config

from app.config import get_settings


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    k_date    = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region  = _sign(k_date, region)
    k_service = _sign(k_region, "s3")
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def generate_presigned_put_url(r2_key: str, content_type: str = "application/octet-stream") -> str:
    settings   = get_settings()
    endpoint   = settings.r2_public_url.rstrip("/")
    bucket     = settings.r2_bucket_name
    access_key = settings.r2_access_key_id
    secret_key = settings.r2_secret_access_key
    host       = endpoint.replace("https://", "").replace("http://", "")

    if "backblazeb2.com" in host:
        match  = re.match(r"s3\.([^.]+)\.backblazeb2\.com", host)
        region = match.group(1) if match else "us-west-004"
    else:
        region = "auto"

    now        = datetime.now(timezone.utc)
    date_stamp = now.strftime("%Y%m%d")
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")

    encoded_key      = urllib.parse.quote(r2_key, safe="")
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    credential       = f"{access_key}/{credential_scope}"

    query_params = {
        "X-Amz-Algorithm":     "AWS4-HMAC-SHA256",
        "X-Amz-Credential":    credential,
        "X-Amz-Date":          amz_date,
        "X-Amz-Expires":       "900",
        "X-Amz-SignedHeaders": "host",
    }
    canonical_qs = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(query_params.items())
    )

    canonical_request = "\n".join([
        "PUT",
        f"/{bucket}/{encoded_key}",
        canonical_qs,
        f"host:{host}\n",
        "host",
        "UNSIGNED-PAYLOAD",
    ])

    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _get_signing_key(secret_key, date_stamp, region)
    signature   = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return f"{endpoint}/{bucket}/{encoded_key}?{canonical_qs}&X-Amz-Signature={signature}"


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


def download_chunk_bytes(r2_key: str) -> bytes:
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
