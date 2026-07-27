import os
import boto3
from botocore.client import Config
import logging

logger = logging.getLogger(__name__)

def get_s3_client():
    """Return s3 client."""
    region = os.getenv("AWS_REGION", "ap-south-1")
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    if not access_key or not secret_key:
        logger.warning("AWS credentials not found. S3 upload will fail.")
        return None
        
    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4")
    )

def upload_to_s3(file_bytes: bytes, crawl_id: str, filename: str, content_type: str = "application/octet-stream") -> str:
    """
    Uploads a file directly from memory to S3 and returns a presigned URL.
    Returns empty string if upload fails.
    """
    s3 = get_s3_client()
    if not s3:
        return ""
        
    bucket = os.getenv("AWS_S3_BUCKET", "gramosoft")
    key = f"gcrawl_artifacts/{crawl_id}/{filename}"
    
    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_bytes,
            ContentType=content_type
        )
        
        # Use the CloudFront domain to construct a shorter, clean URL
        cloudfront_domain = "https://d2q4gipm2ebkzp.cloudfront.net"
        url = f"{cloudfront_domain}/{key}"
        return url
    except Exception as e:
        logger.error(f"Failed to upload {filename} to S3: {e}")
        return ""
